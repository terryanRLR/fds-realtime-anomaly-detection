# -*- coding: utf-8 -*-
"""
secrets_bridge — Streamlit Cloud 의 `st.secrets` 를 `os.environ` 으로 흘려보낸다.

  왜 필요한가
  ───────────────────────────────────────────────────────────
  이 프로젝트의 설정은 전부 `os.getenv(...)` 로 읽는다 — 대시보드 2개,
  watcher, pipeline 의 llm_analyzer · notifier · agent_facts 까지 예외가 없다.
  로컬에서는 `load_dotenv()` 가 `.env` 를 환경변수로 올려 주므로 이게 성립한다.

  그런데 **Streamlit Cloud 에는 `.env` 가 없다.** `.gitignore` 로 막았고,
  막지 않았더라도 비밀값을 저장소에 올리는 건 애초에 금지다. Cloud 는 대신
  `st.secrets`(App settings > Secrets)를 준다. 이 모듈이 그 둘을 잇는다.

  덕분에 **기존 코드는 한 줄도 바뀌지 않는다** — `os.getenv` 는 그대로 두고,
  값이 들어오는 통로만 하나 늘린 것이다.

  우선순위
  ───────────────────────────────────────────────────────────
      실제 환경변수 / .env  >  st.secrets  >  코드 기본값

  이미 값이 있으면 건드리지 않는다. 단 `.env` 에 `ANTHROPIC_API_KEY=` 처럼
  **빈 값**으로 선언된 키는 '설정되지 않은 것'으로 보고 secrets 로 채운다 —
  안 그러면 `.env` 를 둔 채 Cloud 에 올렸을 때 빈 문자열이 secrets 를
  가로막아 "키를 넣었는데 왜 안 되지" 가 된다.

  ⚠️ Streamlit 자체 동작과의 충돌 (실측)
  ───────────────────────────────────────────────────────────
  `st.secrets` 를 **읽는 순간** Streamlit 이 최상위(섹션에 안 들어간) 키를
  제 손으로 `os.environ` 에 밀어 넣는다. 그때 기존 값을 덮어쓴다 — 즉
  `.env` 로 올려 둔 값이 secrets 값으로 조용히 바뀐다. 위에 적은 우선순위가
  섹션 키에서는 지켜지고 최상위 키에서만 깨지는, 설명하기 어려운 상태가 된다.

  그래서 이 모듈은 `st.secrets` 에 손대기 **직전에** 환경변수를 스냅숏하고,
  Streamlit 이 덮어쓴 것을 원래 값으로 되돌린다. 결과적으로 위 우선순위가
  키가 어디에 적혔든 똑같이 성립한다.

  secrets.toml 형식 (평면 · 섹션 둘 다 받는다)
  ───────────────────────────────────────────────────────────
      USE_LLM_PROVIDER = "anthropic"
      ANTHROPIC_API_KEY = "sk-ant-..."

      [notify]                      # 섹션은 한 단계 펼쳐서 같게 취급한다
      SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/..."

  `.streamlit/secrets.toml.example` 에 전체 템플릿이 있다.
"""
from __future__ import annotations

import os

__all__ = ["load_secrets_into_env", "secrets_available"]


def _is_blank(v) -> bool:
    """미설정으로 간주할 값 — None 이거나 공백뿐인 문자열."""
    return v is None or (isinstance(v, str) and not v.strip())


def _flatten(mapping, out: dict) -> None:
    """중첩 테이블을 한 겹씩 벗겨 평면 키로 모은다 (섹션 이름은 버린다)."""
    for k, v in mapping.items():
        if hasattr(v, "items"):
            _flatten(v, out)
        else:
            out[str(k)] = v


def secrets_available() -> bool:
    """secrets.toml 이 실제로 있는가 (없다고 문제는 아니다 — 로컬은 .env 를 쓴다)."""
    try:
        import streamlit as st
        return len(st.secrets) > 0
    except Exception:
        return False


def load_secrets_into_env(override_blank: bool = True) -> list[str]:
    """
    `st.secrets` 의 값을 `os.environ` 에 채운다.

    Returns
    -------
    list[str]
        실제로 채워 넣은 **키 이름만** 돌려준다. 값은 절대 반환하지 않는다 —
        호출부가 무심코 로그나 화면에 찍어도 비밀값이 새지 않도록.

    비고
    ----
    secrets.toml 이 없으면 조용히 `[]` 를 돌려준다. 로컬 `.env` 운영에서는
    이게 정상 경로이므로 경고를 띄우지 않는다.
    """
    # ★ st.secrets 를 건드리기 전에 찍어 둔다. Streamlit 이 최상위 키를
    #   os.environ 에 덮어쓰기 때문에, 이 스냅숏이 없으면 '.env 우선' 을
    #   되살릴 방법이 없다. (모듈 docstring 의 '충돌' 항목 참고)
    before = dict(os.environ)

    flat: dict = {}
    try:
        import streamlit as st
        _flatten(st.secrets, flat)
    except Exception:
        # secrets.toml 부재 · 파싱 실패 · streamlit 밖에서 import 등 —
        # 어느 쪽이든 "secrets 는 없다" 로 처리하고 .env 경로에 맡긴다.
        return []

    # Streamlit 이 몰래 덮어쓴 값을 원상 복구 — 원래 '실제 값' 이 있던 키만.
    for key, old in before.items():
        if _is_blank(old):
            continue                       # 빈 값이었으면 secrets 로 채우는 게 맞다
        if os.environ.get(key) != old:
            os.environ[key] = old

    applied: list[str] = []
    for key, val in flat.items():
        if val is None or isinstance(val, (dict, list)):
            continue
        # ★ 판정 기준은 os.environ 이 아니라 스냅숏이다. Streamlit 이 이미
        #   덮어써 놓은 값을 보면 "원래 있던 값" 과 구분할 수 없다.
        cur = before.get(key)
        if cur is not None and not (override_blank and _is_blank(cur)):
            continue                       # 실제 값이 이미 있다 → 그쪽이 우선
        os.environ[key] = str(val)
        applied.append(key)
    return applied
