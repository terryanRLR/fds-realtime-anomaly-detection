"""db_seed — 배포본에서 관제 화면이 비지 않도록 시연용 DB 를 깔아 준다.

왜 필요한가
  `fds_results.db` 는 운영 DB(탐지 이력·판정·알림)라 `.gitignore` 로 제외한다.
  그래서 clone 하거나 Streamlit Cloud 에 배포하면 DB 가 없고,
  ops_dashboard 는 `if not Path(DB).exists(): st.stop()` 으로 멈춘다.
  링크를 받은 사람은 KPI 가 전부 0·— 인 화면과 안내 한 줄만 보게 된다.
  로컬에는 DB 가 있어 드러나지 않던 부류의 문제다.

어떻게
  운영 DB 를 그대로 커밋하면 두 가지가 곤란하다 —
    ① 원본 거래 레코드(이름·IP·MAC·계좌번호)가 공개 저장소에 올라간다
    ② 로컬에서 앱을 쓸 때마다 DB 가 바뀌어 git 이 계속 더럽다
  그래서 **원본 레코드를 걷어낸 시드**를 따로 두고, 운영 DB 가 없을 때만 복사한다.
  시드에서 비운 것: `detections.raw_json` · `analysis_cache.payload`
  (탐지 결과·위험점수·판정·알림 이력은 그대로 남아 관제 화면이 살아난다.)

  이미 DB 가 있으면 **아무것도 하지 않는다** — 로컬 운영 이력을 덮지 않는다.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

log = logging.getLogger("db_seed")

DEFAULT_SEED = "demo/fds_results_seed.db"


def ensure_db(db_path: str | Path, seed_path: str | Path = DEFAULT_SEED) -> bool:
    """운영 DB 가 없으면 시드를 복사한다. 복사했으면 True.

    실패해도 예외를 올리지 않는다 — 시드가 없거나 쓰기 권한이 없더라도
    앱은 기존대로 "DB 없음" 안내를 띄우면 되지, 부팅이 죽으면 안 된다.
    """
    db = Path(db_path)
    try:
        if db.exists():
            return False
        seed = Path(seed_path)
        if not seed.is_file():
            log.info("시드 DB 없음 — 건너뜀 (%s)", seed)
            return False
        if db.parent and str(db.parent) not in ("", "."):
            db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed, db)
        log.info("시연용 DB 를 깔았습니다: %s → %s", seed, db)
        return True
    except Exception as e:                      # noqa: BLE001
        log.warning("시드 DB 복사 실패 (무시하고 계속): %s", e)
        return False
