"""
ops_recheck — 단건 재검증 + 안전 가드  ✨ v19 신규

무엇을 하는가
  이미 알림이 나간 거래를 **지금 모델로 다시 돌려** 원래 판정과 비교한다.
  담당자가 오탐/정탐을 찍기 전에 "이게 지금도 같은 점수인가?"를 확인하는 용도이고,
  점수가 크게 달라지면 그건 모델·전처리가 바뀌었다는 뜻(= FP 사유 'model_drift').

🚨 왜 이 파일이 '가드' 위주인가 — 두 개의 조용한 오염 경로

  ① 더미 모드 오염
     MLClassifier 는 모델 로드에 실패하면 _dummy_predict() 로 빠진다.
     그건 **15% 확률로 랜덤 사기 판정**을 만드는 함수인데(ml_classifier.py:295),
     predict() 의 반환값만 봐서는 진짜 예측과 구분할 수 없다.
     detect_service 는 allow_dummy=False 로 기동 자체를 거부해 이걸 막는다.

     오탐 대시보드에서는 훨씬 위험하다. 담당자가 랜덤 숫자를 근거로 '오탐'을 찍으면
     그 라벨이 review_store 에 쌓이고 → export_training_labels() 로 재학습에 들어간다.
     **가짜 데이터가 모델을 오염시키는 폐쇄 루프**가 된다.
     → 이 모듈은 더미를 감지하면 재검증 자체를 거부한다. 폴백하지 않는다.

  ② 마스킹 데이터 오염
     워처가 detections.raw_json 에 넣는 것은 **마스킹본**이다
     (detect_service.py:713 주석 — 무인 대량 적재라 평문 PII 를 쌓지 않으려는 의도).
     옳은 결정이지만, 그 데이터로 재예측하면 값의 의미가 파괴된다:

        Customer_Birthyear      1980         → "1980년대"   (int 아님)
        Account_account_number  oVZASOzgcm   → "oV******cm" (인코더 미지의 값)
        IP_Address              171.237.22.26→ "171.237.*.*"
        Transaction_Datetime    ...22:20:34  → 날짜만

     bundle_io.is_numeric_encoder() 독스트링이 경고하는 것과 같은 종류의 파괴다.
     전처리는 이것들을 조용히 기본값으로 메우고 예측은 '성공'한다 — 숫자는 나오는데
     의미가 없다. 그래서 재검증 전에 손상도를 먼저 재고, 심하면 막는다.

핵심 API
    ok, clf, why = load_guarded(model_path)      # 더미면 ok=False
    report = mask_damage(features)               # 마스킹 손상도
    result = recheck(db, txn_id, model_path)     # 원판정 vs 현재 비교
"""

from __future__ import annotations

import re
import json
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

RECHECK_VERSION = "v19"
DEFAULT_DB = "fds_results.db"

try:
    from pipeline.ml_classifier import MLClassifier
    from pipeline import bundle_io
    from pipeline.pii_masker import PIIMasker, COLUMN_MASKERS
except ImportError:                                   # pragma: no cover
    from ml_classifier import MLClassifier
    import bundle_io
    from pii_masker import PIIMasker, COLUMN_MASKERS

try:
    from pipeline import ops_queries as oq
except ImportError:                                   # pragma: no cover
    import ops_queries as oq


# ══════════════════════════════════════════════════════════
# ① 더미 모드 가드
# ══════════════════════════════════════════════════════════

def is_dummy(clf) -> bool:
    """이 분류기가 더미(랜덤) 모드인가.

    ml_classifier.predict() 는 self.model 이 None 이면 _dummy_predict() 를 부른다.
    le_target 이 없으면 classes_ 를 못 읽어 역시 예측 경로가 성립하지 않는다.
    둘 중 하나라도 비면 나오는 숫자는 난수다.
    """
    return getattr(clf, "model", None) is None or getattr(clf, "le_target", None) is None


_CLF_CACHE: dict = {}


