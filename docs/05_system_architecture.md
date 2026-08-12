# 05. 시스템 구조 — 왜 앱이 두 개이고 프로세스가 셋인가

모델을 만든 뒤 **운영에 올리는 구간**의 설계 기록입니다.
기능 목록은 [`06_dashboard_features.md`](06_dashboard_features.md), 실행 방법은 [`08_operations_runbook.md`](08_operations_runbook.md) 를 보세요.

---

## 1. 세 개의 프로세스

```
                        inbox/ 에 거래 파일이 떨어진다
                                   │
                      ┌────────────▼─────────────┐
                      │  watcher.py  (백그라운드)  │  5초마다 폴링
                      │  탐지 → 분석 캐시 → 알림   │
                      └────────────┬─────────────┘
                                   │  기록
                        ┌──────────▼──────────┐
                        │   fds_results.db    │  SQLite (WAL)
                        └──────────┬──────────┘
                                   │  읽기 / 판정 쓰기
                 ┌─────────────────┴─────────────────┐
                 │                                   │
      ┌──────────▼──────────┐            ┌───────────▼───────────┐
      │   dashboard.py      │            │   ops_dashboard.py    │
      │   :8501  QA 대시보드 │            │   :8502  관제 콘솔     │
      │   모델을 검증한다     │            │   거래를 처리한다      │
      └─────────────────────┘            └───────────────────────┘
```

### 두 앱은 목적이 다르다 — 합치면 안 된다

| | `dashboard.py` (QA) | `ops_dashboard.py` (관제) |
|---|---|---|
| 쓰는 사람 | 모델 담당자 · 보고 받는 사람 | 관제 당번 |
| 묻는 질문 | *"이 모델이 쓸 만한가"* | *"이 거래를 어떻게 할 것인가"* |
| 사용 방식 | 열어서 본다 | **켜 둔다 (24시간)** |
| 데이터 기준 | 검증셋 (정적 라벨) | **실제 담당자 판정** |
| 화면 | 5개 세션 | 8개 탭 |
| 이메일 | 리치 HTML + 등급 머리말, **마스킹 강제** | 평문 + **편집 가능한** 미리보기 |
| 발송 기록 | 없음 | `ops_dispatch` **감사 로그** |
| 규모 | 5,843줄 | 3,554줄 |

> ⚠️ **발송 경로가 둘로 갈린 것은 의도된 설계다.**
> 합치려면 *"이메일을 어떤 물건으로 볼 것인가"* 를 먼저 정해야 한다 —
> 리팩터링이 아니라 **제품 결정**이다. → [`OPS_BACKLOG.md`](../OPS_BACKLOG.md) §A2

이 판단은 실제로 리팩터링을 시도하다가 나왔습니다.
v26 에서 "단건/배치/챗 본문 공용화"를 계획했다가, 발송 경로를 실측해 보니
두 앱이 **우연히 갈린 게 아니라 설계상 다르다**는 것을 확인하고 범위에서 제외했습니다.

---

## 2. 관제 콘솔이 왜 따로 생겼나

`dashboard.py` 의 세션5(실시간 탐지)를 분리한 것이 아니라, **없던 것을 만든 것**입니다.

| 기존에 없던 것 | 왜 필요했나 |
|---|---|
| **오탐 피드백 루프** | 기존 DB 에는 담당자가 *"이 알림은 오탐이었다"* 를 남길 곳이 **어디에도 없었다** |
| **실제 판정 기반 임계값 튜닝** | QA 대시보드의 비용곡선은 **검증셋 기준**이라 운영 분포와 다르다 |
| **자동 갱신** | 기존 워처 패널은 🔄 버튼이 전부였다. `st.fragment` 로 부분 리런 |

가장 직접적인 계기는 튜터 피드백이었습니다.

> *"실제 FDS 가 가동되는 환경에서는 특정 거래의 이상 여부를 즉각적으로 판별하기 어렵다.
> 정답을 실시간으로 알 수 없는 운영 상황에서 모델이 어떻게 적용되고 작동할지에 대한
> 구체적인 시나리오 설계 보완 필요."* → [`04_tutor_feedback.md` A-9](04_tutor_feedback.md)

**정답을 모르는 상태에서 운영하려면 사람의 판정을 받아 적을 곳이 있어야 한다** —
그게 관제 콘솔입니다.

### 독립성 검증

`ops_dashboard.py` 는 **`dashboard.py` 를 전혀 참조하지 않습니다** (import 0건).
`dashboard.py` 를 삭제한 폴더에서 실행해도 **예외 0** 으로 정상 동작하는 것을 검증했습니다.

