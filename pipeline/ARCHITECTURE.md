# FDS 관제 · 오탐 대시보드 — 구조 및 파일 목록

> `ops_dashboard.py` v19 · 작성일 2026-08-06
> 메인 대시보드(`dashboard.py`)에서 세션5를 분리해 **관제 · 오탐 피드백 전용**으로 재설계한 앱.

---

## 1. 이 앱은 왜 따로 존재하는가

| | `dashboard.py` (메인) | `ops_dashboard.py` (신규) |
|---|---|---|
| 목적 | **분석 · 검증** | **운영 · 관제** |
| 사용 방식 | 열어서 본다 | 켜 둔다 (24시간) |
| 데이터 기준 | 검증셋(정적 라벨) | 실제 담당자 판정 |
| 화면 수명 | 세션 단위 | 상시 |
| 규모 | 5,716줄 | 388줄 + 모듈 4개 |

메인과 **같은 DB(`fds_results.db`)** 와 **같은 판정 엔진(`DetectService`)** 을 공유한다.
판정 로직을 복제하지 않으므로 "대시보드는 정상인데 알림은 왔어요" 사고가 생기지 않는다.

### 기존에 없던 것 (= 이 앱의 존재 이유)

1. **오탐 피드백 루프** — `batch_analyzer.py:491` 이 남긴 TODO 를 실제로 닫는다.
   기존 DB에는 담당자가 "이 알림은 오탐이었다"를 남길 곳이 어디에도 없었다.
2. **실제 판정 기반 임계값 튜닝** — 세션2의 비용곡선은 검증셋 기준이라 운영 분포와 다르다.
3. **자동 갱신** — 기존 워처 패널은 🔄 버튼이 전부였다. `st.fragment` 로 부분 리런한다.

---

## 2. 전체 파일 트리

```
프로젝트 루트/
│
├── ops_dashboard.py            🆕 관제 앱 본체 (3,033줄) ★ streamlit run 대상
├── migrate_timestamps.py       🆕 시간대 UTC 통일 마이그레이션 (M001)
├── secrets_bridge.py           🆕 st.secrets → os.environ (Streamlit Cloud 대응)
├── dashboard.py                   ✏️ 수정 — localtime writer 6곳 → UTC, 표시 1곳 보정
├── watcher.py                     ✏️ 수정 — 분석 캐시 훅 6줄
├── i18n_data.py                   4개국어 문자열 (1,705줄)
│
├── pipeline/
│   │  ── 🆕 관제 콘솔과 함께 들어온 것 ─────────────
│   ├── ops_ui.py               🆕 테마·다국어·CSS (1,848줄 — 이 계층에서 가장 크다)
│   ├── ops_alert.py            🆕 실시간 경보 — 사운드·팝업·데스크톱 (840줄)
│   ├── ops_queries.py          🆕 조회·분석 레이어, 읽기 전용 (782줄)
│   ├── ops_dispatch.py         🆕 발송 + 감사 로그·2단계 삭제 (718줄)
│   ├── ops_sidebar.py          🆕 관제 사이드바 (487줄)
│   ├── ops_guide.py            🆕 온보딩 안내 (462줄)
│   ├── ops_shift.py            🆕 SLA 경과·교대 인수인계 (359줄)
│   ├── ops_recheck.py          🆕 재검증 + 안전 가드 (353줄)
│   ├── ops_agent.py            🆕 챗봇 액션 화이트리스트 (305줄)
│   ├── review_store.py         🆕 오탐 판정 저장소 (807줄)
│   ├── analysis_store.py       🆕 탐지 시점 분석 캐시 (501줄)
│   ├── detect_io.py            🆕 원장 이원화·거래ID·계좌이력 (424줄)
│   ├── audit_store.py          🆕 감사 로그 저장소 (269줄)
│   ├── status_push.py          🆕 상태 외부 내보내기·잠금 하트비트 (225줄)
│   ├── asset_registry.py       🆕 모델·자산 레지스트리 (191줄)
│   │
│   │  ── 🔗 두 앱이 함께 쓰는 공용 계층 ─────────────
│   │     (같은 코드가 양쪽에 복사돼 한쪽만 썩는 사고를 3번 겪고 뽑아냈다)
│   ├── detect_workbench.py     🆕 프롬프트/RAG 편집기·위젯 헬퍼 (875줄)
│   ├── detect_ui.py            🆕 위험 게이지·확률 막대·유형 카드 (732줄)
│   ├── preprocessor.py         🆕 원본 행 → 58피처 변환 (495줄)
│   │
│   │  ── 재활용 ──────────────────────────────────
│   ├── detect_service.py       ✏️ 수정 — 타임스탬프 UTC 통일 (_utc_now 추가)
│   ├── watcher_panel.py           워처 상태 패널 (읽기 전용)
│   ├── watcher_control.py         워처 시작·중지
│   ├── watcher_config.py          임계값 핫 리로드 설정
│   ├── ml_classifier.py           모델 추론
│   ├── model_loader.py            다형식 로더 (.pkl/.onnx/.pmml/.sql)
│   ├── bundle_io.py               joblib/pickle 안전 로드
│   ├── pii_masker.py              개인정보 마스킹
│   ├── llm_analyzer.py            LLM 분석
│   ├── notifier.py                Slack/Email 발송
│   ├── notify_visuals.py          알림용 이미지 생성
│   ├── rule_checker.py            규칙 기반 검증
│   ├── batch_analyzer.py          배치 종합 보고서
│   ├── evaluator.py               성능 평가
│   ├── dataset_loader.py          데이터셋 검색·로딩
│   ├── data_streamer.py           입력 스트리머
│   ├── feature_bridge.py          피처 변환
│   ├── rag_searcher.py            Chroma 벡터 검색
│   ├── chat_agent.py              챗봇 에이전트
│   ├── agent_facts.py             에이전트 컨텍스트·자가진단
│   └── speech_to_text.py          음성 입력
│
├── models/                        모델 번들 (재활용)
│   ├── lgbm_13class(최종).pkl        58피처 · 13클래스 · macro-F1 0.6138
│   ├── label_encoders.pkl
│   ├── le_target.pkl
│   ├── feature_cols.json
│   ├── feature_defaults.json
│   └── model_meta.json
│
├── data/                          데이터셋 (재활용)
├── inbox/                         워처 감시 폴더
│
├── fds_results.db                 ★ 공유 SQLite (WAL 모드)
├── watcher_config.json            임계값 핫 리로드 설정
├── watcher.log                    워처 로그
│
└── pipeline/selftest_*.py         자가 검증 12종
    ├── selftest_all.py            ★ 통합 러너 — 이것만 부르면 된다
    ├── selftest_ui.py             화면 회귀 — AppTest 로 두 앱 부팅 (느림)
    ├── selftest_preprocessor.py   배치 불변식·시도 매핑 (느림)
    ├── selftest_ops.py            조회 계층·시간대
    ├── selftest_alert.py          경보 폴링·등급·렌더
    ├── selftest_analysis.py       분석 캐시
    ├── selftest_dispatch.py       발송 감사 로그·2단계 삭제
    ├── selftest_detect_io.py      원장 이원화·거래ID·계좌이력
    ├── selftest_status_push.py    상태 내보내기·잠금 하트비트
    ├── selftest_agent.py          챗봇 액션 화이트리스트·파싱
    ├── selftest_shift.py          SLA 경과·교대 인수인계
    ├── selftest_recheck.py        재검증·마스킹
    └── selftest_migrate.py        시간대 마이그레이션
```