def load_guarded(model_path: str | None = None,
                 model_dir: str = "models/") -> tuple[bool, object | None, str]:
    """분류기를 로드하되 **더미면 거부**한다. (ok, clf, 사유)

    detect_service 의 allow_dummy=False 정책을 그대로 승계한다.
    '일단 보여주고 배지로 경고'하는 대시보드식 타협을 쓰지 않는 이유는,
    여기서 나온 숫자가 사람의 판정을 거쳐 학습 라벨이 되기 때문이다.
    """
    resolved = bundle_io.resolve_model_path(model_dir, model_path)
    if resolved is None:
        return False, None, (
            f"모델 파일을 찾지 못했습니다 (탐색 위치: {model_dir}). "
            f"재검증 없이 판정하려면 트리아지 화면의 원거래 내역만 참고하세요.")

    key = str(resolved)
    if key in _CLF_CACHE:
        clf = _CLF_CACHE[key]
    else:
        try:
            clf = MLClassifier(str(resolved))
        except Exception as e:
            return False, None, f"모델 로드 실패: {type(e).__name__}: {e}"
        _CLF_CACHE[key] = clf

    if is_dummy(clf):
        return False, None, (
            f"🚨 모델이 로드되지 않아 **더미(랜덤) 모드**입니다 — 재검증을 거부합니다.\n\n"
            f"이 상태에서 나오는 점수는 15% 확률의 난수이며(ml_classifier._dummy_predict), "
            f"그 숫자로 오탐 판정을 찍으면 잘못된 라벨이 재학습 데이터에 쌓입니다.\n"
            f"경로: `{resolved}` — 파일 존재 여부와 학습 환경 버전(scikit-learn/lightgbm)을 "
            f"확인하세요.")

    meta = getattr(clf, "meta", {}) or {}
    return True, clf, (
        f"✅ {resolved.name} · 피처 {len(getattr(clf, 'feature_cols', []))}개"
        + (f" · macro_f1 {meta.get('macro_f1_valid')}" if meta.get("macro_f1_valid") else ""))


# ══════════════════════════════════════════════════════════
# ② 마스킹 손상도
# ══════════════════════════════════════════════════════════

# 마스킹 흔적 패턴 — pii_masker 의 각 _mask_* 함수가 남기는 모양
_MASK_SIGNS = (
    re.compile(r"\*{2,}"),            # oV******cm, BJ****-**LJ, TXN_***
    re.compile(r"○"),                 # 이○○
    re.compile(r"\.\*\.\*$"),         # 171.237.*.*
    re.compile(r":\*\*:\*\*:\*\*$"),  # 44:b3:37:**:**:**
    re.compile(r"^\d{4}년대$"),        # 1980년대
    re.compile(r"\*\*\*$"),           # 강원도 ***
)

# 마스킹되면 모델 입력으로서 특히 치명적인 컬럼.
#   수치형인데 문자열이 되거나(생년), 인코더 classes_ 에 없는 값이 되는 것들.
_CRITICAL_IF_MASKED = {
    "Customer_Birthyear",             # 1980 → "1980년대" : 수치 → 문자
    "Account_account_number",         # 인코더 미지의 값
    "Recipient_Account_Number",
    "IP_Address",
    "MAC_Address",
    "Location",
}


def looks_masked(value) -> bool:
    s = str(value) if value is not None else ""
    return any(p.search(s) for p in _MASK_SIGNS)


