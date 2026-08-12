# 배포 순서서 — 🔴 우선순위 2건

> 이번 작업은 **기존 파일을 수정**하고 **저장된 데이터를 변환**한다.
> 지금까지의 작업(신규 파일만 추가)과 성격이 다르므로 순서를 지켜야 한다.

| # | 항목 | 영향 |
|---|---|---|
| 1 | 시간대 UTC 통일 | `detect_service.py` · `dashboard.py` 수정 + **DB 데이터 변환** |
| 2 | 분석 캐시 훅 | `watcher.py` 6줄 추가 |

---

## 사전 확인

```bash
# 현재 오염 상태 진단 (읽기만 함 — 안전)
python -m pipeline.ops_queries fds_results.db
```

`transactions.processed_at` 이 `관측=혼재 ⚠️불일치` 로 나오면 1번이 필요하다.

---

## 1단계 — 워처 정지 ⚠️ 필수

```bash
python -m pipeline.watcher_control stop
# 또는 작업 관리자에서 python.exe(watcher) 종료
```

마이그레이션 도중 워처가 새 행을 넣으면 그 행만 옛 규칙(로컬)으로 기록되어
통일이 다시 깨진다. 게다가 **어느 행이 신규인지 사후에 구분할 방법이 없다.**

> 마이그레이션 도구는 `watcher_status.last_poll` 이 2분 이내면 자동으로 거부한다.

---

## 2단계 — 드라이런 (아무것도 바꾸지 않음)

```bash
python migrate_timestamps.py fds_results.db
```

출력 예시:

```
로컬 오프셋: 32400초 (+9시간)

현황
  detections.detected_at        로컬 확정 · 30행 → UTC 변환  (예: 2026-08-05 16:10:45)
  transactions.processed_at     혼재 · 로컬 30 → 변환 / UTC 0 유지 · 판별불가 20
  notified.sent_at              이미 UTC · 30행 (변경 없음)
  watcher_status.started_at     이미 UTC · 1행 (변경 없음)

🔍 드라이런 — 실제로는 아무것도 바꾸지 않았습니다.
   60행이 변환 대상입니다.
```

**숫자가 예상과 맞는지 확인한 뒤** 다음으로 넘어간다.

### 행별 시간대를 어떻게 판별하는가

추측하지 않는다.

- `detections.detected_at` — 두 writer(`detect_service:722`, `dashboard:931/948`)가
  모두 `localtime` 을 쓰므로 **예외 없이 로컬**이다. 무조건 변환.
- `transactions.processed_at` — 애매하지만, `_save_db()` 가 `detections` 와
  `transactions` 에 **같은 호출 안에서** 쓴다는 사실을 이용한다.

  | 같은 txn_id 의 `detected_at` 과 비교 | 판정 |
  |---|---|
  | 차이 ≈ 0 | 로컬 (detect_service 가 씀) → 변환 |
  | 차이 ≈ offset | 이미 UTC (DEFAULT 가 씀) → 유지 |
  | 짝이 없음 / 설명 불가 | 건드리지 않음 |

  '미래 시각인가' 같은 휴리스틱보다 견고하다 — 오래된 행에도 통한다.

---

## 3단계 — 적용

```bash
python migrate_timestamps.py fds_results.db --apply
```

자동으로 수행되는 것:

1. `fds_results.db.bak-YYYYmmdd-HHMMSS` 백업 생성 (WAL·SHM 포함)
2. `BEGIN IMMEDIATE` 로 다른 writer 잠금
3. 변환 + `schema_migrations` 에 이력 기록
4. 검증 리포트 출력

```
✅ 적용 완료
  · detections.detected_at: 30행 변환
  · transactions.processed_at: 30행 변환 · 0행 유지 · 20행 판별불가(유지)

검증
  ✅ detections ↔ notified 평균 시차 0초 (30건 대조)
  ✅ transactions ↔ notified 평균 시차 0초 (30건 대조)
  ✅ transactions.processed_at — 미래 시각 0행
```

### 두 번 돌려도 안전하다

```
✅ 이미 적용됨 — 2026-08-06 12:11:31 UTC (offset 32400초)
두 번 적용하면 시각이 두 배로 어긋납니다. 중단합니다.
```

이중 적용은 18시간을 어긋나게 하고 원인 추적이 매우 어렵다.
`schema_migrations` 테이블로 차단한다.

---

## 4단계 — 코드 교체

`patched/` 의 세 파일로 교체한다. **반드시 원본을 백업할 것.**

```bash
copy detect_service.py detect_service.py.bak
copy dashboard.py      dashboard.py.bak
copy watcher.py        watcher.py.bak

copy patched\detect_service.py pipeline\detect_service.py
copy patched\dashboard.py      dashboard.py
copy patched\watcher.py        pipeline\watcher.py
```

### 무엇이 바뀌었나

**`detect_service.py`**