관제 계층은 처음 7개 파일로 시작해 **ops·detect 계열 18개 모듈**로 자랐다.
`dashboard.py` 는 5,744줄짜리 파일이라 여전히 **최소 침습**이 원칙이고,
두 앱이 함께 쓰는 것은 위 '공용 계층'으로 뽑아 한 벌만 유지한다.
배포 순서는 [`MIGRATION_RUNBOOK.md`](MIGRATION_RUNBOOK.md) 참조.

---

## 3. 신규 모듈 상세

### 3.1 `pipeline/review_store.py` — 오탐 판정 저장소

신규 테이블 `alert_review` 의 유일한 **쓰기** 경로.

```sql
CREATE TABLE alert_review (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id       TEXT NOT NULL,
    alert_ref    INTEGER,          -- transactions.id
    verdict      TEXT NOT NULL,    -- tp | fp | fn | unclear
    reason       TEXT,             -- FP_REASONS 코드
    memo, reviewer TEXT,
    -- 판정 '당시' 스냅샷
    tier, risk_score, fraud_type, th_review, th_confirm, model,
    source       TEXT,
    reviewed_at  TEXT NOT NULL     -- ⚠ UTC 고정
);
```

#### 설계 결정 2가지

**① 추가 전용 (append-only)** — 판정을 `UPDATE` 하지 않는다. 재판정하면 새 행이 쌓이고
최신 행이 현재 판정이다.

> 기존 `detections` 테이블은 `transaction_id` PK + UPSERT 라 재탐지하면
> **이전 판정이 소리 없이 덮어써진다**(`detect_service.py:722`).
> 감사 대상인 사람의 판정에 그 구조를 쓸 수 없어 의도적으로 다르게 만들었다.

**② 판정 시점 스냅샷 동봉** — 워처 임계값은 `watcher_config.json` 으로 **핫 리로드**된다.
`th_review=0.45` 에서 내린 "오탐"과 `0.60` 에서 내린 "오탐"은 비교 불가다.
스냅샷이 없으면 임계값 시뮬레이터가 전부 거짓말이 된다.

