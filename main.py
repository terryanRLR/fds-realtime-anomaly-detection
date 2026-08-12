"""
FDS 자동화 파이프라인 — 메인 오케스트레이터 (전면 수정)
흐름: 데이터 입력(5가지 방식) → ML 분류 → RAG 검색 → LLM 분석 → 알림 발송
"""

import time
import logging
from pipeline.data_streamer  import DataStreamer
from pipeline.ml_classifier  import MLClassifier
from pipeline.rag_searcher   import RAGSearcher
from pipeline.llm_analyzer   import LLMAnalyzer
from pipeline.notifier       import Notifier
from pipeline.pii_masker     import PIIMasker
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── 기본 설정 (대시보드 설정창에서 주입 가능) ──────────
CONFIG = {
    "risk_threshold": 0.5,
    "pii_mask_level": "standard",   # off | basic | standard | strict — LLM/알림 발송 전 마스킹
    "stream_delay":   0.5,
    "rag_top_k":      3,
    "llm_max_tokens": 256,
    "alert_email":    "담당자@example.com",
    "train_path":     "data/train.csv",
    "test_path":      "data/test.csv",
    "folder_path":    "data/",
    "model_path":     "models/lgbm_fds.pkl",
    "input_mode":     "stream",   # stream | manual | test_csv | train_csv | synthetic | folder
}


def run_pipeline(config: dict = CONFIG, rows: list = None):
    """
    Args:
        config: 파이프라인 설정
        rows  : 방식 1(manual) 사용 시 미리 준비된 row 리스트 (없으면 자동 스트리밍)
    """
    log.info(f"=== FDS 파이프라인 시작 (입력 방식: {config['input_mode']}) ===")

    streamer   = DataStreamer(
        train_path  = config["train_path"],
        test_path   = config["test_path"],
        folder_path = config["folder_path"],
    )
    classifier = MLClassifier(config["model_path"])
    rag        = RAGSearcher(top_k=config["rag_top_k"])
    analyzer   = LLMAnalyzer(max_tokens=config["llm_max_tokens"])
    notifier   = Notifier()
    # 🐛 FIX(v5): 대시보드 경로와 달리 자동화 파이프라인엔 PII 마스킹이 누락되어
    #   원본 이름·식별번호·IP·계좌번호가 그대로 LLM API/Slack/이메일로 전달되던 문제 수정.
    masker     = PIIMasker(level=config.get("pii_mask_level", "standard"))

    anomaly_count = 0

    # ── 입력 방식별 row 이터레이터 구성 ────────────────
    mode = config["input_mode"]

    if rows is not None:
        row_iter = iter(rows)

    elif mode == "stream":
        row_iter = streamer.stream()

    elif mode == "test_csv":
        row_iter = iter(streamer.from_test_csv(n=100))

    elif mode == "train_csv":
        row_iter = iter(streamer.from_train_csv(n=100))

    elif mode == "synthetic":
        row_iter = iter(streamer.from_synthetic(n=100))

    elif mode == "folder":
        row_iter = streamer.stream_folder()

    elif mode == "manual":
        # 🐛 FIX(v5): CONFIG 주석엔 있으나 분기가 없어 혼란 → 명시적 안내
        log.error("input_mode='manual'은 rows 인자로 직접 row 리스트를 전달해야 합니다 — 예: run_pipeline(config, rows=[{...}])")
        return

    else:
        log.error(f"알 수 없는 input_mode: {mode}")
        return

    # ── 메인 루프 ───────────────────────────────────────
    for idx, row in enumerate(row_iter):
        tx_id = row.get('transaction_id', idx)
        log.info(f"[{idx+1}] 거래 처리 — ID: {tx_id} | 방식: {row.get('_input_mode','?')}")

        # ① ML 분류
        fraud_type, risk_score, proba_dict = classifier.predict(row)
        log.info(f"  → 예측: {fraud_type} / 위험점수: {risk_score:.4f}")

        # ② 정상 → DB 저장 후 다음으로
        if fraud_type == "m" and risk_score < config["risk_threshold"]:
            streamer.save_normal(row, fraud_type, risk_score)
            time.sleep(config["stream_delay"])
            continue

        # ③ 이상 탐지
        anomaly_count += 1
        true_label = row.get('_true_label', '')
        log.warning(
            f"  ⚠️  이상거래 탐지! 유형: {fraud_type} | 점수: {risk_score:.4f}"
            + (f" | 실제: {true_label}" if true_label else "")
        )

        # ④ RAG 검색
        rag_context = rag.search(
            query=f"사기유형 {fraud_type} 이상거래 탐지 대응",
            fraud_type=fraud_type,
        )

        # ⑤ LLM 분석 (3단계 분리 호출) — PII 마스킹본 사용
        masked_row = masker.mask_row({k: v for k, v in row.items() if not k.startswith('_')})
        result = analyzer.analyze(
            row=masked_row,
            fraud_type=fraud_type,
            risk_score=risk_score,
            rag_context=rag_context,
        )

        # ⑥ 알림 발송 — 자유 텍스트도 패턴 기반 마스킹 (이중 안전장치)
        notifier.send_slack(text=masker.mask_text(result["slack"]))
        notifier.send_email(
            to_address=config["alert_email"],
            subject=f"[FDS 경보] 이상거래 — 유형 {fraud_type.upper()} / 점수 {risk_score:.2f}",
            body=masker.mask_text(result["email"]),
        )

        # ⑦ DB 저장
        streamer.save_result(row, fraud_type, risk_score, is_anomaly=True)
        log.info("  → 알림 발송 + DB 저장 완료")

        time.sleep(config["stream_delay"])

    log.info(f"=== 파이프라인 종료 — 총 이상거래: {anomaly_count}건 ===")
    return anomaly_count


# ── 단건 처리 (대시보드 시연용) ─────────────────────────
def process_single(row: dict, config: dict = CONFIG) -> dict:
    """
    대시보드에서 단건 거래를 처리하고 결과를 반환
    Returns:
        {
          fraud_type, risk_score, proba_dict,
          rag_context, analysis, slack, email
        }
    """
    classifier = MLClassifier(config["model_path"])
    rag        = RAGSearcher(top_k=config["rag_top_k"])
    analyzer   = LLMAnalyzer(max_tokens=config["llm_max_tokens"])

    fraud_type, risk_score, proba_dict = classifier.predict(row)

    is_anomaly = fraud_type != 'm' or risk_score >= config["risk_threshold"]

    rag_context = []
    llm_result  = {"analysis": "", "slack": "", "email": ""}

    if is_anomaly:
        rag_context = rag.search(
            query=f"사기유형 {fraud_type} 이상거래 탐지 대응",
            fraud_type=fraud_type,
        )
        # 🐛 FIX(v5): 단건 경로도 LLM 전달 전 마스킹
        masker = PIIMasker(level=config.get("pii_mask_level", "standard"))
        masked_row = masker.mask_row({k: v for k, v in row.items() if not k.startswith('_')})
        llm_result = analyzer.analyze(
            row=masked_row,
            fraud_type=fraud_type,
            risk_score=risk_score,
            rag_context=rag_context,
        )

    return {
        "fraud_type":  fraud_type,
        "risk_score":  risk_score,
        "proba_dict":  proba_dict,
        "is_anomaly":  is_anomaly,
        "rag_context": rag_context,
        "analysis":    llm_result.get("analysis",""),
        "slack":       llm_result.get("slack",""),
        "email":       llm_result.get("email",""),
        "true_label":  row.get("_true_label",""),
        "input_mode":  row.get("_input_mode",""),
    }


if __name__ == "__main__":
    run_pipeline()