def mask_damage(features: dict) -> dict:
    """저장된 피처가 얼마나 마스킹으로 훼손됐는지 진단.

    반환: {"masked": [...], "critical": [...], "level": ok|warn|block, "message": str}

    level 의 뜻
      ok    — 마스킹 흔적 없음. 재검증 결과를 신뢰해도 된다
      warn  — 일부 마스킹. 점수는 나오지만 원본과 다를 수 있다 (참고용 표시 필요)
      block — 치명 컬럼이 훼손됨. 재예측 결과가 무의미하므로 막는다
    """
    if not features:
        return {"masked": [], "critical": [], "level": "block",
                "message": "저장된 거래 내역이 없어 재검증할 수 없습니다."}

    masked, critical = [], []
    for k, v in features.items():
        if str(k).startswith("_"):
            continue
        if looks_masked(v):
            masked.append(k)
            if k in _CRITICAL_IF_MASKED:
                critical.append(k)

    if critical:
        return {
            "masked": masked, "critical": critical, "level": "block",
            "message": (
                f"🚫 재검증 불가 — 저장된 내역이 마스킹본이라 핵심 피처가 훼손됐습니다: "
                f"{', '.join(critical)}\n\n"
                f"예: `Customer_Birthyear` 는 1980 → '1980년대' 가 되어 수치 피처가 "
                f"문자열이 되고, 전처리는 이를 조용히 기본값으로 대체합니다. "
                f"예측은 '성공'하지만 숫자에 의미가 없습니다.\n"
                f"원본 CSV(inbox/)가 남아 있다면 그 파일로 재검증하세요."),
        }
    if masked:
        return {
            "masked": masked, "critical": [], "level": "warn",
            "message": (f"⚠️ 일부 필드가 마스킹돼 있습니다({', '.join(masked[:6])}"
                        f"{' 외' if len(masked) > 6 else ''}). "
                        f"재검증 점수는 참고용으로만 보세요."),
        }
    return {"masked": [], "critical": [], "level": "ok", "message": ""}


# ══════════════════════════════════════════════════════════
# ③ 재검증
# ══════════════════════════════════════════════════════════

def load_stored_features(db_path: str | Path, txn_id: str) -> dict:
    """detections.raw_json 에서 저장된 거래 내역을 꺼낸다 (마스킹본일 수 있음)."""
    try:
        con = oq._conn(db_path)
        has = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='detections'"
        ).fetchone()
        if not has:
            con.close()
            return {}
        r = con.execute(
            "SELECT raw_json FROM detections WHERE transaction_id=?", (str(txn_id),)
        ).fetchone()
        con.close()
        if not r or not r[0]:
            return {}
        return json.loads(r[0])
    except Exception as e:
        log.debug(f"저장 내역 조회 실패({txn_id}): {e}")
        return {}