#### 주요 API

| 함수 | 설명 |
|---|---|
| `record(db, txn_id, verdict, ...)` | 판정 1건 기록 |
| `record_many(db, items)` | 일괄 판정 (단일 트랜잭션) |
| `current(db, txn_ids)` | txn_id 별 **최신** 판정 |
| `history(db, txn_id)` | 판정 이력 전체 (감사용) |
| `counts(db, since_hours)` | 집계 + 오탐률 |
| `reason_counts(db)` | 오탐 사유별 분포 |
| `export_training_labels(db)` | 재학습용 라벨 + 피처 |
| `undo_last(db, txn_id)` | 유일한 파괴적 연산 |

#### 오탐 사유 코드

사유 없는 오탐률은 행동으로 이어지지 않는다.
`legit_customer` 가 많으면 → **임계값**을 올릴 것,
`model_drift` 가 많으면 → **재학습**이 필요한 것. 처방이 완전히 다르다.

| 코드 | 의미 |
|---|---|
| `legit_customer` | 정상 고객 확인됨 (본인 거래) |
| `known_pattern` | 기존 예외 패턴 (해외출장·급여일 등) |
| `test_data` | 테스트/내부 거래 |
| `data_error` | 데이터 오류·중복 유입 |
| `model_drift` | 모델 오작동 의심 |
| `rule_overfit` | 룰 과민반응 |
| `other` | 기타 |

---

### 3.2 `pipeline/ops_queries.py` — 조회·분석 레이어 (읽기 전용)

`mode=ro` URI 로 연다 — 무인 워처의 쓰기를 절대 막지 않는다.

#### 이 파일이 존재하는 진짜 이유: 시간대

DB 전수 조사 결과, **테이블마다 시간대가 다르다.**

| 테이블.컬럼 | 쓰는 코드 | 시간대 |
|---|---|---|
| `watcher_status.started_at` / `last_poll` | `watcher.py:185,187` | **UTC** |
| `watch_cursor.updated_at` | `watcher.py:175` | **UTC** |
| `notified.sent_at` | `detect_service.py:668` | **UTC** |
| `detections.detected_at` | `detect_service.py:722` | **LOCAL** |
| `transactions.processed_at` (detect_service) | `detect_service.py:743` | **LOCAL** |
| `transactions.processed_at` (DEFAULT) | `detect_service.py:600` | **UTC** ⚠️ |

마지막 두 줄 — **같은 컬럼에 UTC 행과 KST 행이 섞여 들어간다.**
각 테이블을 따로 보는 기존 화면에서는 안 터지지만, 오탐 대시보드는 이것들을
**하나의 타임라인에 합쳐야** 한다. 그 순간 9시간짜리 유령 피크가 생긴다.

→ 모든 조회가 이 모듈을 통과하며 UTC 로 정규화되고, 화면 표시 직전에만 로컬로 되돌린다.
→ `diagnose_timestamps()` 가 현재 오염 상태를 보고한다 (진단 탭).

> ⚠️ **근본 해결은 아니다.** 진짜 고치려면 `detect_service` 가 전부
> `datetime('now')` 로 통일해야 한다. 이 모듈은 기존 데이터를 버리지 않으면서 읽는 임시방편이다.

#### 알림 원장 선택

`detections` 는 UPSERT 라 이력이 날아간다 → **`transactions`**(AUTOINCREMENT, append-only)를
알림 원장으로 쓰고, `detections` 는 `raw_json`(피처)을 얻는 보조 테이블로만 쓴다.

#### 주요 API

| 함수 | 설명 |
|---|---|
| `diagnose_timestamps(db)` | 시간대 오염 진단 |
| `alert_queue(db, ...)` | 판정 대기 알림 큐 |
| `live_feed(db, limit)` | 실시간 탐지 피드 |
| `fp_timeline(db, bucket)` | 오탐률 추이 |
| `fp_by_dimension(db, dim)` | 유형/등급/점수구간별 오탐 |
| `threshold_whatif(db, ...)` | 임계값 시뮬레이터 |
| `coverage(db)` | 판정 커버리지 = 오탐률의 신뢰도 |

---

### 3.3 `pipeline/ops_recheck.py` — 재검증 + 안전 가드

단건을 지금 모델로 다시 돌려 원판정과 비교한다.
파일의 대부분이 **가드**인 이유는 조용한 오염 경로가 둘 있기 때문이다.

#### ① 더미 모드 오염

`MLClassifier` 는 모델 로드 실패 시 `_dummy_predict()` 로 빠진다 —
**15% 확률 랜덤 사기 판정**(`ml_classifier.py:295`)인데 반환값만 봐선 구분이 안 된다.

```
더미 난수 → 담당자 "오탐" 판정 → export_training_labels() → 재학습
```