관제 앱만 별도 서버로 떼려면 아래만 복사하면 됩니다.

```
ops_console/
├── ops_dashboard.py
├── i18n_data.py
├── fds_results.db          ← ⚠ 심볼릭 링크 또는 같은 PC 경로
└── pipeline/
    ├── ops_ui.py  ops_alert.py  review_store.py  ops_queries.py  ops_recheck.py
    ├── watcher_panel.py  watcher_control.py  watcher_config.py
    ├── ml_classifier.py  bundle_io.py  pii_masker.py
    └── detect_service.py
```

> ⚠️ **DB 만은 공유해야 한다.** 워처가 쓰고 관제가 읽는 구조라 복사본을 두면
> **영원히 빈 화면**이 된다. `FDS_DB_PATH` 로 원래 경로를 가리키게 하는 것이 가장 안전하다.

---

## 3. 단일 판정 엔진 — 이 설계가 모든 것을 지탱한다

```
              pipeline/detect_service.py   ← 판정 엔진 (Streamlit 무관)
                        │
     ┌──────────┬───────┴────────┬──────────────┐
  대시보드      워처            (n8n용 API)     (MCP 서버)
   [완료]      [완료]            [미착수]        [프로토타입]
```

**판정 로직을 복제하지 않는다.** 그 결과:

| 얻은 것 | 구체적으로 |
|---|---|
| 사고 방지 | *"대시보드는 정상인데 알림은 왔어요"* 가 구조적으로 불가능 |
| 확장성 | 이미 **2개 어댑터가 같은 코어에 붙어 동작 중**. n8n·MCP 는 3·4번째 어댑터일 뿐 |
| 검증 가능 | 두 앱이 같은 입력에 **같은 판정**: `d / 0.8773517059743291` (`selftest_ui` §13 으로 고정) |

