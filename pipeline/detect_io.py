"""탐지 입력 인프라 — dashboard.py 세션4/5가 쓰던 모델 로딩·분류기 해석·
데이터셋 로더·DB 저장을 별도 모듈로 뽑아냈다.

왜 뽑았나: ops_dashboard.py가 세션5를 '그대로' 이식하려면 이 로직들이 그대로
필요한데, dashboard.py는 실행형 스트림릿 스크립트라 import로 재사용할 수 없다
(임포트하면 st.set_page_config()가 두 번 호출되는 등 그대로 실행돼버린다).
그래서 순수 로직만 이 모듈로 분리했다 — dashboard.py는 아직 이 모듈을 쓰지
않지만(자기 사본을 그대로 둠), 나중에 원하면 dashboard.py도 이걸 import하도록
바꿔 완전한 단일 진실 공급원으로 만들 수 있다.
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
from pathlib import Path

import streamlit as st

log = logging.getLogger("fds.detect_io")

MODEL_DIR = Path("models")
DATA_DIR = Path("data")

BINARY_FLAGS = [
    'Customer_rooting_jailbreak_indicator', 'Customer_VPN_Indicator',
    'Customer_flag_terminal_malicious_behavior_1',
    'Customer_flag_terminal_malicious_behavior_2',
    'Customer_flag_terminal_malicious_behavior_3',
    'Unused_terminal_status', 'Unused_account_status',
    'Recipient_account_suspend_status', 'Account_release_suspention',
    'Transaction_Failure_Status', 'Another_Person_Account',
    'Flag_deposit_more_than_tenMillion',
]

# ── 계좌 이력 기본값 (v24) ─────────────────────────────────
#
# 왜 필요한가 — 직접입력이 '실재하지 않는 계좌'를 그리고 있었다
#   직접입력 행은 58피처 중 22개만 제공한다. 나머지는 Preprocessor 가
#   models/feature_defaults.json 으로 채우는데, 그 값들이 계좌 이력을
#   **0** 으로 만든다:
#
#     Account_one_month_max_amount   기본 0  ← 정상 계좌 중앙값 14,140,000
#     Account_one_month_std_dev      기본 0  ← 정상 계좌 중앙값  4,798,938
#     Account_initial_balance   기본 750,207 ← 정상 계좌 중앙값  9,680,268
#                                              (정상 데이터에 0인 행은 0.0%)
#
#   "한 달간 거래가 전혀 없던 계좌에서 8,500만원이 빠져나갔다" 는 학습 데이터에
#   없는 조합이라, 모델이 그 지점을 자신 있게 'm(정상)' 으로 읽는다.
#   실측: '자동채움(사기 프리셋)' → m · risk 0.1839 (= 정상 판정).
#         Account_one_month_max_amount 하나만 현실값으로 바꾸면 → j · 0.9871.
#         반대로 **기본 상태는 보정 후에도 m · 0.0000** — 정상은 정상으로 남는다.
#
# 값의 출처 — data/train.csv 의 **정상(Fraud_Type='m') 행 중앙값**.
#   사기 값이 아니라 '평범한 실제 계좌' 값이다. 프리셋이 사기가 되는 이유는
#   계좌를 사기처럼 꾸며서가 아니라, **계좌가 실재하게 되어** 나머지 사기 신호
#   (거액 출금·원거리·루팅·VPN)가 비로소 의미를 갖기 때문이다.
#
# 다시 계산하려면:
#   df = load_test_df("data/train.csv"); nm = df[df.Fraud_Type == "m"]
#   {c: float(nm[c].median()) for c in ACCOUNT_HISTORY_DEFAULTS}
ACCOUNT_HISTORY_DEFAULTS = {
    'Account_initial_balance': 9_680_268.0,
    'Account_one_month_max_amount': 14_140_000.0,
    'Account_one_month_std_dev': 4_798_938.0,
    'Transaction_history_with_the_account': 1.0,
    'Number_of_transaction_with_the_account': 0.0,
}

# 화면 표기 — (라벨, 도움말, 입력 step). 판정 영향력이 큰 순서로 둔다.
# ⚠ i18n 대상이 아니다 (의도적)
#   이 라벨들은 화면 장식이 아니라 **모델 피처 사전**이다 — model_meta.json 의
#   피처명, threshold_report, 사용설명서가 모두 같은 한국어 이름을 쓴다.
#   화면만 번역하면 "Account_one_month_max_amount 가 리포트에선 '최근 1개월 최대
#   거래액', 화면에선 다른 말"이 되어 대조가 불가능해진다. 피처 사전을 통째로
#   다국어화하려면 리포트·문서·메타까지 함께 가야 하므로 별도 과제로 남긴다.
ACCOUNT_HISTORY_FIELDS = {
    'Account_one_month_max_amount': (
        "최근 1개월 최대 거래액",
        "이 계좌에서 지난 한 달 가장 컸던 거래. **판정에 가장 큰 영향**을 준다 — "
        "0 으로 두면 '거래 이력이 없는 계좌'가 되어 무엇을 입력해도 정상으로 나온다.",
        1_000_000),
    'Account_one_month_std_dev': (
        "최근 1개월 거래액 표준편차",
        "평소 거래 금액이 얼마나 들쭉날쭉했는지. 작을수록 '규칙적인 계좌'다.",
        1_000_000),
    'Account_initial_balance': (
        "계좌 개설 시 잔액",
        "정상 데이터에서 0 인 행은 0.0% — 0 은 실제로 존재하지 않는 값이다.",
        1_000_000),
    'Transaction_history_with_the_account': (
        "이 상대와 거래한 적 있음",
        "1 = 기존 거래처. 처음 보는 상대(0)일수록 위험 신호가 된다.", 1),
    'Number_of_transaction_with_the_account': (
        "이 상대와의 거래 횟수", "위 항목이 1 일 때의 누적 횟수.", 1),
}

CAT_OPTIONS = {
    'Customer_Gender': ['male', 'female'],
    'Customer_credit_rating': ['A', 'B', 'C', 'D', 'E', 'S'],
    'Customer_loan_type': ['a', 'b', 'c', 'd', 'e'],
    'Account_account_type': ['a', 'b', 'c', 'd'],
    'Channel': ['ATM', 'internet', 'mobile', 'Others'],
    'Operating_System': ['Android', 'Linux', 'Others', 'Windows', 'iOS', 'macOS'],
    'Error_Code': ['a', 'c'],
    'Type_General_Automatic': ['automatic', 'general'],
    'Access_Medium': ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
}

# 모델 이름 → 경로. **파일이 없으면 get_available_models() 가 자동으로 숨긴다.**
#
# 📌 "안 쓰는 항목을 지워 목록을 단순하게" 는 실익이 없다(v24 확인):
#   · 파일이 없는 항목은 애초에 화면에 뜨지 않는다 — 런타임 비용 0
#   · "type" 필드는 현재 **어디서도 쓰이지 않는다**(로더가 확장자·내용으로 판별)
#   · 지우면, 나중에 그 파일이 생겼을 때 "🔍 Xgb Fds" 같은 자동 발견 이름으로만 뜬다
#   결론: 이름표로서만 값이 있으므로 그대로 둔다. 다시 열지 말 것.
MODEL_REGISTRY = {
    "LightGBM (기본)":    {"path": "models/lgbm_fds.pkl",     "type": "lightgbm"},
    "RandomForest":       {"path": "models/rf_fds.pkl",       "type": "sklearn"},
    "LogisticRegression": {"path": "models/lr_fds.pkl",       "type": "sklearn"},
    "XGBoost":            {"path": "models/xgb_fds.pkl",      "type": "xgboost"},
    "CatBoost":           {"path": "models/catboost_fds.pkl", "type": "catboost"},
    "MLP (신경망)":        {"path": "models/mlp_fds.pkl",      "type": "sklearn"},
}
BASE_MODEL_NAME = "🎯 lgbm_13class (최종·58피처)"

try:
    from pipeline.bundle_io import resolve_model_path as _resolve_mp, is_non_model_pkl as _is_non_model
    _BASE_MODEL_PATH = _resolve_mp(MODEL_DIR)
except Exception:
    _BASE_MODEL_PATH, _is_non_model = None, (lambda p: False)


def _mtime(p: Path):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


@st.cache_data(ttl=30)
def get_available_models() -> dict:
    """models/ 에서 실제 존재하는 모델 파일 탐색 — dashboard.py와 동일 로직."""
    available = {}
    if _BASE_MODEL_PATH is not None and Path(_BASE_MODEL_PATH).exists():
        available[BASE_MODEL_NAME] = {"path": str(_BASE_MODEL_PATH), "type": "lightgbm",
                                      "desc": "팀 배포 번들(최종 모델)"}
    for name, info in MODEL_REGISTRY.items():
        if Path(info["path"]).exists():
            available[name] = {**info, "desc": info.get("desc", "")}
    _known = {str(Path(i["path"])) for i in MODEL_REGISTRY.values()}
    if _BASE_MODEL_PATH is not None:
        _known.add(str(Path(_BASE_MODEL_PATH)))
    for pkl in MODEL_DIR.glob("*.pkl"):
        if _is_non_model(pkl) or str(pkl) in _known:
            continue
        display = pkl.stem.replace("_", " ").title()
        available[f"🔍 {display}"] = {"path": str(pkl), "type": "auto", "desc": "자동 발견됨"}
    if not available:
        available["LightGBM (기본)"] = MODEL_REGISTRY["LightGBM (기본)"]
    return available


def default_model_name(avail: dict) -> str:
    if BASE_MODEL_NAME in avail:
        return BASE_MODEL_NAME
    return next(iter(avail), "LightGBM (기본)")


@st.cache_data(show_spinner=False)
def _load_csv_cached(path_str, mt):
    p = Path(path_str)
    if not p.exists():
        return None
    import pandas as pd
    df = pd.read_csv(p)
    for c in df.select_dtypes(include='object').columns:
        if c == 'Fraud_Type':
            continue
        try:
            if df[c].nunique(dropna=False) <= 50:
                df[c] = df[c].astype('category')
        except TypeError:
            pass
    return df


def load_train_df():
    p = DATA_DIR / "train.csv"
    return _load_csv_cached(str(p), _mtime(p))


def load_test_df(path):
    p = Path(path)
    return _load_csv_cached(str(p), _mtime(p))


def discover_ds(folder):
    from pipeline.dataset_loader import discover_datasets
    return dict(discover_datasets(folder))


def resolve_seed(val: int) -> int:
    if int(val) < 0:
        return random.randint(0, 9999)
    return int(val)


@st.cache_resource(show_spinner=False)
def _get_ml_classifier_cached(model_path, mt):
    from pipeline.ml_classifier import MLClassifier
    return MLClassifier(model_path)


def get_ml_classifier(model_path):
    return _get_ml_classifier_cached(str(model_path), _mtime(Path(model_path)))


@st.cache_resource(show_spinner=False)
def _get_raw_classifier_cached(model_path, mt):
    from pipeline.preprocessor import RawRowClassifier
    return RawRowClassifier.from_bundle(MODEL_DIR, model_path)


def get_raw_classifier(model_path):
    return _get_raw_classifier_cached(str(model_path), _mtime(Path(model_path)))


def is_bundle_model(model_path) -> bool:
    try:
        if _BASE_MODEL_PATH is None:
            return False
        return Path(model_path).resolve() == Path(_BASE_MODEL_PATH).resolve()
    except Exception:
        return False


_RAW_ONLY_MARKERS = ("Transaction_Amount", "Location", "Transaction_Datetime",
                     "Time_difference", "Account_creation_datetime")


def classify_row_shape(row: dict, feature_cols=None) -> str:
    """행의 컬럼 구성 판정 → 'raw' | 'engineered' | 'unknown' (값 타입이 아니라 컬럼명 기준)."""
    keys = {str(k) for k in (row or {}) if not str(k).startswith('_') and k != 'Fraud_Type'}
    if not keys:
        return 'unknown'
    if any(m in keys for m in _RAW_ONLY_MARKERS):
        return 'raw'
    if feature_cols:
        cover = len(keys & set(feature_cols)) / max(len(feature_cols), 1)
        if cover >= 0.9:
            return 'engineered'
    return 'unknown'


def resolve_classifier(model_path, sample_row: dict):
    """(분류기, 모드정보, row정제여부) 반환 — dashboard.py._resolve_classifier와 동일 로직.
    모드정보 = (코드, 부가값1, 부가값2). 코드: 'bundle'|'encoded'|'bridge'|'mlclf'.
    문구화(번역)는 UI 레이어(ops_ui.t)에 위임해 이 모듈은 i18n에 의존하지 않는다."""
    if is_bundle_model(model_path):
        try:
            clf = get_raw_classifier(model_path)
            shape = classify_row_shape(sample_row, clf.feature_cols)
            return clf, ("bundle", len(clf.feature_cols), shape), False
        except Exception as e:
            log.warning(f"RawRowClassifier 준비 실패 → MLClassifier 폴백: {e}")

    _mlclf = get_ml_classifier(model_path)
    shape = classify_row_shape(sample_row, getattr(_mlclf, 'feature_cols', None))

    if shape == 'engineered':
        try:
            from pipeline.model_loader import make_row_classifier
            _cols = [k for k in sample_row if not str(k).startswith('_') and k != 'Fraud_Type']
            return make_row_classifier(model_path, _cols), ("encoded", None, None), True
        except Exception as e:
            log.warning(f"RowClassifier 준비 실패 → MLClassifier 폴백: {e}")

    if shape == 'raw' and Path("models/feature_bridge.pkl").exists():
        try:
            from pipeline.model_loader import discover_models as _dm
            from pipeline.feature_bridge import make_bridged_classifier
            _comps = {k: v for k, v in _dm("models/").items() if k.startswith("🧩")}
            if _comps:
                _ck = next(iter(_comps))
                return make_bridged_classifier(_comps[_ck]), ("bridge", _ck, None), False
        except Exception as e:
            log.warning(f"브리지 경로 실패 → MLClassifier 폴백: {e}")

    return _mlclf, ("mlclf", None, None), False


_ID_JUNK = {"", "nan", "none", "null", "na", "-"}


def _source_tag(source: str) -> str:
    """`ops:test_csv` → `TEST_CSV` · `ops:dataset:X_va.parquet` → `DATASET`"""
    s = str(source or "").split(":")
    tag = (s[1] if len(s) > 1 else s[0]) or "OPS"
    tag = "".join(c for c in tag if c.isalnum() or c == "_").upper()
    return tag[:12] or "OPS"


def make_txn_id(row: dict, source: str = "ops:manual") -> str:
    """거래 식별자를 정한다.

    ⚠️ CSV 의 `ID` 를 그대로 쓰면 안 되는 경우가 있다
      test.csv/train.csv 의 ID 가 `1`, `2` 같은 **행 번호**면 그건 거래 식별자가
      아니다. 파일이 다르면 같은 `1` 이 전혀 다른 거래인데, detections 는
      transaction_id 가 PK 라 **서로 덮어쓴다.** 실제 DB 에 `'1'` 과 빈 문자열
      키가 남아 있는 것이 그 흔적이다.

    규칙
      · 진짜 식별자처럼 보이면(`TXN-A1B2…`, `TRAIN_000009`) 그대로 쓴다 —
        같은 거래를 재탐지하면 같은 행이 갱신되는 것이 옳다.
      · 숫자만이거나 너무 짧으면 출처·시각을 붙여 유일하게 만든다.
        원본 ID 는 raw_json 에 그대로 남으므로 추적성은 잃지 않는다.
    """
    raw = str(row.get('ID') or row.get('transaction_id')
              or row.get('_idx') or '').strip()
    tag = _source_tag(source)
    ts = time.strftime('%Y%m%d_%H%M%S')
    if raw.lower() in _ID_JUNK:
        return f"{tag}_{ts}_{random.randint(1000, 9999)}"
    if raw.isdigit() or len(raw) < 4:
        return f"{tag}_{ts}_{raw}"
    return raw


def _utc_now() -> str:
    """detect_service._utc_now 와 같은 값. time.strftime() 은 로컬시각이라
    sqlite 의 CURRENT_TIMESTAMP(UTC)와 섞이면 한 컬럼에 두 시간대가 들어간다."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _append_transaction(con, txn_id: str, row: dict, fraud_type: str,
                        risk_score: float, is_anomaly: bool, model_name: str,
                        threshold: float, source: str, now: str) -> None:
    """알림 원장(transactions)에 한 줄 append — detect_service._save_transactions 와 동일 방식.

    존재하는 컬럼에만 INSERT 하는 이유: 이 테이블은 세대가 둘이다.
      · data_streamer/detect_service 계열 → processed_at · input_mode · true_label
      · 구 대시보드 계열                  → detected_at · model · threshold
    어느 쪽 DB에 붙어도 죽지 않아야 한다.

    append-only 인 것이 핵심이다(ops_queries.py:270 주석). 같은 거래를 다시 탐지하면
    새 알림 한 건으로 쌓인다 — 워처가 하는 것과 같고, 판정 이력이 덮어써지지 않는다.
    """
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
    except Exception:
        cols = set()
    if not cols:
        return
    payload = {
        "transaction_id": txn_id,
        "fraud_type": fraud_type,
        "risk_score": round(float(risk_score), 6),
        "is_anomaly": int(bool(is_anomaly)),
        "input_mode": source,
        "true_label": str(row.get("_true_label", "") or row.get("Fraud_Type", "") or ""),
        "model": model_name,
        "threshold": float(threshold),
        "processed_at": now,
        "detected_at": now,
    }
    use = {k: v for k, v in payload.items() if k in cols}
    if not use:
        return
    con.execute(
        f"INSERT INTO transactions ({', '.join(use)}) "
        f"VALUES ({', '.join('?' * len(use))})", tuple(use.values()))