**가짜 데이터가 모델을 오염시키는 폐쇄 루프**가 된다.
→ 더미를 감지하면 재검증 자체를 **거부**한다. 폴백하지 않는다.
(`DetectService` 의 `allow_dummy=False` 정책 승계)

#### ② 마스킹 데이터 오염

워처가 `detections.raw_json` 에 넣는 것은 **마스킹본**이다(`detect_service.py:713`).
옳은 결정이지만 그 데이터로 재예측하면 값의 의미가 파괴된다.

실제 `pii_masker` 출력으로 검증한 결과:

| 마스킹 레벨 | 판정 | 훼손 | 치명 컬럼 |
|---|---|---|---|
| `basic` | ⚠️ warn | 3개 | 0개 |
| `standard` ← **워처 기본값** | 🚫 block | 7개 | 4개 |
| `strict` | 🚫 block | 8개 | 5개 |

```
Account_account_number   oVZASOzgcm      → oV******cm     (인코더 미지의 값)
IP_Address               171.237.22.26   → 171.237.*.*
Location                 강원도 고성군 ... → 강원도 ***
Customer_Birthyear       1980            → 1980년대        (수치 → 문자)
```

전처리는 이것들을 조용히 기본값으로 메우고 **예측은 "성공"한다** — 숫자에 의미가 없을 뿐.
→ `mask_damage()` 가 모델 로드 **전에** 막는다 (무거운 로드도 회피).
→ 우회 경로는 하나: `recheck(..., features=원본행)` — `inbox/` 원본 CSV 사용.

#### 주요 API

| 함수 | 설명 |
|---|---|
| `load_guarded(path)` | 더미면 `ok=False` |
| `mask_damage(features)` | `ok` / `warn` / `block` |
| `recheck(db, txn_id)` | 원판정 vs 현재 비교 + 드리프트 해석 |
| `safe_view(features, level)` | 화면 표시용 마스킹 |

> `safe_view` 가 이미 마스킹된 데이터에도 한 번 더 적용되는 이유:
> `dashboard._save_detection_to_db` 는 **원본을 그대로** 넣는다
> (`detect_service.py:713` 주석이 지적한 비대칭). 평문 PII 가 섞여 있을 수 있다.

---

### 3.4 `pipeline/ops_ui.py` — 테마 · 다국어 · CSS

#### i18n 전략: `i18n_data.py` 를 수정하지 않는다

```
신규 문구 (오탐 판정 등)  → ops_ui._OPS 표 (4개국어 직접 정의)
기존 문구 (사기 유형명 등) → i18n_data 에 위임
어디에도 없으면          → 키를 그대로 반환
```

`dashboard.py` 의 `tt()` + `_V5_KO` 폴백 패턴과 같은 방식.
`i18n_data.py` 가 없거나 구버전이어도 한국어로는 동작한다.

**사기 유형명은 반드시 `i18n_data` 에서 가져온다.** 같은 제품인데
세션3에선 "위장 최종인출", 관제 화면에선 다른 말이면 곤란하다.

#### 테마

`dashboard.py:206` 의 `NEW_THEMES` 7종을 **색상값 그대로** 옮겼다.
기본값만 `amber` 로 바꿨는데, `i18n_data` 가 이 테마에 붙인 이름이
**"야간 관제 앰버(Night-watch Amber)"** 라 24시간 관제 화면의 의도와 정확히 맞기 때문이다.

---

## 4. 화면 구성 (5탭)

| 탭 | 내용 | 신규 여부 |
|---|---|---|
| 🟢 **실시간 감시** | 워처 생존·KPI·라이브 피드 (`st.fragment` 자동 갱신) + 기존 `watcher_panel` 임베드 | 자동 갱신 신규 |
| 🚨 **알림 트리아지** | 판정 대기 큐 → 정탐/오탐/미탐/보류 찍기 + 사유·메모 + 재검증 | **전부 신규** ★ |
| 🗃 **탐지 로그** | 로그 표 → 행 클릭 → 당시 데이터·LLM 분석·확률·발송본문·환경·판정이력 | **전부 신규** ★ |
| 📉 **오탐 분석** | 오탐률 추이·차원별 분포·사유 분포·커버리지 + 재학습 라벨 내보내기 | **전부 신규** |
| ⚙ **임계값 튜닝** | 실제 판정 기반 비용곡선 → `watcher_config` 즉시 적용 | **전부 신규** |
| 🩺 **진단** | 시간대 정합성·모델 상태·모듈 버전 | **전부 신규** |

### 임계값 시뮬레이터의 선택 편향 경고

우리는 **실제로 알림이 나간 거래만** 관측한다. 과거 `th_review` 아래로 깔려서
알림이 안 간 거래에는 판정이 없다.