> 복붙 구조였다면 어댑터를 늘릴수록 판정이 갈라졌을 것입니다.
> 실제로 **편집기 코드가 두 벌이었을 때 같은 버그가 3번 재발**했습니다
> → [`03b` #B-11](03b_issues_dashboard_pipeline.md#b-11)

---

## 4. 모듈 계층

`pipeline/` 40개 모듈, 약 21,000줄. 계층별로 나뉩니다.

### 탐지 계층 (두 앱 공용)

| 모듈 | 줄 | 역할 |
|---|---|---|
| `detect_service.py` | 794 | **판정 실행 본체** — 단일 진실 원천 |
| `detect_io.py` | 424 | 원장 이원화 · 거래ID 생성 · 계좌이력 |
| `detect_ui.py` | 732 | 위험 게이지 · 확률 막대 · 유형 카드 (공용 렌더) |
| `detect_workbench.py` | 988 | 프롬프트/RAG 편집기 · **위젯 헬퍼** (공용) |
| `preprocessor.py` | 495 | 원본 행 → 58피처 변환 |
| `ml_classifier.py` | 310 | 모델 추론 |
| `model_loader.py` | 563 | 다형식 로더 (`.pkl`/`.onnx`/`.pmml`/`.sql`) |
| `feature_bridge.py` | 523 | 원본→파생 피처 **역학습** 브리지 |
| `bundle_io.py` | — | joblib/pickle 안전 로드 |
| `rule_checker.py` | 569 | 규칙 기반 검증 (설명용) |

### 관제 계층

| 모듈 | 줄 | 역할 |
|---|---|---|
| `ops_ui.py` | 1,925 | 테마 · 다국어 · CSS (이 계층에서 가장 크다) |
| `ops_alert.py` | 919 | 실시간 경보 — 사운드 · 팝업 · 데스크톱 |
| `ops_queries.py` | 782 | **조회·분석 레이어 (읽기 전용, `mode=ro`)** |
| `ops_dispatch.py` | 730 | 발송 + 감사 로그 (2단계 삭제) |
| `ops_agent.py` | 598 | 챗봇 액션 화이트리스트 |
| `ops_sidebar.py` | 507 | 관제 사이드바 |
| `ops_guide.py` | 462 | 온보딩 안내 |
| `ops_shift.py` | 359 | SLA 경과 · 교대 인수인계 |
| `ops_recheck.py` | 353 | 재검증 + **안전 가드** |
| `review_store.py` | 807 | **오탐 판정 저장소** (append-only) |
| `analysis_store.py` | 501 | 탐지 시점 분석 캐시 |
| `audit_store.py` | 269 | 감사 로그 저장소 |
| `status_push.py` | 225 | 상태 외부 내보내기 · 잠금 하트비트 |
| `asset_registry.py` | 191 | 모델·자산 레지스트리 |

### 워처 · 분석 · 데이터

| 모듈 | 역할 |
|---|---|
| `watcher_panel.py` (651) · `watcher_control.py` (362) · `watcher_config.py` | 상태 패널 · 시작/중지 · **임계값 핫 리로드** |
| `llm_analyzer.py` (768) · `batch_analyzer.py` (527) · `chat_agent.py` (523) · `agent_facts.py` (511) | LLM 3단계 분석 · 배치 · 챗봇 |
| `rag_searcher.py` (194) | Chroma 벡터 검색 (`knowledge/` 임베딩) |
| `notifier.py` · `notify_compose.py` · `notify_visuals.py` | Slack/Email 발송 · 리치 컴포저 · 알림 이미지 |
| `pii_masker.py` (302) | **개인정보 마스킹 — 발송 전 필수 통과** |
| `dataset_loader.py` (331) · `data_streamer.py` (261) · `evaluator.py` (466) | 데이터셋 검색·로딩 · 스트리머 · 실시간 평가 |
| `selftest_*.py` × 12 | 자가 검증 |

### 공용 계층이 생긴 이유

> *"같은 코드가 양쪽에 복사돼 한쪽만 썩는 사고를 **3번** 겪고 뽑아냈다."*

| 대상 | Before | After |
|---|---|---|
| 프롬프트 편집기 | 두 벌 (~55줄 × 2) | `dwb.render_prompt_editor()` |
| RAG 편집기 | 두 벌 (~75줄 × 2) | `dwb.render_rag_editor()` |
| `prompt_overrides` | 두 벌 (하드코딩 dict) | `dwb.prompt_overrides()` |
| 탐지 입력 | ops 안에 624줄 | `detect_workbench` 호출부 **33줄** |

**결과: ops −117줄 · dashboard −133줄 · 공용 모듈 +314줄 = 합계 +64줄.**
줄 수를 줄이는 게 목적이 아니었습니다 — **구현이 두 벌에서 한 벌이 된 것**이 결과입니다.

`selftest_ui` §14 가 **정적 검사**로 재발을 막습니다 —
앱 파일에 `_PROMPT_SLOTS`/`rag_reidx_` 가 다시 나타나면 테스트가 실패합니다.

---

## 5. 데이터 흐름

```
inbox/*.csv
    ↓  watcher.py (5초 폴링 · 커서 추적)
DetectService.detect()  ←── watcher_config.json (핫 리로드)
    ↓
    ├─→ transactions    (append-only) ── 알림 원장 ★
    ├─→ detections      (UPSERT)      ── 피처 저장 (마스킹본)
    ├─→ notified                      ── 중복 억제
    ├─→ analysis_cache  (append-only) ── LLM 리포트·확률·환경 스냅샷
    │        ↑ astore.attach(svc) 훅이 여기서 가로챈다
    └─→ Slack / Email

        ↓ ops_queries (읽기 전용 · UTC 정규화)
    ops_dashboard 트리아지 · 로그 탭
        ↓ 담당자 판정
    review_store → alert_review  (append-only · UTC)
        ↓
        ├─→ 오탐률·사유 분석
        ├─→ 임계값 시뮬레이터 → watcher_config.json → 워처 (재시작 불필요)
        └─→ export_training_labels() → 재학습
```

### 원장 선택 — 왜 `transactions` 인가

`detections` 는 `transaction_id` PK + UPSERT 라 재탐지하면 **이전 판정이 소리 없이 덮어써진다.**
감사 대상인 사람의 판정에 그 구조를 쓸 수 없어, `AUTOINCREMENT` + append-only 인
`transactions` 를 알림 원장으로 쓰고 `detections` 는 `raw_json`(피처)을 얻는 보조로만 씁니다.

→ [`03c` #C-3](03c_issues_ops_runtime.md#c-3)

### 시간대 — 모든 조회가 한 관문을 지난다

DB 전수 조사 결과 **테이블마다 시간대가 달랐고, 같은 컬럼에 UTC 와 KST 가 섞여** 있었습니다.
각 테이블을 따로 보는 화면에서는 안 터지지만, 관제 콘솔이 처음으로 하나의 타임라인에 합치면서
**9시간짜리 유령 피크**가 드러났습니다.

- 모든 조회가 `ops_queries` 를 통과하며 UTC 로 정규화 → 화면 표시 직전에만 로컬로
- `migrate_timestamps.py` (M001) 로 기존 데이터 이관 + writer 6곳 패치
- `diagnose_timestamps()` 가 현재 오염 상태를 🩺 진단 탭에 보고

→ [`03c` #C-1](03c_issues_ops_runtime.md#c-1) · [`pipeline/MIGRATION_RUNBOOK.md`](../pipeline/MIGRATION_RUNBOOK.md)

---

## 6. 무인 운영 안전장치

24시간 돌아가는 시스템은 **기능이 부족해서가 아니라 방치돼서** 죽습니다.

| 장치 | 동작 | 왜 |
|---|---|---|
| **5초 폴링** (watchdog 아님) | 커서 추적으로 신규+append 모두 | Windows `ReadDirectoryChangesW` 가 SMB 에서 **이벤트를 조용히 놓친다** |
| **기동 거부** | 모델 로드 실패 시 시작하지 않음 | 더미 모드로 도는 것보다 안 도는 게 낫다 |
| **서킷 브레이커** | LLM 연속 실패 시 5분 우회 | LLM 장애 시 1건당 12초 낭비 → 알림 자체가 막힌다 |
| **중복 억제** | `notified` 테이블 | 같은 거래 재유입 |
| **설정 핫 리로드** | `watcher_config.json` 5초 내 반영 | 무중단 임계값 조정 |
| **데드맨 스위치** | OS 작업 스케줄러가 10분마다 하트비트 확인 | **감시자도 죽을 수 있다.** 스케줄러는 OS 가 관리하므로 우리가 만든 어떤 프로세스보다 안 죽는다 |
| **상태 푸시** | `status_push.py` — 파일/HTTP | Streamlit Cloud 는 워처 상태를 직접 못 본다 |

### 데드맨 스위치의 세심한 부분

| 상황 | 알림 |
|---|---|
| 정상 (10분 내 폴링) | 없음 |
| 10분 이상 무응답 | 🔴 1회 → 이후 60분 쿨다운 |
| 복구됨 | 🟢 1회 후 상태 초기화 |
| **대시보드 버튼으로 중지** (`note=stopped`) | **없음 (의도적 중지)** |
| `--once` 1회 실행 | 없음 |
| 워처를 한 번도 실행 안 함 | 없음 |

> **'의도적 중지'를 구분하는 게 중요하다.** 이게 없으면 워처를 끌 때마다
> "죽었어요!" 알림이 와서 금방 무시하게 된다.

`--restart` 옵션(다운 시 자동 재시작, 1시간 3회 제한)도 있지만
**처음 며칠은 붙이지 말 것**을 권합니다 — 왜 죽는지 먼저 알아야 자동 복구가 맞는 처방인지 판단할 수 있습니다.

---

## 7. 자가 검증 12종

```bash
python -m pipeline.selftest_all           # 12종 전체 (~80초)
python -m pipeline.selftest_all --fast    # UI·원본조회 제외 (~6초)
```

| 스위트 | 검증 대상 |
|---|---|
| `agent` | 챗봇 액션 화이트리스트·파싱 |
| `shift` | SLA 경과·교대 인수인계 |
| `dispatch` | 발송 감사 로그·2단계 삭제 |
| `detect_io` | 원장 이원화·거래ID·계좌이력 |
| `status` | 상태 외부 내보내기·잠금 하트비트 |
| `alert` | 경보 폴링·등급·렌더 |
| `ops` | 조회 계층·**시간대** |
| `analysis` | 분석 캐시 |
| `recheck` | 재검증·마스킹 |
| `migrate` | 시간대 마이그레이션 |
| `preprocessor` | **배치 불변식**·시도 매핑 *(느림)* |
| `ui` | **화면 회귀** — AppTest 로 두 앱을 실제 부팅 *(느림)* |

### 이 테스트들이 특별한 이유

| 테스트 | 무엇을 하나 |
|---|---|
| `selftest_ops` | **UTC 행과 KST 행이 섞인 DB 를 실제로 만들어** 정규화를 검증 |
| `selftest_ui` | AppTest 로 두 앱을 **실제로 부팅**. 4개국어 × 7테마 = **28조합 전부 예외 0** |
| `selftest_preprocessor` | "58피처 전부 99.9% 이상 일치"를 **불변식으로 고정** |
| `selftest_ui` §14 | **정적 검사** — 앱 파일에 특정 심볼이 다시 나타나면 실패 (재발 차단) |

**설계 규칙** (새 테스트를 추가할 때도 지킬 것):
- 임시 DB 를 만들어 쓴다 — 자체 테스트가 운영 DB 를 오염시킨 사고가 **2번** 있었다 ([`03c` #C-22](03c_issues_ops_runtime.md#c-22))
- 값 검사에 **예외 0 단언을 병행**한다 — 값만 보면 예외가 나도 통과한다

> ⚠️ `ui` 스위트는 **워처가 살아 있다고 가정**한다. 워처를 꺼 둔 채 돌리면
> 관제 콘솔이 "워처 응답 없음" 경보를 정상적으로 띄우고, 그 때문에 `[1] 에러 0` 체크가 실패한다
> — **코드 문제가 아니다.**

---

## 8. 팀 규칙 — 사고에서 나온 것들

이 여섯 줄은 전부 실제 사고 뒤에 만들어졌습니다.

| # | 규칙 | 어느 사고에서 |
|---|---|---|
| 1 | **PII** — LLM·알림으로 나가는 데이터는 전부 `pii_masker` 를 통과한다 | [`03b` #B-20](03b_issues_dashboard_pipeline.md#b-20) 인젝션 · 원본 유출 |
| 2 | **시간대** — DB 는 UTC. 표시 시점에만 로컬로 | [`03c` #C-1](03c_issues_ops_runtime.md#c-1) 9시간 유령 피크 |
| 3 | **DB 경로** — 배포 시 `FDS_DB_PATH` 절대경로 고정 | [`03c` #C-22](03c_issues_ops_runtime.md#c-22) 운영 DB 오염 2회 |
| 4 | **원장은 append-only** — 조회는 반드시 `ops_queries` 를 거친다 | [`03c` #C-3](03c_issues_ops_runtime.md#c-3) UPSERT · [C-7](03c_issues_ops_runtime.md#c-7) 위젯 key 충돌 |
| 5 | **직접 위젯을 만들지 말 것** — `detect_workbench` 헬퍼를 쓴다 | [`03b` #B-11](03b_issues_dashboard_pipeline.md#b-11) `value=` 함정 **3회 재발** |
| 6 | **코드를 건드렸으면** `selftest_all` 을 돌린다 | 전반 |

새 과제가 생기면 [`OPS_BACKLOG.md`](../OPS_BACKLOG.md) 맨 위에, 끝나면 [`PATCH_NOTES5.md`](../PATCH_NOTES5.md) 로 옮깁니다.

---

## 9. 배포

### ngrok (현재 운영 방식)

`start_fds_all_ops.bat` 한 번으로 llama.cpp · 워처 · 두 앱 · ngrok 이 순서대로 뜹니다.

> 🔴 **인증이 없다.** ngrok URL 을 아는 사람은 누구나 거래내역을 조회하고
> 이메일·Slack 을 발송할 수 있습니다. 공개 전 `ngrok http --basic-auth …` 또는
> 앱 레벨 로그인을 **반드시** 붙일 것. → [`03c` #C-29](03c_issues_ops_runtime.md#c-29)

ngrok 무료 플랜은 터널이 1개뿐이라 **둘 중 하나만** 외부에 공개됩니다.
공개 대상은 스크립트 상단 `TUNNEL_TARGET` (`ops` | `dashboard`).

### Streamlit Community Cloud

| 항목 | 로컬(ngrok) | Cloud |
|---|---|---|
| 비밀값 | `.env` | App settings > **Secrets** |
| 의존성 | `requirements.txt` | `requirements-cloud.txt` |
| LLM | llama.cpp (`local`) | 클라우드 제공자 — Cloud 에는 llama.cpp 가 없다 |
| RAG · 음성 · ONNX/PMML | 동작 | **꺼짐** (torch 496MB — 자원 한도 초과) |
| DB | 파일 영속 | **휘발** — 재시작 시 탐지 이력 소실 |
| 워처 상태 | 직접 조회 | `status_push.py` 로 외부 푸시 필요 |

`secrets_bridge.py` 가 `st.secrets` 를 `os.environ` 으로 넘겨주므로
**앱 코드는 로컬과 Cloud 에서 동일하게 동작합니다** (`os.getenv` 그대로).

### 왜 NSSM(윈도우 서비스)을 안 쓰나

`nssm.exe` 는 저장소에 있지만 채택하지 않았습니다.
서비스로 등록하면 세션 0 에서 돌아 **GUI 상호작용이 불가능**하고,
llama.cpp · ngrok · Streamlit 의 기동 순서를 보장하기 어렵습니다.
현재는 런처 배치(`start_fds_all_ops.bat`)로 순서를 명시적으로 제어합니다.

→ 배포 방법 7종 비교: [`FDS_배포_7가지_방법_완전가이드.md`](../FDS_배포_7가지_방법_완전가이드.md)
