"""
asset_registry — 모델 · 데이터셋 탐색 레지스트리 (dashboard.py · ops_dashboard.py 공용)

왜 필요한가
  dashboard.py 는 사이드바에서 "탐지 모델(전역)"과 "평가 데이터셋"을 고르는데,
  그 목록을 만드는 로직(get_available_models / _discover_ds / _pick_model_key)이
  전부 dashboard.py 본문 안에 있었다. ops_dashboard.py 에 사이드바를 붙이려면
  같은 목록이 필요하고, 복붙하면 모델 하나 추가할 때마다 두 곳을 고쳐야 한다.

무엇이 여기 있고 무엇이 없나
  · 있다 — "무슨 모델·데이터셋이 있는가" (탐색 · 표시명 · 기본값 선택)
  · 없다 — 실제 로딩/추론. 그건 model_loader · dataset_loader · detect_service 몫이다.

Streamlit 의존은 캐시 데코레이터뿐이라, 없으면 캐시 없이 그대로 동작한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

ASSET_REGISTRY_VERSION = "v1"

log = logging.getLogger("asset_registry")

# ── Streamlit 캐시 브리지 (없어도 죽지 않는다) ─────────────
try:
    import streamlit as st
    _cache_data = st.cache_data
except Exception:                                      # pragma: no cover
    def _cache_data(*a, **kw):
        def deco(fn):
            return fn
        return deco if not (a and callable(a[0])) else a[0]

try:
    from i18n_data import MODEL_DESC_I18N, model_display_name
    HAS_I18N_DATA = True
except ImportError:                                    # pragma: no cover
    HAS_I18N_DATA = False
    MODEL_DESC_I18N = {}

    def model_display_name(name, lang):
        return name

# dashboard.py:224 원본 유지 — 두 앱의 기본 선택이 갈리면 안 된다
DEFAULT_DETECT_MODEL_MATCH = "lgbm_13class"   # 기본 탐지 모델   → lgbm_13class(모델).pkl
DEFAULT_DATASET_MATCH      = "parquet:tr"     # 기본 평가 데이터셋 → X_tr.parquet + y_tr.parquet

# ── 모델 목록은 detect_io 가 단일 출처 ───────────────────
#   detect_io 는 이미 배포 번들 탐색·메타 pkl 제외·자동 발견을 갖고 있고,
#   resolve_classifier() 가 같은 MODEL_DIR 기준으로 번들을 연다. 여기서 목록을
#   따로 만들면 "사이드바에는 보이는데 탐지가 안 되는 모델"이 생긴다.
#   이 모듈은 그 위에 i18n 설명·기본값 선택만 얹는다.
try:
    from pipeline import detect_io as _dio
except ImportError:                                    # pragma: no cover
    try:
        import detect_io as _dio
    except ImportError:
        _dio = None

BASE_MODEL_NAME = getattr(_dio, "BASE_MODEL_NAME", "🎯 lgbm_13class (최종·58피처)")


def _model_desc(name: str, lang: str) -> str:
    try:
        return MODEL_DESC_I18N[name][lang]
    except (KeyError, TypeError):
        return ""


# ══════════════════════════════════════════════════════════
# 이름 매칭 — 표시명이 바뀌어도 기본 선택이 깨지지 않게
# ══════════════════════════════════════════════════════════
def norm_key(s) -> str:
    """매칭 정규화 — 대소문자·공백·밑줄 차이를 무시 (auto-discovery 의 title() 변형에도 강함)."""
    return str(s).lower().replace(" ", "").replace("_", "")


def pick_key(keys, fragment, fallback=None):
    """keys 중 fragment(정규화 비교)를 포함하는 첫 키. 없으면 fallback."""
    frag = norm_key(fragment)
    for k in keys:
        if frag in norm_key(k):
            return k
    return fallback


def pick_model_key(models_dict, fragment, fallback=None):
    """모델 dict 에서 '키 또는 path' 에 fragment 가 든 첫 키.
    path 기준이라 표시명이 바뀌어도 안전하다."""
    frag = norm_key(fragment)
    for k, info in (models_dict or {}).items():
        if frag in norm_key(k) or frag in norm_key((info or {}).get('path', '')):
            return k
    return fallback


# ══════════════════════════════════════════════════════════
# 모델
# ══════════════════════════════════════════════════════════
def get_available_models(model_dir: str = "models/", lang: str = "ko") -> dict:
    """{표시명: {path, type, desc}} — detect_io 의 목록에 i18n 설명만 얹는다.

    model_dir 은 detect_io.MODEL_DIR 과 다를 경우 경고만 남기고 무시한다.
    실제 추론(resolve_classifier)이 detect_io.MODEL_DIR 기준으로 번들을 열기
    때문에, 여기서 다른 폴더를 훑으면 "목록엔 있는데 탐지가 깨지는" 모델이 생긴다.
    """
    if _dio is None:                                   # pragma: no cover
        log.warning("detect_io 미탑재 — 모델 목록을 만들 수 없습니다")
        return {"LightGBM (기본)": {"path": "models/lgbm_fds.pkl",
                                    "type": "lightgbm", "desc": ""}}
    try:
        if Path(model_dir) != Path(_dio.MODEL_DIR):
            log.debug(f"model_dir={model_dir} 무시 — detect_io.MODEL_DIR={_dio.MODEL_DIR} 사용")
    except Exception:
        pass
    avail = dict(_dio.get_available_models())
    for name, info in avail.items():
        desc = _model_desc(name, lang)
        if desc:
            avail[name] = {**info, "desc": desc}
    return avail


def default_model_name(avail: dict) -> str:
    """기본 선택 모델 — 배포 번들이 있으면 그것, 없으면 첫 항목."""
    if _dio is not None:
        try:
            return _dio.default_model_name(avail)
        except Exception:
            pass
    if BASE_MODEL_NAME in avail:
        return BASE_MODEL_NAME
    return next(iter(avail), "LightGBM (기본)")


def preferred_model_name(avail: dict) -> str:
    """최초 진입 시 자동 선택할 모델 — 설정된 기본(조각 매칭) → 배포 번들 폴백."""
    return pick_model_key(avail, DEFAULT_DETECT_MODEL_MATCH) or default_model_name(avail)


def model_path(avail: dict, name: str, model_dir: str = "models/") -> str:
    """표시명 → 실제 경로. 이름이 목록에 없으면 기본 모델 경로로 폴백."""
    info = (avail or {}).get(name)
    if info and info.get("path"):
        return info["path"]
    fallback = (avail or {}).get(default_model_name(avail or {}), {})
    return fallback.get("path") or "models/lgbm_fds.pkl"


def display_name(name: str, lang: str = "ko") -> str:
    return model_display_name(name, lang)


# ══════════════════════════════════════════════════════════
# 데이터셋
# ══════════════════════════════════════════════════════════
@_cache_data(ttl=15)
def discover_ds(folder: str = "data/") -> dict:
    """폴더 스캔 캐시 (ttl 15초 — 새 파일도 곧 반영).
    사이드바가 매 rerun 마다 디스크를 훑던 것을 막는다."""
    try:
        from pipeline.dataset_loader import discover_datasets
    except ImportError:
        try:
            from dataset_loader import discover_datasets   # pragma: no cover
        except ImportError:
            log.debug("dataset_loader 미탑재 — 데이터셋 탐색 비활성")
            return {}
    try:
        return dict(discover_datasets(folder))
    except Exception as e:
        log.debug(f"데이터셋 탐색 실패: {e}")
        return {}


def preferred_dataset(found: dict) -> str | None:
    """기본 선택 데이터셋 — 설정값 우선 → 없으면 첫 '라벨 보유' 데이터셋."""
    if not found:
        return None
    names = list(found.keys())
    return (pick_key(names, DEFAULT_DATASET_MATCH)
            or next((n for n in names if getattr(found[n], "has_label", False)), names[0]))


def dataset_label(name: str, found: dict) -> str:
    """셀렉터 표시 문자열 — 라벨 보유 여부를 아이콘으로."""
    info = (found or {}).get(name)
    return f"{'🏷️' if getattr(info, 'has_label', False) else '❔'} {name}"