| 구간 | 신뢰도 |
|---|---|
| τ ≥ 과거 최저 `th_review` | ✅ 신뢰 가능 — 알림을 줄였을 때의 효과 |
| τ < 과거 최저 `th_review` | ❌ **데이터 없음** — 새 알림이 몇 % 오탐일지 추정 불가 |

화면에서 회색 점선 + 경계선으로 표시한다. 그냥 그리면 그럴듯한 거짓말이 되기 때문이다.

---

## 5. 데이터 흐름

```
inbox/*.csv
    ↓  watcher.py (5초 폴링)
DetectService.detect()  ←── watcher_config.json (핫 리로드)
    ↓
    ├─→ transactions    (append-only) ── 알림 원장
    ├─→ detections      (UPSERT)      ── 피처 저장 (마스킹본)
    ├─→ notified                      ── 중복 억제
    ├─→ analysis_cache  (append-only) ── 🆕 LLM 리포트·확률·환경 스냅샷
    │        ↑ astore.attach(svc) 훅이 여기서 가로챈다
    └─→ Slack / Email

        ↓ ops_queries (읽기 전용, UTC 정규화)
    ops_dashboard 트리아지 · 로그 탭
        ↓ 담당자 판정
    review_store → alert_review  (append-only, UTC)
        ↓
        ├─→ 오탐률·사유 분석
        ├─→ 임계값 시뮬레이터 → watcher_config.json → 워처 (재시작 불필요)
        └─→ export_training_labels() → 재학습
```

---

## 5.5 독립 실행 · 폴더 분리

`ops_dashboard.py` 는 **`dashboard.py` 를 전혀 참조하지 않는다** (import 0건).
`dashboard.py` 를 삭제한 폴더에서 실행해도 예외 0으로 정상 동작하는 것을 검증했다.
둘은 같은 폴더에 있어도 각각 독립적으로 뜬다 — 한쪽만 켜도 되고, 둘 다 켜도 서로 막지 않는다.

### 완전히 분리하고 싶다면

관제 앱만 별도 폴더/서버로 떼려면 아래만 복사하면 된다.

```
ops_console/                        ← 새 폴더
├── ops_dashboard.py
├── i18n_data.py                    (문구·테마 라벨)
├── fds_results.db                  ← ⚠ 심볼릭 링크 또는 같은 PC 경로
└── pipeline/
    ├── __init__.py
    ├── ops_ui.py  ops_alert.py  review_store.py  ops_queries.py  ops_recheck.py
    ├── watcher_panel.py  watcher_control.py  watcher_config.py
    ├── ml_classifier.py  bundle_io.py  pii_masker.py
    └── detect_service.py           (재검증에 간접 참조)
```

> ⚠️ **DB 만은 공유해야 한다.** 워처가 쓰고 관제가 읽는 구조라 복사본을 두면
> 영원히 빈 화면이 된다. 같은 PC라면 `FDS_DB_PATH` 로 원래 경로를 가리키게 하는 것이 가장 안전하다.
>
> ```bash
> set FDS_DB_PATH=C:\fds\fds_results.db
> streamlit run ops_dashboard.py --server.port 8502
> ```

`i18n_data.py` 가 없으면 한국어로 폴백해 계속 동작한다(`ops_ui.HAS_I18N_DATA=False`).
`ops_recheck` 계열이 없으면 재검증 기능만 비활성화되고 나머지는 정상이다.

---

## 5.6 실시간 경보 (`ops_alert.py`)

워처가 새 이상거래를 넣으면 **어느 탭에 있든** 화면 위에 경보 카드가 뜨고,
삐용삐용 사이렌이 울리고, 윈도우 알림이 나간다. 클릭하면 해당 거래의 트리아지로 이동한다.
전부 토글로 끌 수 있고 **기본값은 OFF** 다.

### 이 모듈의 절반은 '덜 울리게 하는' 코드다

알람 시스템은 기능이 부족해서 죽지 않는다. **과해서** 죽는다.
오탐률 37% 기준으로 실측한 소음 예보:

| 등급 설정 | 하루 알람 | 그중 헛알람 |
|---|---|---|
| `confirm` ← **기본값** | 3.1회 | **1.1회** |
| `review` | 7.0회 | **2.6회** |
| `all` | 7.0회 | 2.6회 |

> ⚠️ 위 수치는 **th_review 0.45 / th_confirm 0.80** 으로 측정한 값이다(당시 코드 기본값).
> v24 부터 등급 경계는 코드가 아니라 `watcher_config.json` 이 정하며, 화면 라벨과
> 소음 예보 모두 그 값을 읽는다. 현재 설정은 `⚙ 임계값 튜닝` 탭 또는 사이드바에서
> 확인할 것 — 이 표의 숫자를 현재 값으로 읽으면 안 된다.