def save_detection(db_path, row: dict, fraud_type: str, risk_score: float,
                   is_anomaly: bool, model_name: str, threshold: float,
                   source: str = "ops:manual") -> str | None:
    """탐지 1건을 DB에 남긴다 — detections upsert + transactions append. txn_id 반환.

    ⚠️ 왜 두 테이블에 쓰나 (v24 수정)
      관제 화면이 '알림 원장'으로 읽는 것은 **transactions** 다(ops_queries._ledger:
      transactions 가 있으면 detections 는 쳐다보지 않는다). detections 는
      raw_json(피처)을 얻는 보조 테이블이다 — PK UPSERT라 재탐지하면 이전 것이
      덮어써져 판정 대상 원장으로는 부적격이기 때문.

      예전에는 여기서 detections 에만 썼다. 그래서 이 앱의 ▶탐지 실행 결과가
      **트리아지 큐 · 탐지 로그 목록 · 경보 폴링 어디에도 나타나지 않았다** —
      저장은 되는데 화면에서는 도달할 수 없는 상태였고, 실제로 그렇게 갇힌 건이
      analysis_cache 에 8건 쌓여 있었다. (PATCH_NOTES5 v22 의 "수동 탐지도 DB에
      저장되므로 ops_alert 폴링이 집어간다"는 서술도 이 때문에 사실과 달랐다.)

    시각은 두 테이블 모두 **같은 UTC 문자열** 하나를 쓴다. 예전엔 sqlite 의
    datetime('now')(UTC)를 쓰면서 TZ_DECLARED 는 detections 를 'local' 로 선언해,
    🩺 진단이 74행 전부를 불일치로 표시하고 있었다.
    """
    try:
        con = sqlite3.connect(str(db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS detections (transaction_id TEXT PRIMARY KEY, "
            "fraud_type TEXT, risk_score REAL, is_anomaly INTEGER, model TEXT, "
            "threshold REAL, detected_at TEXT DEFAULT (datetime('now')), raw_json TEXT)")
        txn_id = make_txn_id(row, source)
        now = _utc_now()
        con.execute(
            "INSERT INTO detections VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(transaction_id) DO UPDATE SET fraud_type=excluded.fraud_type, "
            "risk_score=excluded.risk_score, is_anomaly=excluded.is_anomaly, "
            "model=excluded.model, threshold=excluded.threshold, "
            "detected_at=excluded.detected_at, raw_json=excluded.raw_json",
            (txn_id, fraud_type, round(float(risk_score), 6), int(bool(is_anomaly)),
             model_name, float(threshold), now,
             json.dumps({k: str(v) for k, v in row.items() if not str(k).startswith('_')},
                        ensure_ascii=False)[:4000]))
        _append_transaction(con, txn_id, row, fraud_type, risk_score, is_anomaly,
                            model_name, threshold, source, now)
        con.commit()
        con.close()
        return txn_id
    except Exception as e:
        log.warning(f"DB 적재 실패: {e}")
        return None