def load_original_verdict(db_path: str | Path, txn_id: str) -> dict:
    """원래 판정(점수·유형·임계값·모델)을 꺼낸다."""
    try:
        con = oq._conn(db_path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(detections)")}
        if not cols:
            con.close()
            return {}
        want = [c for c in ("fraud_type", "risk_score", "is_anomaly",
                            "model", "threshold", "detected_at") if c in cols]
        r = con.execute(
            f"SELECT {', '.join(want)} FROM detections WHERE transaction_id=?",
            (str(txn_id),)).fetchone()
        con.close()
        return dict(zip(want, r)) if r else {}
    except Exception as e:
        log.debug(f"원판정 조회 실패({txn_id}): {e}")
        return {}


def recheck(db_path: str | Path, txn_id: str,
            model_path: str | None = None, model_dir: str = "models/",
            features: dict | None = None) -> dict:
    """단건 재검증. 원판정과 현재 모델의 결과를 비교한다.

    features 를 직접 주면(원본 CSV 에서 읽은 행 등) 저장본 대신 그것을 쓴다 —
    마스킹 훼손을 우회하는 유일한 정상 경로다.

    반환:
      {"ok": bool, "blocked": str|"", "original": {...}, "current": {...},
       "drift": {...}, "damage": {...}, "model_note": str}
    """
    out = {"ok": False, "blocked": "", "txn_id": str(txn_id),
           "original": {}, "current": {}, "drift": {}, "damage": {}, "model_note": ""}

    out["original"] = load_original_verdict(db_path, txn_id)
    feats = features if features is not None else load_stored_features(db_path, txn_id)

    # 손상도 먼저 — 모델을 로드하기 전에 막을 수 있으면 막는다(무거운 로드 회피)
    dmg = mask_damage(feats) if features is None else {
        "masked": [], "critical": [], "level": "ok",
        "message": "원본 데이터로 재검증합니다."}
    out["damage"] = dmg
    if dmg["level"] == "block":
        out["blocked"] = dmg["message"]
        return out

    ok, clf, why = load_guarded(model_path, model_dir)
    out["model_note"] = why
    if not ok:
        out["blocked"] = why
        return out

    try:
        ft, score, proba = clf.predict(feats)
    except Exception as e:
        out["blocked"] = f"재예측 실패: {type(e).__name__}: {e}"
        return out

    out["current"] = {"fraud_type": ft, "risk_score": round(float(score), 4),
                      "top3": sorted(proba.items(), key=lambda kv: -kv[1])[:3]}

    o_score = out["original"].get("risk_score")
    o_type = out["original"].get("fraud_type")
    if o_score is not None:
        delta = round(float(score) - float(o_score), 4)
        out["drift"] = {
            "점수변화": delta,
            "유형변화": (f"{o_type} → {ft}" if o_type and o_type != ft else "없음"),
            # 0.15 는 이중 임계값 간격(0.45→0.80)의 대략 1/2 — 등급이 바뀔 수 있는 크기
            "유의미": bool(abs(delta) >= 0.15 or (o_type and o_type != ft)),
            "해석": _drift_note(delta, o_type, ft, dmg["level"]),
        }
    out["ok"] = True
    return out


def _drift_note(delta: float, o_type, n_type, dmg_level: str) -> str:
    if dmg_level == "warn":
        return ("일부 필드가 마스킹된 상태로 계산됐습니다 — 이 차이는 모델 변화가 아니라 "
                "입력 훼손 때문일 수 있습니다. 원본 CSV 로 다시 확인하세요.")
    if o_type and o_type != n_type:
        return (f"예측 유형이 바뀌었습니다({o_type}→{n_type}). 모델 교체·재학습이 있었는지 "
                f"확인하고, 오탐 사유는 'model_drift' 로 기록하세요.")
    if abs(delta) >= 0.15:
        d = "상승" if delta > 0 else "하락"
        return (f"위험점수가 {abs(delta):.2f} {d}했습니다. 임계값(검토 0.45/확정 0.80) 근처라면 "
                f"알림 등급 자체가 달라졌을 수 있습니다.")
    return "원판정과 일치합니다 — 모델은 안정적입니다."


# ══════════════════════════════════════════════════════════
# ④ 트리아지 화면용 안전 표시
# ══════════════════════════════════════════════════════════

def safe_view(features: dict, level: str = "standard") -> dict:
    """트리아지 화면에 원거래 내역을 띄우기 전 마스킹.

    저장본이 이미 마스킹돼 있어도 한 번 더 통과시킨다 — 대시보드 경로로 들어온
    행(dashboard._save_detection_to_db)은 **원본을 그대로** 넣기 때문에
    (detect_service.py:713 주석이 지적한 비대칭) 평문 PII 가 섞여 있을 수 있다.
    """
    try:
        return PIIMasker(level=level).mask_row(features or {})
    except Exception as e:
        log.warning(f"마스킹 실패(빈 값 반환): {e}")
        return {}


def masked_field_names(level: str = "standard") -> list[str]:
    """현재 레벨에서 마스킹되는 컬럼 목록 — 화면 안내문용."""
    try:
        return sorted(set(PIIMasker(level=level).target_columns) & set(COLUMN_MASKERS))
    except Exception:
        return []


# ── CLI:  python -m pipeline.ops_recheck <db> <txn_id> ──
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    tid = sys.argv[2] if len(sys.argv) > 2 else None
    ok, clf, why = load_guarded(None, "models/")
    print(f"ops_recheck {RECHECK_VERSION}")
    print(" 모델:", why)
    if tid:
        r = recheck(db, tid)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