새벽에 두 번 깨우고 두 번 다 헛것이면 담당자는 사흘 안에 토글을 끄고 다시는 켜지 않는다.
그래서 UI 는 **토글 옆에 이 예보를 실시간으로 보여준다.** 켤 때 대가를 알아야 계속 켜 둔다.

억제 장치:

| 장치 | 기본값 | 이유 |
|---|---|---|
| 등급 필터 | `confirm` | review 까지 울리면 소음 2배 |
| 워터마크 (`transactions.id`) | 자동 | 최초 실행 시 과거 전체가 울리는 사고 방지 |
| 중복 억제 | 30분 | 같은 거래 재유입 |
| 버스트 상한 | 3건/폴링 | 대량 유입 시 100번 울리지 않게 |
| 조용한 시간대 | 미사용 | 야간 무음 |

### 기술적 함정 3가지

**① 브라우저 오디오 정책** — 최신 브라우저는 사용자가 페이지를 클릭하기 전엔
소리를 차단한다. `AudioContext` 가 `suspended` 로 생성되고 **에러 없이 조용히** 실패한다.

> `dashboard.py:918` 의 기존 `_play_alarm()` 이 이 문제를 안고 있다 —
> 켜도 소리가 안 났다면 그 이유다.

→ "🔔 소리·알림 활성화" 버튼을 한 번 눌러 `ctx.resume()` 을 태워야 한다.
탭을 새로 열 때마다 필요하다.

**② 윈도우 알림이 어느 PC 에 뜨는가**

| 방식 | 뜨는 위치 | 채택 |
|---|---|---|
| 브라우저 `Notification` API | **보는 사람 PC** | ✅ |
| 파이썬 `win10toast` / PowerShell | **서버 PC** | ❌ ngrok 공유 시 아무도 못 봄 |

**③ 팝업이 탭을 뚫고 나와야 한다**

Streamlit 탭 안에 그리면 그 탭이 비활성일 때 같이 숨는다.
`components.html` 의 srcdoc iframe 은 오리진을 상속하므로 `window.parent.document.body`
에 직접 붙일 수 있다 — `dashboard.py:1571` 의 사이드바 수정 JS 가 쓰는,
이 코드베이스에서 이미 검증된 기법이다.

### 클릭 → 이동

Streamlit 은 JS 이벤트를 직접 받지 못한다.
경보 카드가 `?goto=TXN_xxx` 로 쿼리 파라미터를 바꾸면 재실행이 걸리고,
`st.query_params` 로 읽어 트리아지 탭에서 해당 건을 펼친다.
필터에 걸려 안 보이는 건이면 큐에 강제로 끌어올린다 —
클릭했는데 빈 화면이 나오는 것이 최악의 경험이다.

### ♿ 접근성

- 초당 3회를 넘는 점멸은 광과민성 발작을 유발할 수 있다(WCAG 2.3.1).
  번쩍이는 빨간 화면 대신 **레이더 스윕**(회전, 점멸 없음)을 쓰고 펄스 주기를 1.4초로 뒀다.
- `prefers-reduced-motion: reduce` 를 존중해 모든 애니메이션을 끈다.
- 사운드는 삼각파 + 게인 엔벨로프. 사각파는 귀에 꽂히지만 야간 관제실에서 거슬리고,
  엔벨로프가 없으면 시작·끝에 '툭' 하는 클릭 노이즈가 난다.

---

## 5.7 분석 캐시 (`analysis_store.py`)

### 메우려는 구멍

`detect_service.detect()` 는 거래 1건마다 이만큼을 계산한다.

```python
det["proba"]   # 13클래스 확률 분포
det["llm"]     # {"analysis", "slack", "email", "ctx"}  ← LLM 리포트 전문
det["tier"] / ["errors"] / ["elapsed"]
masked         # 마스킹된 원거래 내역
rag_ctx        # RAG 근거 문서
```

그런데 `_save_db()` 가 남기는 것은 **6개 컬럼뿐**이다 —
`fraud_type` · `risk_score` · `is_anomaly` · `model` · `threshold` · `raw_json`.

> **LLM 이 쓴 판정 근거·이상 패턴·오탐 체크·권장 조치는 Slack 을 보내는 순간 사라진다.**
> LLM 을 돌리는 이유 자체가 그 분석인데 DB 에 한 글자도 남지 않는다.

결과적으로 사흘 뒤 담당자는 `위험 0.72, 유형 f` 만 보고 정탐/오탐을 찍어야 한다.
재검증 경로는 마스킹 훼손으로 막혀 있다(5.3절). 따라서
**탐지 시점에 캐시하는 것이 근거를 남기는 유일한 방법이다.**

### 붙이는 법 — 워처에 2줄

```python
# watcher.py — DetectService 생성 직후
from pipeline import analysis_store as astore
astore.attach(svc)
```

또는 진입점 스크립트에서 클래스 레벨로: `astore.install()`

