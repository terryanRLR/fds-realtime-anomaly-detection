# 08. 운영 런북 — 설치 · 실행 · 검증 · 장애 대응

시스템을 **실제로 돌리는 방법**입니다. 구조는 [`05_system_architecture.md`](05_system_architecture.md),
기능은 [`06_dashboard_features.md`](06_dashboard_features.md) 를 보세요.

---

## 1. 설치

### 요구사항

```bash
pip install -r requirements.txt
```

> 🔴 **`streamlit>=1.58` 이 하한입니다.**
> 관제 콘솔이 `st.tabs(key=…, default=…)` 로 탭 상태를 관리하는데 이 인자가 1.58 부터입니다.
> 낮으면 **탭을 만드는 순간 `TypeError` 로 앱이 아예 뜨지 않습니다.**
> 앱이 부팅 단계에서 이 상황을 감지해 안내합니다 ([`03c` #C-24](03c_issues_ops_runtime.md#c-24)).

### 설정

```bash
cp .env.example .env      # 값을 채운다
```

**우선순위**: 실제 환경변수 / `.env` > `st.secrets` > 코드 기본값
(대시보드 사이드바에 직접 입력한 값은 그 세션에서 위 모두를 덮어씁니다)

| 환경변수 | 기본값 | 용도 |
|---|---|---|
| `USE_LLM_PROVIDER` | `local` | `local`(llama.cpp) / `anthropic` / `openai` / `deepseek` / `moonshot` / `custom` / `fallback` |
| `FDS_DB_PATH` | `fds_results.db` | 공유 DB. **실행 디렉터리 기준 상대경로**라 배포 시 절대경로 고정 권장 |
| `FDS_MODEL_DIR` | `models` | 모델·메타 폴더 |
| `FDS_DOCS_DIR` | `knowledge` | RAG 지식베이스 |
| `FDS_CHROMA_DIR` | `chroma_db` | 벡터 DB |
| `FDS_LOG_PATH` | `watcher.log` | 워처 로그 |
| `FDS_INBOX` | `inbox` | 워처 감시 폴더 |
| `FDS_REVIEWER` | OS 사용자명 | 판정 기록에 남는 이름 |
| `FDS_OPS_TAB_LAYOUT` | `ai_first` | 관제 탭 배치 |
| `FDS_ALLOW_WATCHER_CONTROL` | (미설정) | 워처 시작·중지 버튼 활성화 |
| `SLACK_WEBHOOK_URL` / `SMTP_USER` / `SMTP_PASS` | — | 알림. `SMTP_PASS` 는 Gmail **앱 비밀번호**(16자) |

> 🔴 **`.env` 는 `.gitignore` 로 막혀 있습니다. 절대 커밋하지 마세요.**

### 모델 배치

`models/` 에 아래를 둡니다. **메타 4종은 반드시 함께** — 하나라도 없으면 추론이 어긋납니다.

```
models/
├── lgbm_13class(최종).pkl        ★ 58피처 · 13클래스 · macro-F1 0.6138
├── label_encoders.pkl            ★ 메타
├── le_target.pkl                 ★ 메타 (parquet 정수 라벨 디코딩에도 재사용)
├── feature_cols.json             ★ 메타
├── feature_defaults.json         ★ 메타
└── model_meta.json                 요약 정보
```

**탐색 순서**: `FDS_MODEL_DIR` → `CWD/models` → `프로젝트루트/models` → `pipeline/models` → `pipeline/` → 프로젝트 루트 → `CWD`

**배포 전 호환성 검증**

```bash
python -m tools.verify_bundle
python -m tools.verify_bundle --raw data/train.csv --x data/X_tr.parquet   # 변환 규칙 자가검증까지
```

### 데이터셋 ↔ 모델 짝 맞추기

- 파생 parquet 에는 파생 모델을, 원본 CSV 에는 원본 피처 모델을 씁니다.
  어긋나면 **해당 모델만** 사유와 함께 스킵됩니다 (앱은 죽지 않습니다)
- `data/` 의 `X_*`/`y_*` 페어는 자동 결합됩니다.
  `구 X_tr.parquet` 처럼 **접두어가 붙어도** 인식됩니다 — 세대별 데이터셋을 나란히 두고 고를 수 있습니다
- X·y 결합은 **위치 기준**입니다 (인덱스로 결합하면 어긋납니다)
- SQL 모델 규약: `data` 테이블 대상 · `proba_<클래스>` 컬럼 · `ORDER BY` 금지

---

## 2. 실행

### 개별 실행 (포트 고정)

```bash
run_dashboard.bat        # :8501  QA 대시보드
run_ops_dashboard.bat    # :8502  관제 콘솔
run_watcher.bat          #        워처
```

또는 직접:

```bash
conda activate qaqc_st
streamlit run dashboard.py     --server.port 8501
streamlit run ops_dashboard.py --server.port 8502
python watcher.py --inbox inbox
```

> 관제 콘솔은 **워처가 도는 그 PC** 에서 실행해야 합니다 (`fds_results.db` 가 로컬 파일).
> 두 앱은 **동시 실행 가능**합니다 — WAL 모드 + `mode=ro` 라 서로 막지 않습니다.

### 전체 스택

```bash
start_fds_all_ops.bat    # llama.cpp + 워처 + 두 앱 + ngrok(관제 :8502 공개)
start_fds_all.bat        # 위와 같되 ngrok 이 QA 대시보드(:8501) 공개
stop_fds_team.bat        # 정지
```

경로·포트는 [`fds_config.bat`](../fds_config.bat) 에서 읽고,
헬퍼 스크립트(`_run_*.cmd`)는 실행 시점에 생성됩니다 — **산출물이라 지워도 됩니다.**

> ngrok 무료 플랜은 터널이 1개뿐이라 **둘 중 하나만** 외부에 공개됩니다.
> 나머지는 같은 LAN 에서 `http://<내부IP>:<포트>` 로 접속합니다.
> 공개 대상은 스크립트 상단 `TUNNEL_TARGET` (`ops` | `dashboard`).

### 🔴 공개 전 반드시

```bash
ngrok http --basic-auth "user:password" 8502
```

**인증이 없으면 URL 을 아는 누구나 거래내역을 조회하고 이메일·Slack 을 발송할 수 있습니다.**
→ [`03c` #C-29](03c_issues_ops_runtime.md#c-29)

---

## 3. 매일 쓰는 법

### 관제 당번

1. `ops_dashboard.py` (:8502) 를 켜 둔다
2. 🚨 **알림 트리아지** — 큐에 쌓인 건을 정탐/오탐/미탐/보류로 판정
   - 오탐이면 **사유 코드**를 반드시 고른다 (사유 없는 오탐률은 행동으로 이어지지 않는다)
   - 근거가 필요하면 🗃 탐지 로그에서 해당 건의 **당시 LLM 분석**을 본다
3. 🔄 **교대 인수인계** — 교대 시 인수인계서 자동 생성 + 메모 전달
4. 판정이 쌓이면 ⚙ **임계값 튜닝** 에서 실제 판정 기반 what-if 를 본다

### 모델 담당자

1. `dashboard.py` (:8501) 에서 데이터셋 × 모델 조합으로 재평가
2. 📉 **오탐 분석** 에서 재학습 라벨 내보내기 (`export_training_labels`)
3. 새 모델을 `models/` 에 두고 `python -m tools.verify_bundle` 로 검증

### 워처 감시 폴더에 파일 넣기

```bash
cp 거래파일.csv inbox/
# 또는 대시보드 세션5 → 📤 inbox 전송
```

5초 내에 워처가 집어서 탐지 → 등급 판정 → 알림까지 갑니다.

> ⚠️ 런처는 `--inbox inbox` 를 **명시적으로** 넘깁니다 — 인자가 환경변수를 이깁니다.
> `FDS_INBOX` 로 폴더를 옮기려면 런처의 그 인자도 함께 지워야 합니다
> ([`03c` #C-16](03c_issues_ops_runtime.md#c-16)).

---

## 4. 임계값 조정

**우선순위: CLI 명시 > `watcher_config.json` > `.env` > 기본값**

| 방법 | 절차 |
|---|---|
| **A** | 대시보드 세션5 → 워처 상태 → ⚙️ 설정 → 슬라이더 → 저장 (**5초 내 반영**) |
| **B** | `watcher_config.json` 직접 수정 (**재시작 불필요**) |
| **C** | 관제 콘솔 ⚙ 임계값 튜닝 → 확인 카드 → 적용 |

> ⚠️ **슬라이더가 아니라 `정확한 값` 숫자 칸이 실제 적용값입니다.**
> 슬라이더 `step=0.01` 로는 운영값 `0.005` 를 만들 수 없습니다
> ([`03c` #C-11](03c_issues_ops_runtime.md#c-11)).

**재측정**

```bash
python -m tools.threshold_report --daily 300 --fn-cost 1700 --fp-cost 5 --min-macro-f1 0.6
```

근거 상세: [`07_model_and_thresholds.md`](07_model_and_thresholds.md)

---

## 5. 자가 검증

```bash
python -m pipeline.selftest_all           # 12종 전체 (~80초)
python -m pipeline.selftest_all --fast    # UI·원본조회 제외 (~6초)

# 개별 실행은 모듈 경로(-m)로
python -m pipeline.selftest_ops           # 조회 계층·시간대
python -m pipeline.selftest_recheck       # 재검증·마스킹
python -m pipeline.selftest_alert         # 경보 폴링·등급·렌더
python -m pipeline.selftest_analysis      # 분석 캐시
```

> **개별 파일을 직접 실행하지 마세요.** 셀프테스트는 `pipeline` 패키지 안에 있어서
> `python selftest_ops.py` 로는 상대 import 가 깨집니다. 반드시 `-m` 으로 부릅니다.

**코드를 건드렸으면 반드시 돌립니다.**

> ⚠️ `ui` 스위트는 **워처가 살아 있다고 가정**합니다.
> 워처를 꺼 둔 채 돌리면 관제 콘솔이 "워처 응답 없음" 경보를 정상적으로 띄우고,
> 그 때문에 `[1] 에러 0` 체크가 실패합니다 — **코드 회귀가 아닙니다.**

---

## 6. 데드맨 스위치 (워처 사망 감지)

작업 스케줄러가 10분마다 `tools/check_watcher.py` 로 하트비트를 확인합니다.

> **별도 상주 데몬을 만들지 않은 이유: 감시자도 죽을 수 있다.**
> 작업 스케줄러는 OS 가 관리하므로 우리가 만든 어떤 프로세스보다 안 죽는다.

### 설치

```cmd
REM ① 발송 테스트 (일부러 다운 판정 → Slack 오는지 확인)
python -m tools.check_watcher --stale-minutes 0 -v

REM ② 정상 판정 확인 + 상태 초기화
python -m tools.check_watcher -v

REM ③ 스케줄러 등록 (관리자 권한)
install_deadman.bat

REM ④ 즉시 1회 실행
schtasks /Run /TN "FDS Watcher Deadman"
type logs\deadman.log
```

### 동작 규칙

| 상황 | 알림 |
|---|---|
| 정상 (10분 내 폴링) | 없음 |
| 10분 이상 무응답 | 🔴 1회 → 이후 **60분 쿨다운** |
| 복구됨 | 🟢 1회 후 상태 초기화 |
| **대시보드 버튼으로 중지** (`note=stopped`) | **없음 (의도적 중지)** |
| `--once` 1회 실행 | 없음 |
| 워처를 한 번도 실행 안 함 | 없음 |

> **'의도적 중지'를 구분하는 게 중요합니다.** 이게 없으면 워처를 끌 때마다
> "죽었어요!" 알림이 와서 금방 무시하게 됩니다.

### 옵션

`check_watcher.bat` 안의 한 줄만 고칩니다.

```bat
python -m tools.check_watcher --stale-minutes 10 --cooldown-minutes 60 %*
```

`--restart` 를 붙이면 다운 시 자동 재시작합니다 (1시간 3회 제한).

> **처음 며칠은 붙이지 마세요.** 왜 죽는지 먼저 알아야 자동 복구가 맞는 처방인지 판단할 수 있습니다.

**제거**: `schtasks /Delete /TN "FDS Watcher Deadman" /F`

---

## 7. DB 마이그레이션

구버전 DB 는 시간대가 섞여 있습니다 ([`03c` #C-1](03c_issues_ops_runtime.md#c-1)).

```bash
python migrate_timestamps.py fds_results.db            # 미리보기 (dry-run)
python migrate_timestamps.py fds_results.db --apply    # 실제 적용
```

절차 상세: [`pipeline/MIGRATION_RUNBOOK.md`](../pipeline/MIGRATION_RUNBOOK.md)

**진단** — 관제 콘솔 🩺 진단 탭의 `diagnose_timestamps()` 가 현재 오염 상태를 보고합니다.

---

## 8. RAG 지식베이스 관리

```bash
# knowledge/ 에 .md 를 두면 자동 임베딩 (mtime 해시로 변경 감지)
python -m tools.build_rag_docs                    # 유형별 문서 자동 생성
python -m tools.build_rag_docs --force            # 기존 파일 덮어쓰기

# 인덱스를 완전히 다시 만들려면
rm -rf chroma_db/          # 다음 실행 시 재임베딩
```

> ⚠️ **`knowledge/` 에는 LLM 이 인용할 것만 두세요.**
> 이 폴더의 모든 최상위 `.md` 가 벡터 DB 에 들어갑니다.
> 프로젝트 문서는 `docs/` 에 둡니다 ([`03b` #B-24](03b_issues_dashboard_pipeline.md#b-24)).

---

## 9. 트러블슈팅 빠른 참조

### 모델 · 예측

| 증상 | 원인 후보 | 확인 |
|---|---|---|
| 세션5 예측이 **매번 랜덤** | 번들이 **더미 모드** | 로그에 `→ 더미 모드` 가 있는지. `pipeline/bundle_io.py` 배치 확인 |
| Channel/OS 를 바꿔도 결과 동일 | 수치형 인코더 미감지 | 로그에 `수치형 인코더 45개 감지` 가 있는지 |
| 세션2 F1 이 **0 또는 비정상** | 라벨 디코딩 실패 | `models/le_target.pkl` 존재 + `dataset_loader.py` 갱신본인지 |
| macro F1 이 0.6070 | NaN 이 채워짐 | `make_batch_preprocess(clf)` 에 `keep_nan=False` 가 없는지 |
| `invalid load key '\x05'` | **형식 문제** (버전 아님) | joblib 저장본. `bundle_io.safe_load` 사용 |
| `ModuleNotFoundError` / `AttributeError` | **버전 불일치** | `requirements.txt` 기준으로 맞출 것 |
| 모델 목록에 번들이 안 뜸 | 파일명 탐색 실패 | `python -c "from pipeline.bundle_io import resolve_model_path; print(resolve_model_path('models'))"` |
| `🔍 Le Target` 이 모델 목록에 | `is_non_model_pkl` 미적용 | `dashboard.py` + `bundle_io.py` 배치 확인 |
| `No module named 'lightgbm'` | 환경 미설치 | `conda activate qaqc_st` 후 `pip install -r requirements.txt` |

### 화면 · 캐시

| 증상 | 원인 후보 | 확인 |
|---|---|---|
| 파일 교체했는데 화면 그대로 | 캐시 키 밑줄 | `dashboard.py` 갱신본인지 + 완전 재시작 |
| 앱이 아예 안 뜨고 스택 트레이스 | streamlit < 1.58 | `pip install -U streamlit` |
| 음성 패널이 안 보임 | streamlit < 1.42 | 동일 |
| 탭이 8개가 아님 | `ops_shift`/`ops_guide` 미탑재 | 🩺 진단 → 모듈 버전 확인 |
| 온보딩이 안 뜸 | 이미 봤다 | 사이드바 `🎓 사용 안내` 또는 `.ops_onboarded` 삭제 |
| 사이드바 챗봇이 안 보임 | 토글 꺼짐 | `🤖 AI 어시스턴트` (기본 접힘) |

### 워처 · 알림

| 증상 | 원인 후보 | 확인 |
|---|---|---|
| `--once` 인데 `0행 처리` | 커서가 이미 그 파일을 소비 | `watch_cursor` 확인 또는 새 파일명으로 |
| **알림이 두 번 온다** | 워처 + 대시보드 중복 | 한쪽만 자동 발송 켤 것 |
| 기동이 20초, HuggingFace 요청 25번 | RAG 임베딩 모델 최초 다운로드 | 정상. 2회차부터 빨라짐 |
| Slack 에 AI 분석 없이 "기본 양식" | LLM 연결 실패 → 폴백 | `USE_LLM_PROVIDER` · llama.cpp 기동 확인 |
| 📤 inbox 전송이 반영 안 됨 | 런처 `--inbox` 인자가 환경변수를 이김 | 전송 후 표시되는 **절대 경로** 확인 |
| 소리가 안 남 | 브라우저 오디오 정책 | 페이지 아무 곳이나 한 번 클릭 (자동 무장) |
| 윈도우 알림이 안 옴 | 브라우저 권한 미허용 | 브라우저 알림 권한 확인 |

### 관제 · 판정

| 증상 | 조치 |
|---|---|
| `🔒 다른이름 님이 검토 중` | 먼저 확인하고 넘어가거나 `🔓 잠금 무시하고 내가 검토`. **15분 후 자동 해제** |
| 잠금이 안 걸림 | 사이드바 `🔒 동시 판정 잠금` 이 꺼져 있거나, 검토자 이름이 서로 같다 |
| 메모가 자꾸 날아감 | `💾` 배지가 안 보이면 **검토자 이름이 매번 바뀌는지** 확인 |
| SLA 초과가 전부 🔴 | 오래된 미판정이 쌓인 것. 사이드바 SLA(분)로 기준 조정 |
| 교대 요약의 유입 ≠ 판정 | **정상.** 유입은 `ops_queries`, 판정은 `review_store` 로 출처가 다르다 |
| 캐시 훅 안내가 **파란색 info** | 정상 연결됨. 캐시할 이상거래가 아직 없다는 뜻 |
| 캐시 훅 안내가 **노란색 warning** | 진짜 훅 부재. `watcher.py` 의 `DetectService` 생성 직후 2줄 추가 |
| 화면이 통째로 비어 보임 | `FDS_DB_PATH` 미설정 → 다른 위치에서 실행해 **빈 DB 가 새로 생김** |
| `table transactions has no column named input_mode` | 구버전 DB | 마이그레이션 실행 |

### RAG

| 증상 | 조치 |
|---|---|
| RAG 문서 수정이 반영 안 됨 | 🔄 강제 재색인 버튼. 로그에 `knowledge/ 변경 감지 → 인덱스 재구축` |
| 배치 실행 시 `'곗퀜'은(는) 내부 또는 외부 명령...` | 배치 파일 인코딩 (CP949). `chcp 65001` 또는 파일 재저장 |

---

## 10. 명령어 치트시트

```bash
# 실행
run_dashboard.bat / run_ops_dashboard.bat / run_watcher.bat
start_fds_all_ops.bat                          # 전체 스택
stop_fds_team.bat                              # 정지

# 검증
python -m pipeline.selftest_all                # 12종 (~80초)
python -m pipeline.selftest_all --fast         # 6종 (~6초)
python -m tools.verify_bundle                  # 번들 × 데이터셋 호환
python -m tools.verify_bundle --raw data/train.csv --x data/X_tr.parquet

# 도구
python -m tools.threshold_report --daily 300 --fn-cost 1700 --fp-cost 5 --min-macro-f1 0.6
python -m tools.build_rag_docs                 # knowledge/ 문서 생성
python -m tools.check_watcher -v               # 워처 생존 점검
python -m tools.backfill_ops_ledger --days 7 --apply
python -m pipeline.feature_bridge data/train.csv data/X_tr.parquet
python -m pipeline.preprocessor data/train.csv data/X_tr.parquet

# 마이그레이션
python migrate_timestamps.py fds_results.db            # dry-run
python migrate_timestamps.py fds_results.db --apply

# 워처 단독
python watcher.py --inbox inbox                        # 상시
python watcher.py --inbox inbox --once                 # 1회
python watcher.py --inbox inbox --dry-run              # 발송 없이

# 데드맨
install_deadman.bat
schtasks /Run /TN "FDS Watcher Deadman"
schtasks /Delete /TN "FDS Watcher Deadman" /F
```

---

## 11. 관련 문서

| 알고 싶은 것 | 문서 |
|---|---|
| 관제 콘솔 화면 사용법 | [`ops_dashboard_사용설명서.md`](../ops_dashboard_사용설명서.md) |
| 워처 운영·장애 대응 상세 | [`README_WATCHER.md`](../README_WATCHER.md) |
| 모듈 구조·설계 결정 | [`pipeline/ARCHITECTURE.md`](../pipeline/ARCHITECTURE.md) |
| 데이터 흐름 다이어그램 | [`PIPELINE_DIAGRAM.md`](../PIPELINE_DIAGRAM.md) |
| 배포 방법 7종 비교 | [`FDS_배포_7가지_방법_완전가이드.md`](../FDS_배포_7가지_방법_완전가이드.md) |
| DB 스키마 이관 절차 | [`pipeline/MIGRATION_RUNBOOK.md`](../pipeline/MIGRATION_RUNBOOK.md) |
| 변경 이력 (v10~v39) | [`PATCH_NOTES5.md`](../PATCH_NOTES5.md) |
| 미해결 과제 | [`OPS_BACKLOG.md`](../OPS_BACKLOG.md) |
| 팀 세팅 가이드 | [`기타 문서/FDS_팀공유_세팅가이드.md`](../기타%20문서/FDS_팀공유_세팅가이드.md) |