| 위치 | 변경 |
|---|---|
| 699 | `detections` DDL 기본값 `datetime('now','localtime')` → `datetime('now')` |
| 722·726 | INSERT / UPSERT 의 `detected_at` → `datetime('now')` |
| 743 | `time.strftime()` → `_utc_now()` |
| 신규 | `_utc_now()` 헬퍼 추가 |

```python
def _utc_now() -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS'. 🕐 M001 — 프로젝트 전체 시각 기준."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
```

> `time.strftime()` 은 서버 로컬시각이라 같은 컬럼의 DEFAULT
> `CURRENT_TIMESTAMP`(UTC)와 섞였다. 이게 혼재의 원인이었다.

**`dashboard.py`**

| 위치 | 변경 |
|---|---|
| 926·931·940·948 | `localtime` writer 6곳 → `datetime('now')` |
| 5333 | **표시 조회에 로컬 변환 추가** |

```sql
-- 저장은 UTC — 화면에는 로컬로 변환해서 보여준다
SELECT datetime(detected_at, 'localtime') AS detected_at, ...
```

> 이 한 줄이 없으면 메인 대시보드 이력 화면이 9시간 어긋난다.
> **읽는 쪽은 이 1곳뿐이다** (전수 조사 확인).

**`watcher.py`** — `svc = DetectService(cfg)` 직후 6줄

```python
svc = DetectService(cfg)
# 📼 분석 캐시 — 탐지 시점의 LLM 리포트·확률분포·환경을 DB에 남긴다.
#    이 훅이 없으면 근거가 Slack 발송과 함께 증발한다(복원 불가).
try:
    from pipeline.analysis_store import attach as _astore_attach
    _astore_attach(svc, cfg.db_path)
except Exception as _e:            # 캐시는 부가 기능 — 탐지를 막지 않는다
    log.warning(f'분석 캐시 훅 부착 실패(탐지는 정상 동작): {_e}')
```

기동 하드 가드(`try` / `except ModelNotReadyError`) **안쪽**에 들어간다.
훅 부착이 실패해도 자체 `try` 로 격리되어 워처는 정상 기동한다.

---

## 5단계 — 워처 재기동 · 확인

```bash
python -m pipeline.watcher_control start
python -m pipeline.ops_queries fds_results.db      # 혼재 0 확인
python -m pipeline.analysis_store fds_results.db   # 캐시 쌓이는지 확인
```

관제 대시보드 🩺 진단 탭에서 모든 컬럼이 `선언=utc (M001)` · `관측=utc` 인지 본다.

---

## 되돌리기

```bash
# DB
copy fds_results.db.bak-YYYYmmdd-HHMMSS fds_results.db

# 코드
copy detect_service.py.bak pipeline\detect_service.py
copy dashboard.py.bak      dashboard.py
copy watcher.py.bak        pipeline\watcher.py
```

`ops_queries` 는 `schema_migrations` 를 보고 선언을 자동으로 되돌리므로
관제 대시보드는 롤백 후에도 정상 동작한다.

---

## 검증

셀프테스트는 `pipeline` 패키지 안에 있다 — **모듈 경로(`-m`)로 부른다.**
`python selftest_migrate.py` 처럼 파일을 직접 실행하면 import 가 깨진다.

```bash
python -m pipeline.selftest_migrate    # 드라이런·판별·워처가드·멱등성·검증
python -m pipeline.selftest_ops        # 조회 계층·시간대 (회귀)
python -m pipeline.selftest_analysis   # 분석 캐시 (회귀)
python -m pipeline.selftest_alert      # 경보 (회귀)
python -m pipeline.selftest_recheck    # 재검증·마스킹 (회귀)

# 또는 12종 한 번에
python -m pipeline.selftest_all
```

> 예전 판에 있던 `selftest_patch.py`(패치된 writer 가 실제 UTC 인가)는
> **존재하지 않는다.** 해당 검증은 `selftest_migrate` 와 `selftest_ops` 의
> 시간대 케이스에 흡수됐다.

---

## 부수적으로 잡은 버그

회귀 테스트가 **신규 DB 첫 실행 시 죽는 버그**를 잡았다.

`review_store.counts()` 의 조기 반환이 `total` · `fp_rate` 키를 빠뜨려,
`alert_review` 테이블이 아직 없는 상태에서 `summary_line()` 이 `KeyError` 로
대시보드 전체를 죽였다.

```python
base = {v: 0 for v in VERDICTS}
base["total"] = 0          # ← 누락돼 있었음
base["fp_rate"] = None     # ← 누락돼 있었음
if not table_exists(db_path):
    return base
```

> 반환 형태는 어떤 경로로 나가든 항상 같아야 한다.
> 호출부가 키 존재를 확인하도록 만드는 API 는 언젠가 반드시 터진다.

기존 테스트는 항상 테이블을 먼저 만들어서 이 경로를 밟지 않았다.
마이그레이션 테스트용 DB(`alert_review` 없음)가 우연히 드러냈다.