> ⚠️ **이 2줄만은 워처 쪽에 들어가야 한다.** 다른 모든 것은 기존 파일 수정 없이 붙였지만,
> LLM 리포트는 그 순간 **워처 프로세스의 메모리에만** 존재하고 DB 에 애초에 기록되지 않는다.
> 대시보드가 나중에 주워올 방법이 없다. `attach()` 는 인스턴스의 `detect` 를 감싸는
> 래퍼라 `detect_service.py` 나 `watcher.py` 본문은 손대지 않는다.

훅을 붙이기 전 탐지분은 **복원 불가능**하다. 로그 화면이 그 사실을 명시적으로 안내한다
(조용히 빈 화면을 보여주지 않는다).

### 저장 항목

| 컬럼군 | 내용 |
|---|---|
| 판정 | `fraud_type` `risk_score` `tier` `is_anomaly` |
| **당시 환경** | `model` `th_review` `th_confirm` `pii_level` `llm_provider` `llm_model` |
| 페이로드(zlib) | 마스킹된 원거래 · 확률분포 · LLM 4종 · RAG 근거 · 발송내역 · 오류 |
| 메타 | `captured_at`(UTC) `elapsed` `n_errors` `size_raw` `schema_ver` |

**당시 환경을 함께 박는 이유**: 임계값은 `watcher_config.json` 으로 핫 리로드된다.
지금 화면에 보이는 `th_review` 는 이 판정의 기준이 아닐 수 있다.
로그 상세의 ⚙ 탭이 "이 값이 이 판정의 실제 기준이었습니다"를 명시한다.

### 설계 결정

| 결정 | 이유 |
|---|---|
| **추가 전용** | `detections` 의 UPSERT 로 근거가 덮어써지는 사고를 반복하지 않는다 |
| **zlib 압축** | LLM 리포트는 건당 1~4KB. 실측 압축률 **0.567** → 하루 100건이면 연 **53MB** |
| **이상거래만 캐시** | 정상 거래는 LLM 도 안 돌았고 남길 근거도 없다. 용량만 먹는다 |
| **저장 직전 재마스킹** | 심층 방어. `dashboard._save_detection_to_db` 는 원본을 넣으므로 어느 경로로 들어와도 평문이 쌓이지 않게 한다 (DB 파일 바이트 검사로 검증) |
| **실패해도 탐지 계속** | 캐시는 부가 기능이다. 저장 실패로 알림이 막히면 본말전도 |
| **판정된 건은 보존** | `prune()` 이 나이로 지울 때 `alert_review` 에 판정이 달린 거래는 제외한다 — 감사 자료이자 재학습 라벨의 출처다 |

### 로그 화면

표에서 행을 클릭하면 6개 탭이 열린다.

| 탭 | 내용 |
|---|---|
| 📄 당시 데이터 | 마스킹된 원거래 필드. 캐시가 없으면 `detections.raw_json` 폴백(표시) |
| 🧠 LLM 분석 | 판정 근거 전문 + RAG 근거 문서 |
| 📊 확률 분포 | 13클래스 중 상위 8개 가로 막대 |
| 📨 발송 내역 | 등급·채널·중복억제 + **실제로 나간 Slack/Email 본문** |
| ⚙ 당시 환경 | 모델·임계값·마스킹·LLM·처리시간 + 재분석 횟수 |
| 판정 이력 | `alert_review` 전체 이력 + 그 자리에서 판정 찍기 |

`📼` 배지가 캐시 보유 여부를 표시한다.

---

## 6. 실행

```bash
# 워처가 도는 그 PC에서 실행해야 한다 (fds_results.db 가 로컬 파일)
conda activate qaqc_st
streamlit run ops_dashboard.py --server.port 8502
```

메인 대시보드(8501)와 **동시 실행 가능**하다. WAL 모드 + `mode=ro` 라 서로 막지 않는다.

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `FDS_DB_PATH` | `fds_results.db` | 공유 DB |
| `FDS_LOG_PATH` | `watcher.log` | 워처 로그 |
| `FDS_MODEL_DIR` | `models/` | 모델 폴더 |
| `FDS_REVIEWER` | OS 사용자명 | 판정 기록에 남는 이름 |
| `FDS_ALLOW_WATCHER_CONTROL` | (미설정) | 워처 시작·중지 버튼 활성화 |

### 요구사항

- Streamlit **1.33+** (`st.fragment` 자동 갱신) — 미만이면 수동 새로고침으로 폴백
- 첫 실행 시 `alert_review` 테이블이 자동 생성된다 (기존 테이블은 손대지 않음)

---

## 7. 검증

**통합 러너로 한 번에 돌린다** — 개별 파일을 직접 실행하지 말 것.
셀프테스트는 `pipeline` 패키지 안에 있어서 `python selftest_ops.py` 로는
상대 import 가 깨진다. 반드시 모듈 경로(`-m`)로 부른다.

```bash
python -m pipeline.selftest_all           # 12종 전체 (~80초)
python -m pipeline.selftest_all --fast    # UI·원본조회 제외 (~6초)

# 개별 실행이 필요하면
python -m pipeline.selftest_ops           # 조회 계층·시간대
python -m pipeline.selftest_recheck       # 재검증·마스킹
python -m pipeline.selftest_alert         # 경보 폴링·등급·렌더
python -m pipeline.selftest_analysis      # 분석 캐시
```

전체 목록(12종)은 [`selftest_all.py`](selftest_all.py) 의 `SUITES` 에 정의돼 있다 —
`agent · shift · dispatch · detect_io · status · alert · ops · analysis ·
recheck · migrate · preprocessor · ui`.

`selftest_ops` 는 **UTC 행과 KST 행이 섞인 DB** 를 실제로 만들어
시간대 정규화가 동작하는지 검증한다.
`selftest_ui` 는 AppTest 로 `ops_dashboard.py` 와 `dashboard.py` 를 실제로 부팅한다.

UI 검증 결과: **4개국어 × 7테마 = 28조합 전부 예외 0.**

> ⚠️ `selftest_ui` 는 **워처가 살아 있다고 가정**한다. 워처를 꺼 둔 채 돌리면
> 관제 콘솔이 "워처 응답 없음" 경보를 정상적으로 띄우고, 그 때문에
> `[1] 에러 0` 체크가 실패한다 — 코드 회귀가 아니다.

---

## 8. 개발 중 발견한 버그 3건

| # | 위치 | 내용 |
|---|---|---|
| 1 | 신규 코드 (수정 완료) | `strftime('%s', …)` 는 INTEGER 가 아니라 **TEXT** 를 반환. SQLite 타입 서열상 INTEGER < TEXT 라 `strftime(...) > strftime(...) + 60` 은 **항상 참**이었다. UTC 컬럼까지 로컬로 오진. → `CAST(... AS INTEGER)` 로 수정 |
| 2 | 신규 코드 (수정 완료) | `coverage()` 가 **132%** 반환. 분자는 전체 판정 수, 분모는 `is_anomaly=1` 수로 서로 다른 집합을 나누고 있었다 |
| 3 | 기존 코드 (**✅ 해결**) | `transactions.processed_at` 에 UTC 와 LOCAL 혼재 → M001 마이그레이션 + writer 패치로 통일 |
| 6 | 신규 코드 (**✅ 수정**) | `review_store.counts()` 조기 반환이 `total`·`fp_rate` 키를 빠뜨려 **신규 DB 첫 실행 시 대시보드 전체가 KeyError 로 죽었다.** 회귀 테스트가 발견 |
| 4 | 기존 코드 (**미수정**) | `dashboard.py:918` `_play_alarm()` 은 브라우저 오디오 정책 때문에 **실제로 울리지 않는다**. 사용자 제스처 안에서 `ctx.resume()` 이 필요 |
| 5 | 기존 코드 (**미수정**) | `dashboard.py` 가 쓰는 `st.components.v1.html` 은 2026-06-01 지원 종료 예고 — 이미 지났다. `ops_alert._html()` 이 `st.iframe` 우선 폴백 shim 을 갖고 있으니 참고 |

> `watcher_panel.py` 가 버그 #1 을 피한 것은 우연이다 —
> `CAST(strftime(...) - strftime(...) AS INTEGER)` 처럼 **뺄셈**을 써서
> 숫자 강제변환이 일어났기 때문. 비교 연산을 쓰는 순간 터지는 지뢰였다.

---

## 9. 남은 과제

| 우선순위 | 항목 |
|---|---|
| ~~🔴 높음~~ | ~~타임스탬프 UTC 통일~~ → ✅ **완료** (M001 + 코드 패치) |
| ~~🔴 높음~~ | ~~`watcher.py` 캐시 훅~~ → ✅ **완료** |
| 🟡 중간 | `dashboard.py:918` `_play_alarm()` 오디오 정책 대응 (버그 #4) |
| 🟡 중간 | `st.components.v1.html` → `st.iframe` 전환 (버그 #5) |
| 🟡 중간 | `inbox/` 원본 CSV 연결 — 마스킹 훼손 없는 재검증 경로 |
| 🟡 중간 | 판정 권한 분리 (현재는 URL 을 아는 누구나 판정 가능) |
| ⚪ 낮음 | 재학습 파이프라인 자동 연결 (현재는 JSON 수동 내보내기) |
| ⚪ 낮음 | 오탐률 급등 시 Slack 알림 (지표의 지표) |
| ⚪ 낮음 | 경보 사운드 커스텀 (현재는 WebAudio 합성 2음, 파일 의존성 없음) |
