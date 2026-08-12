# FDS 대시보드 배포 가이드 — 7가지 방법 완전 정복

> 대상: FDS QA 대시보드 + 관제 콘솔 (Streamlit + LightGBM + llama.cpp)
> 작성 2026-07-20 · **개정 2026-08-10** (앱 2개 체제 · ngrok 실운영 · Cloud 실측 반영)
> 전제: Windows 환경, Anaconda 사용, llama.cpp 로컬 운영

> **읽기 전에 — 이 시스템은 앱이 두 개다**
>
> | 앱 | 포트 | 용도 |
> |---|---|---|
> | `dashboard.py` | 8501 | QA 대시보드 — 모델을 검증한다 |
> | `ops_dashboard.py` | 8502 | 관제 콘솔 — 거래를 처리한다 |
>
> 여기에 백그라운드 워처(`watcher.py`)와 llama.cpp 서버가 더 붙는다.
> 아래 방법들은 **하나의 앱을 공개하는 법**을 설명한다 — 둘 다 공개하려면
> 터널을 2개 쓰거나(유료), Cloud 에 앱을 2개 만든다.
> 전체 구조는 [README.md](README.md) 참조.
>
> 🔴 **어느 방법을 쓰든 두 앱에는 인증이 없다.** 관제 콘솔은 거래내역 조회와
> 이메일·Slack 실발송이 가능하므로, 외부 공개 전 인증을 반드시 붙일 것.


---

## 목차

- 방법 1. 로컬 네트워크 공유 (같은 사무실/VPN)
- 방법 2. ngrok 터널링 (외부 접속, 현재 운영 중)
- 방법 3. Cloudflare Tunnel (ngrok 대안, 고정 도메인 무료)
- 방법 4. Streamlit Community Cloud
- 방법 5. HuggingFace Spaces
- 방법 6. Docker + 클라우드 VM
- 방법 7. FastAPI + 프론트엔드 전환
- 부록 A. 정적 HTML 보고서 내보내기
- 부록 B. 방법별 비교 요약표
- 부록 C. llama.cpp 아키텍처 의사결정 흐름도


---

## 방법 1. 로컬 네트워크 공유

> 난이도: ★☆☆☆☆ | 비용: 무료 | 소요 시간: 5분
> 적합한 상황: 같은 사무실/VPN에 있는 팀원과 공유

### 개요

오빠 PC에서 Streamlit을 띄우되, `--server.address 0.0.0.0` 옵션으로 외부 접속을 허용하면 같은 네트워크의 팀원이 `http://오빠IP:8501`로 바로 접속할 수 있다. 별도 도구 설치나 계정 생성이 전혀 없다.

### 사전 조건

- 오빠 PC와 팀원 PC가 같은 네트워크(사무실 LAN, VPN, 또는 같은 Wi-Fi)
- Windows 방화벽에서 8501 포트 인바운드 허용

### 단계별 가이드

**1단계: 오빠 PC의 내부 IP 확인**

```cmd
ipconfig
```

"이더넷 어댑터" 또는 "Wi-Fi" 항목에서 `IPv4 주소`를 찾는다 (예: `192.168.0.4`).

**2단계: Windows 방화벽 포트 열기**

```powershell
# PowerShell(관리자)에서 실행
New-NetFirewallRule -DisplayName "Streamlit FDS" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow
```

또는 수동으로: 제어판 → Windows Defender 방화벽 → 고급 설정 → 인바운드 규칙 → 새 규칙 → 포트 → TCP 8501 → 허용.

**3단계: llama.cpp 서버 실행**

```cmd
cd C:\Users\terry\llama-cpp-turboquant
.\llama-server.exe --model models\gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf ^
  -fa on --cont-batching --no-kv-unified -ctk turbo3 -ctv turbo3 ^
  -to 1800 -fit on --swa-full --ctx-checkpoints 1 ^
  -np 3 --host 127.0.0.1 --port 8080 -c 16384 ^
  --temperature 0.55 --repeat-penalty 1.12 --top-p 0.9 --top-k 40 --jinja
```

`--host 127.0.0.1`은 유지한다. llama.cpp는 외부에 노출할 필요 없이 대시보드가 localhost로 호출한다.

**4단계: Streamlit 실행 (0.0.0.0 바인딩)**

```cmd
call conda activate qaqc_st
cd /d %USERPROFILE%\바탕 화면\QAQC_streamlit
streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

기동 완료되면 `Network URL: http://192.168.0.4:8501`이 표시된다.

> ⚠️ **런처의 기본값은 이제 `0.0.0.0`이 아니라 `127.0.0.1`입니다.**
> 대시보드에는 인증이 없어서([`docs/03c` #C-29](docs/03c_issues_ops_runtime.md)) 기본값으로 LAN에
> 열어두면 같은 네트워크의 누구나 조회·발송을 할 수 있습니다. 그래서 `run_dashboard.bat`·
> `run_ops_dashboard.bat`은 `127.0.0.1`로 고정되어 있고, 팀 런처(`start_fds_all.bat` 등)는
> `fds_config.bat`의 `BIND_ADDR` 값을 씁니다.
>
> **이 방법(LAN 공유)을 쓰려면** `fds_config.bat`에서 한 줄만 바꾸세요.
>
> ```bat
> set BIND_ADDR=0.0.0.0
> ```
>
> 공유가 끝나면 `127.0.0.1`로 되돌리는 것을 권합니다.
> **ngrok 방식(방법 2)에는 이 변경이 필요하지 않습니다** — ngrok은 `127.0.0.1:포트`로 붙기 때문에
> 루프백 바인딩만으로 충분합니다.

**5단계: 팀원에게 접속 URL 전달**

```
http://192.168.0.4:8501
```

(IP는 1단계에서 확인한 값으로 교체)

### 주의사항

- PC가 꺼지거나 네트워크가 바뀌면 접속 불가.
- 회사 네트워크에 따라 장비 간 직접 통신이 차단된 경우가 있음 (AP 격리 등). 이 경우 방법 2(ngrok)로 전환.
- llama.cpp는 localhost에만 바인딩돼 있어 외부에서 직접 호출 불가 (안전).

### 종료 방법

각 터미널에서 `Ctrl+C`를 누르면 된다. 방화벽 규칙은 한 번 만들면 유지되므로 다음번엔 3~4단계만 반복.


---

## 방법 2. ngrok 터널링 (현재 운영 중)

> 난이도: ★★☆☆☆ | 비용: 무료(기본) / 월 $8(고정 도메인) | 소요 시간: 10분
> 적합한 상황: 네트워크가 다른 팀원에게 공유, 빠른 데모

### 개요

내 PC에서 모든 서비스를 돌리면서, ngrok이 Streamlit 포트를 인터넷에 노출하는 HTTPS URL을 생성한다. 팀원은 어디서든 그 URL로 접속하고, llama.cpp는 localhost에 숨겨진 채 대시보드를 통해서만 호출된다.

> 🔴 **먼저 알아야 할 것 — 두 앱 중 하나만 공개된다**
>
> 이 시스템은 앱이 두 개다: `dashboard.py`(:8501, QA)와 `ops_dashboard.py`(:8502, 관제).
> **ngrok 무료 플랜은 동시 터널이 1개**라 둘 중 하나만 외부에 나가고,
> 나머지는 같은 LAN 에서만 접속된다(방법 1).
> 공개 대상은 실행 스크립트 상단 `TUNNEL_TARGET` 으로 고른다 (`ops` | `dashboard`).

> 🔴 **인증이 없다**
>
> 두 앱 어디에도 로그인이 없다. 관제 콘솔에는 거래내역 조회와
> **이메일·Slack 실발송** 기능이 있으므로, URL 을 아는 사람은 누구나 쓸 수 있다.
> 공개 전 아래 중 하나를 반드시 붙일 것:
> - `ngrok http --basic-auth "user:password" 127.0.0.1:8502` (Personal 플랜 이상)
> - 또는 앱 레벨 로그인 추가
> - 또는 방법 3(Cloudflare Tunnel) + Cloudflare Access

### 사전 조건

- ngrok 계정 (https://ngrok.com 무료 가입)
- ngrok 설치 + authtoken 등록 완료

### 단계별 가이드

**1단계: ngrok 설치 (최초 1회)**

https://ngrok.com/download 에서 Windows용 다운로드 후 PATH가 잡힌 폴더에 압축 해제.

```cmd
ngrok config add-authtoken 여기에_본인_토큰_붙여넣기
```

토큰은 https://dashboard.ngrok.com/get-started/your-authtoken 에서 복사.

**2단계: 고정 도메인 설정 (권장, 무료)**

ngrok 무료 플랜에서도 1개의 고정 도메인을 제공한다 (2024년 이후 정책).

https://dashboard.ngrok.com/domains 에서 "New Domain" 클릭 → 자동 생성된 도메인 확인 (예: `chasing-spoilage-champion.ngrok-free.dev`).

고정 도메인이 있으면 재시작해도 URL이 바뀌지 않아서 팀원에게 매번 새 URL을 공유할 필요가 없다.

**3단계: 원클릭 실행**

공개할 대상에 따라 배치 파일을 고른다:

| 실행 파일 | ngrok 이 공개하는 것 | LAN 전용으로 남는 것 |
|---|---|---|
| `start_fds_all_ops.bat` | **관제 콘솔** `ops_dashboard.py` (:8502) | QA 대시보드 (:8501) |
| `start_fds_all.bat` | **QA 대시보드** `dashboard.py` (:8501) | 관제 콘솔 (:8502) |

더블클릭하면 순서대로 기동된다 — 각 단계마다 health check 를 하고 실패하면 이유를 찍는다.

```
[0/8] 남은 ngrok 세션 정리      [4/8] 워처 (stale lock 자동 정리)
[1/8] 경로·프로그램 사전 점검     [5/8] dashboard.py (:8501)
[2/8] 헬퍼 스크립트 생성         [6/8] ops_dashboard.py (:8502)
[3/8] llama.cpp + /health 대기   [7/8] LAN IP 확인
                               [8/8] ngrok 터널 + URL 출력
```

경로·포트는 `fds_config.bat` 에서 읽는다. `_run_*.cmd` 는 2단계에서 생성되는
산출물이라 지워도 다음 실행 때 다시 만들어진다.

또는 수동으로 터미널 4개:

```
[터미널 1] llama-server.exe (방법 1의 3단계와 동일)
[터미널 2] streamlit run dashboard.py     --server.address 0.0.0.0 --server.port 8501
[터미널 3] streamlit run ops_dashboard.py --server.address 0.0.0.0 --server.port 8502
[터미널 4] ngrok http --url=chasing-spoilage-champion.ngrok-free.dev 127.0.0.1:8502
```

고정 도메인을 쓸 때는 `--url=도메인` 옵션을 추가한다. 고정 도메인이 없으면 `ngrok http 127.0.0.1:8502`만 입력하면 임시 URL이 생성된다.

**4단계: 터널 검증**

메인 창 또는 ngrok 창에서 Forwarding 줄을 확인한다:

```
Forwarding  https://xxx.ngrok-free.dev -> http://127.0.0.1:8502
```

화살표 오른쪽이 **공개하려던 그 포트**여야 한다.

| 화살표 오른쪽 | 의미 |
|---|---|
| `:8502` | 관제 콘솔 — `start_fds_all_ops.bat` 의 정상 결과 |
| `:8501` | QA 대시보드 — `start_fds_all.bat` 의 정상 결과 |
| `:8080` | 🔴 **llama.cpp 가 노출됨**. 즉시 종료하고 다시 시작 |

배치 파일은 이 검증을 자동으로 하고 `CHECK: the target above MUST end with :<포트>` 를 찍는다.
화면 우상단 배지(`🔌 앱이름 · :포트`)로도 어느 앱에 접속했는지 확인할 수 있다 —
두 탭에서 같은 배지가 보이면 포트 충돌이다.

**5단계: 팀원 안내**

팀원에게 전달할 내용:
- URL: `https://chasing-spoilage-champion.ngrok-free.dev`
- 첫 방문 시 ngrok 경고 페이지에서 "Visit Site" 클릭
- 이전에 접속한 적 있으면 시크릿 창(Ctrl+Shift+N) 또는 강력 새로고침(Ctrl+Shift+R)

### 문제 해결

| 증상 | 해결 |
|------|------|
| ERR_NGROK_108 | 이전 ngrok 세션이 남아있음. `taskkill /f /im ngrok.exe` 후 재실행 |
| "Hello there" 채팅 UI가 보임 | 8080(llama.cpp)이 터널링됨. ngrok 종료 후 8501로 재시작 |
| 팀원이 접속 안 됨 (Connections: 0) | 팀원 브라우저 캐시 문제. 시크릿 창으로 접속 시도 |
| 502 Bad Gateway | Streamlit이 안 떠있음. Streamlit 창 확인 |

### 비용

- 무료 플랜: 동시 1세션, 고정 도메인 1개, 월 접속 횟수 제한 있음
- Personal ($8/월): 고정 도메인 3개, basic auth 지원, 월 접속 제한 완화


---

## 방법 3. Cloudflare Tunnel (ngrok 대안)

> 난이도: ★★☆☆☆ | 비용: 완전 무료 | 소요 시간: 20분
> 적합한 상황: ngrok 무료 제한이 불편할 때, 고정 도메인을 무료로 쓰고 싶을 때

### 개요

Cloudflare의 `cloudflared` 도구가 ngrok과 동일한 역할을 한다. 차이점은 완전 무료이면서 접속 횟수 제한이 없고, 고정 도메인도 무료라는 것. 다만 Cloudflare 계정이 필요하고 초기 설정이 ngrok보다 약간 더 걸린다.

### 사전 조건

- Cloudflare 계정 (https://dash.cloudflare.com 무료 가입)
- cloudflared 설치

### 단계별 가이드

**1단계: cloudflared 설치**

```cmd
:: winget으로 설치 (Windows 10/11)
winget install --id Cloudflare.cloudflared

:: 또는 직접 다운로드
:: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
```

설치 확인:

```cmd
cloudflared --version
```

**2단계: 빠른 터널 (임시 URL, 계정 불필요)**

가장 빠른 방법은 "Quick Tunnel"이다. 계정 연결 없이 임시 URL을 즉시 생성한다:

```cmd
cloudflared tunnel --url http://localhost:8501
```

출력에서 `https://xxxxx.trycloudflare.com` URL이 뜨면 그걸 팀원에게 공유한다. ngrok처럼 경고 페이지가 없어서 바로 대시보드가 열린다.

단, 재시작마다 URL이 바뀐다 (ngrok 무료와 동일한 제약).

**3단계: 고정 도메인 터널 (Named Tunnel)**

고정 URL이 필요하면 계정을 연결한다:

```cmd
:: Cloudflare 계정 로그인 (브라우저 팝업)
cloudflared tunnel login

:: 터널 생성
cloudflared tunnel create fds-dashboard

:: 설정 파일 작성
```

`%USERPROFILE%\.cloudflared\config.yml` 파일을 만든다:

```yaml
tunnel: fds-dashboard
credentials-file: C:\Users\terry\.cloudflared\터널ID.json

ingress:
  - hostname: fds.내도메인.com
    service: http://localhost:8501
  - service: http_status:404
```

Cloudflare DNS에서 해당 hostname에 CNAME 레코드를 추가한다:

```
fds.내도메인.com  →  터널ID.cfargotunnel.com
```

그 뒤 터널을 실행한다:

```cmd
cloudflared tunnel run fds-dashboard
```

이제 `https://fds.내도메인.com`이 항상 같은 주소로 대시보드에 연결된다.

**4단계: bat 스크립트 통합**

`start_fds_all_ops.bat`(또는 `start_fds_all.bat`)에서 ngrok 대신 cloudflared를 쓰려면,
`[8/8] Starting ngrok tunnel` 블록의 아래 줄을

```cmd
start "ngrok tunnel" cmd /k "ngrok http 127.0.0.1:!TUNNEL_PORT!"
```

다음으로 교체한다:

```cmd
start "cloudflared" cmd /k "cloudflared tunnel --url http://localhost:!TUNNEL_PORT!"
```

`!TUNNEL_PORT!` 는 스크립트 상단 `TUNNEL_TARGET`(`ops`=8502 / `dashboard`=8501)에 따라
자동으로 정해지므로 포트를 직접 적지 않는다.

> 이어지는 터널 검증 블록(`http://127.0.0.1:4040/api/tunnels` 조회)은 ngrok 전용 API 라
> cloudflared 로 바꾸면 동작하지 않는다. 그 부분은 지우거나, cloudflared 창에 뜨는
> URL 을 눈으로 확인하는 방식으로 대체한다.

> 💡 Cloudflare Tunnel 을 쓰는 실질적 이유는 **Cloudflare Access 로 무료 인증**을
> 붙일 수 있다는 점이다. 이 시스템은 앱 자체에 로그인이 없으므로, 무료로 인증을
> 걸려면 이 경로가 사실상 유일하다.

### ngrok vs Cloudflare Tunnel 비교

| 항목 | ngrok 무료 | Cloudflare Tunnel |
|------|-----------|-------------------|
| 고정 도메인 | 1개 (무료) | Quick: 없음 / Named: 무제한 (자기 도메인 필요) |
| 경고 페이지 | 있음 (Visit Site) | 없음 |
| 접속 횟수 제한 | 있음 | 없음 |
| 설정 난이도 | 매우 쉬움 | Quick은 동일 / Named는 DNS 설정 필요 |
| 인증 옵션 | 유료만 basic auth | Cloudflare Access로 무료 인증 가능 |


---

## 방법 4. Streamlit Community Cloud

> 난이도: ★★☆☆☆ | 비용: 무료 | 소요 시간: 30분
> 적합한 상황: PC를 안 켜도 팀원이 접속할 수 있게 하고 싶을 때

### 개요

GitHub에 코드를 push하면 Streamlit이 자동으로 서버를 띄워주는 공식 호스팅 서비스. URL이 고정되고 24시간 운영된다. 단, 모델 파일 크기 제한과 llama.cpp 미사용 제약이 있다.

### 핵심 제약 (반드시 먼저 확인)

- **llama.cpp 사용 불가**: Cloud 서버에는 GPU가 없고 로컬 바이너리를 실행할 수 없다. LLM 분석은 Anthropic/OpenAI 등 클라우드 제공자로 전환해야 한다.
- **의존성 무게**: `requirements.txt` 를 그대로 올리면 RAG 의존성이 **torch(실측 496MB)** 를 끌고 온다. onnxruntime·faster-whisper 까지 합치면 설치가 타임아웃되거나 실행 중 메모리로 죽는다. → 전용 `requirements-cloud.txt` 를 쓴다.
- **파일시스템 휘발**: 앱이 재시작되면 `fds_results.db` 에 쌓인 탐지 이력이 **사라진다.** 이력 보존이 필요하면 외부 DB 가 필요하다.
- **GitHub 파일 크기**: `models/rf_fds.pkl` 이 84MB 라 GitHub 가 경고한다(100MB 초과 시 차단). Git LFS 를 권장.
- **워처가 없다**: `watcher.py` 는 로컬 프로세스다. Cloud 에는 `inbox/` 감시가 없으므로 관제 콘솔은 "워처 응답 없음" 상태로 뜬다.
- **인증**: 무료 플랜은 public 레포만 지원하고, 앱도 공개된다. Cloud 의 뷰어 제한 기능을 켜거나 앱 레벨 로그인을 붙일 것.

### 단계별 가이드

**1단계: GitHub 레포 생성**

`.gitignore` 가 이미 준비돼 있다 — 비밀값(`.env`)·운영 DB(`*.db`)·대용량 데이터(`data/`)를 자동으로 제외한다. push 전에 반드시 확인:

```bash
git status --short        # .env 와 *.db 가 목록에 없어야 한다
```

올라가는 구조:

```
fds-dashboard/
├── dashboard.py                  QA 대시보드
├── ops_dashboard.py              관제 콘솔
├── i18n_data.py
├── secrets_bridge.py           ★ st.secrets → os.environ
├── pipeline/                     (__init__.py 포함 전체)
├── tools/
├── docs/                         RAG 원문
├── models/                     ★ 메타 4종 필수 (Git LFS 권장)
├── requirements-cloud.txt      ★ Cloud 전용
├── requirements.txt              (로컬용 — 함께 둬도 무방)
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
└── .env.example

제외됨: .env · *.db · data/ · chroma_db/ · inbox/ · __pycache__/
```

**2단계: 의존성 지정**

Cloud 앱 설정에서 **`requirements-cloud.txt`** 를 지정한다. 이 파일은 다음을 뺀다:

| 제외 | 그래서 꺼지는 기능 |
|---|---|
| `chromadb` · `sentence-transformers` | 📚 RAG 문서 검색 |
| `faster-whisper` | 🎙 음성 입력 |
| `onnxruntime` · `sklearn-pmml-model` | ONNX/PMML 모델 로더 |

LightGBM·sklearn 번들 탐지와 LLM 분석은 그대로 동작한다.
대시보드 상단에 "설치 안 된 패키지" 안내가 뜨는 것은 **정상**이다 — 경고일 뿐 앱은 돈다.
(이 조합으로 두 앱이 예외 0 으로 부팅하는 것을 확인했다)

**3단계: Secrets 설정**

`.env` 는 `.gitignore` 로 막혀 있으므로 Cloud 에는 올라가지 않는다. 대신 Secrets 를 쓴다.

앱 페이지 > ⋮ > **Settings > Secrets** 에 `.streamlit/secrets.toml.example` 내용을 붙여넣고 값을 채운다:

```toml
USE_LLM_PROVIDER = "anthropic"
ANTHROPIC_API_KEY = "sk-ant-..."

[notify]
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/..."
SMTP_USER = "..."
SMTP_PASS = "..."          # Gmail 앱 비밀번호(16자)
```

> 코드는 전부 `os.getenv` 로 설정을 읽는다. `secrets_bridge.py` 가 앱 부팅 시
> `st.secrets` 를 `os.environ` 으로 넘겨주므로 **앱 코드는 로컬과 Cloud 에서 동일**하다.
> 섹션(`[notify]`)으로 묶어도 평면 키로 펼쳐서 읽는다.

**4단계: 배포**

1. https://share.streamlit.io 접속 → "New app"
2. GitHub 레포·브랜치 지정
3. **Main file path**: `ops_dashboard.py` 또는 `dashboard.py`
   (두 앱을 다 쓰려면 같은 레포로 **앱을 2개** 만든다 — Cloud 는 포트 개념이 없다)
4. Advanced settings → Python 버전과 **requirements 파일 경로**(`requirements-cloud.txt`) 지정
5. Secrets 붙여넣기 → Deploy

빌드 로그를 확인하고, 완료되면 `https://your-app.streamlit.app` URL이 생성된다.

**5단계: LLM 제공자 전환 확인**

`USE_LLM_PROVIDER` 를 secrets 에서 `anthropic`(또는 `openai`/`custom`)으로 두었는지 확인한다.
`local` 로 남아 있으면 llama.cpp 를 찾다 실패해 **모든 LLM 분석이 폴백 템플릿으로 떨어진다.**
사이드바에서 세션 단위로 바꿀 수도 있다.

**6단계: 배포 후 점검**

- 🩺 진단 탭 → 자가진단 통과 확인
- 모델이 로드됐는가 (사이드바 모델 배지)
- "워처 응답 없음" 경보는 Cloud 에서 **정상**이다 — 워처가 로컬 전용이라서다

### 코드 수정 후 반영

```cmd
git add -A
git commit -m "fix: 버그 수정"
git push origin main
```

Streamlit Cloud가 자동으로 감지하고 약 1~2분 내에 재빌드한다. 별도 배포 명령이 필요 없다.


---

## 방법 5. HuggingFace Spaces

> 난이도: ★★☆☆☆ | 비용: 무료 (16GB RAM) | 소요 시간: 30분
> 적합한 상황: Streamlit Cloud보다 더 큰 리소스가 필요할 때, 모델 파일이 클 때

### 개요

HuggingFace에서 Streamlit 앱을 직접 호스팅한다. 무료 티어가 2vCPU/16GB RAM으로 넉넉하고, Git LFS로 대용량 모델 파일도 함께 올릴 수 있다. 비공개(private) Space도 무료이며, ML 프로젝트와 궁합이 특히 좋다.

### 핵심 제약

- **llama.cpp 사용 불가**: Streamlit Cloud와 동일. GPU가 필요하면 유료 티어($~0.6/시간 T4 GPU)를 써야 하지만 FDS 대시보드의 LightGBM에는 GPU가 필요 없다.
- **Cold start**: 일정 시간 미사용 시 Space가 슬립 상태로 전환되고, 다음 접속 시 재빌드에 1~3분 소요.
- **디스크 50GB**: 모델+데이터를 합쳐 50GB까지 가능.

### 단계별 가이드

**1단계: HuggingFace 계정 생성**

https://huggingface.co/join 에서 무료 가입.

**2단계: 새 Space 생성**

https://huggingface.co/new-space 에서:
- Space name: `fds-dashboard`
- License: 선택
- SDK: **Streamlit** 선택
- Hardware: **CPU basic (Free)** — 2vCPU, 16GB RAM
- Visibility: **Private** (팀원만 접근) — 무료

"Create Space" 클릭.

**3단계: 코드 업로드**

Space가 생성되면 Git 레포 URL이 제공된다.

```cmd
:: HuggingFace CLI 설치 (최초 1회)
pip install huggingface_hub

:: 로그인
huggingface-cli login

:: Space 클론
git clone https://huggingface.co/spaces/내아이디/fds-dashboard
cd fds-dashboard
```

파일 구조를 복사한다 (Streamlit Cloud와 동일 구조).

추가로 루트에 `README.md`가 필요하다:

```markdown
---
title: FDS QA Dashboard
emoji: 🔍
colorFrom: blue
colorTo: purple
sdk: streamlit
sdk_version: "1.45.0"
app_file: dashboard.py
pinned: false
---
```

**4단계: 대용량 모델 파일 업로드 (Git LFS)**

```cmd
:: Git LFS 설치 확인
git lfs install

:: pkl 파일을 LFS로 추적
git lfs track "*.pkl"
git lfs track "*.gguf"

:: .gitattributes가 생성됨 — 커밋에 포함
git add .gitattributes
git add -A
git commit -m "initial: FDS dashboard + models"
git push origin main
```

**5단계: Secrets 설정**

Space 페이지 → Settings → "Repository secrets"에서:

```
ANTHROPIC_API_KEY = sk-ant-...
USE_LLM_PROVIDER = anthropic
```

**6단계: 접속 확인**

빌드 완료 후 `https://내아이디-fds-dashboard.hf.space` URL로 접속한다.

Private Space는 HuggingFace 로그인이 필요하므로, 팀원에게:
1. HuggingFace 계정을 만들게 한다
2. Space Settings → "Add collaborator"로 팀원을 추가한다

### 코드 수정 후 반영

```cmd
git add -A && git commit -m "fix" && git push
```

자동 재빌드 (1~2분). Streamlit Cloud와 동일한 git push 워크플로우.


---

## 방법 6. Docker + 클라우드 VM

> 난이도: ★★★☆☆ | 비용: 월 ~1~5만원 | 소요 시간: 1~2시간
> 적합한 상황: 24시간 안정 운영, 인증/HTTPS 직접 제어, 장기 팀 공유

### 개요

Dockerfile로 앱 전체(Streamlit + pipeline + 모델)를 패키징한 뒤, 클라우드 VM(AWS EC2, GCP, NCP 등)에 올린다. Nginx를 앞단에 둬서 HTTPS와 접근 제어를 붙이면 실무 수준의 배포가 완성된다.

### 핵심 고려사항

- **llama.cpp**: 클라우드 VM에 GPU가 없으면 llama.cpp를 쓸 수 없다. GPU 인스턴스는 비싸므로(월 10~50만원), 보통은 Anthropic API로 전환한다. 또는 "대시보드만 클라우드, llama.cpp는 로컬"로 분리할 수 있지만 복잡도가 올라간다 (부록 C 참고).
- **보안**: 공개 인터넷에 노출되므로 인증 필수. 최소한 Nginx basic auth 또는 Streamlit의 `st-login` 패키지를 사용한다.

### 단계별 가이드

**1단계: Dockerfile 작성**

프로젝트 루트에 `Dockerfile`을 만든다:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgomp1 && rm -rf /var/lib/apt/lists/*

# Python 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 + 모델
COPY . .

# Streamlit 포트
EXPOSE 8501

# 헬스체크
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "dashboard.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--browser.gatherUsageStats=false"]
```

`.dockerignore` 파일:

```
.git
__pycache__
*.pyc
.env
chroma_db/
data/train.csv
data/test.csv
```

**2단계: 로컬에서 Docker 빌드 및 테스트**

```cmd
:: Docker Desktop이 실행 중인 상태에서
docker build -t fds-dashboard .

:: 로컬 테스트 실행
docker run -p 8501:8501 --env-file .env fds-dashboard
```

브라우저에서 `http://localhost:8501`로 대시보드가 뜨는지 확인한다.

**3단계: 클라우드 VM 생성**

AWS EC2를 예시로 한다 (GCP, NCP 등도 유사):

1. AWS 콘솔 → EC2 → "인스턴스 시작"
2. AMI: Ubuntu 24.04 LTS
3. 인스턴스 유형: `t3.medium` (2vCPU, 4GB RAM — LightGBM에 충분)
4. 스토리지: 30GB
5. 보안 그룹: 22(SSH), 80(HTTP), 443(HTTPS) 인바운드 허용
6. 키페어 다운로드

예상 비용: t3.medium 서울 리전 기준 월 약 $30~40 (약 4~5만원).

**4단계: VM에 Docker 설치 + 배포**

```bash
# SSH 접속
ssh -i key.pem ubuntu@VM공개IP

# Docker 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 재접속 후

# 이미지를 직접 빌드하거나, Docker Hub에서 pull
# 방법 A: 코드를 VM으로 복사 후 빌드
git clone https://github.com/내계정/fds-dashboard.git
cd fds-dashboard
docker build -t fds-dashboard .

# 실행
docker run -d --name fds \
  -p 8501:8501 \
  --restart unless-stopped \
  --env-file .env \
  fds-dashboard
```

**5단계: Nginx 리버스 프록시 + HTTPS**

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# Nginx 설정
sudo tee /etc/nginx/sites-available/fds << 'EOF'
server {
    listen 80;
    server_name fds.내도메인.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }

    # Streamlit WebSocket 경로
    location /_stcore/stream {
        proxy_pass http://127.0.0.1:8501/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/fds /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# HTTPS 인증서 (무료, 자동 갱신)
sudo certbot --nginx -d fds.내도메인.com
```

**6단계: 접근 제어 (Basic Auth)**

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd 팀원아이디

# Nginx 설정의 location / 블록 안에 추가:
#   auth_basic "FDS Dashboard";
#   auth_basic_user_file /etc/nginx/.htpasswd;
sudo systemctl reload nginx
```

### 코드 수정 후 반영

```bash
# VM에서
cd fds-dashboard
git pull origin main
docker build -t fds-dashboard .
docker stop fds && docker rm fds
docker run -d --name fds -p 8501:8501 --restart unless-stopped --env-file .env fds-dashboard
```

자동화하려면 GitHub Actions CI/CD를 구성한다 (push시 자동 빌드 및 배포).


---

## 방법 7. FastAPI + 프론트엔드 전환

> 난이도: ★★★★★ | 비용: 월 ~3~10만원 | 소요 시간: 수주
> 적합한 상황: FDS를 정식 내부 서비스로 격상, 다중 사용자 + 권한 관리 필요

### 개요

Streamlit을 걷어내고, 백엔드(FastAPI)가 pipeline 모듈을 REST API로 노출하고, 프론트엔드(React/Vue/순수 HTML+JS)를 직접 구축한다. UI 자유도가 극대화되고, 로그인/권한/감사 로그 등 엔터프라이즈 기능을 직접 제어할 수 있다.

### 이 방법이 필요한 시점

아래 조건 중 2개 이상 해당되면 전환을 고려한다:
- 동시 접속 10명 이상
- 사용자별 권한 분리가 필요 (관리자/분석관/뷰어)
- Streamlit의 UI 한계(커스텀 차트, 실시간 대시보드, 모바일 대응 등)에 부딪힘
- 외부 시스템(SIEM, 티켓 시스템 등)과 API 연동 필요

아직 이 단계가 아니라면 방법 2~6이 훨씬 효율적이다.

### 아키텍처 개요

```
[프론트엔드]                    [백엔드 API]              [서비스]
React/Vue/HTML  ──HTTP──>  FastAPI                 ┬──> MLClassifier
  차트(Plotly.js)             /api/predict           ├──> LLMAnalyzer
  로그인 UI                   /api/batch             ├──> Evaluator
  대시보드 UI                  /api/evaluate          ├──> PIIMasker
                              /api/notify            └──> Notifier
```

### 단계별 가이드 (개략)

**1단계: FastAPI 백엔드 골격**

```python
# backend/main.py
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pipeline.ml_classifier import MLClassifier
from pipeline.llm_analyzer import LLMAnalyzer
from pipeline.pii_masker import PIIMasker

app = FastAPI(title="FDS API", version="1.0")
clf = MLClassifier()
masker = PIIMasker()

@app.post("/api/predict")
async def predict(row: dict):
    fraud_type, risk_score, proba = clf.predict(row)
    return {
        "fraud_type": fraud_type,
        "risk_score": risk_score,
        "proba": proba,
    }

@app.post("/api/batch")
async def batch_predict(rows: list[dict]):
    results = clf.predict_batch(rows)
    return [{"fraud_type": ft, "risk_score": rs} for ft, rs, _ in results]

@app.get("/api/health")
async def health():
    return {"status": "ok", "model_loaded": clf.model is not None}
```

**2단계: 프론트엔드**

React 또는 Vue.js로 대시보드 UI를 새로 구축한다. 기존 Streamlit 화면의 레이아웃을 참고하되, 차트는 Plotly.js를 직접 사용하고, 상태 관리는 프레임워크에 맡긴다.

이 단계가 가장 공수가 크다. 현재 `dashboard.py` 3,300줄의 UI 로직을 프론트엔드 코드로 재작성해야 한다.

**3단계: Docker Compose로 묶기**

```yaml
# docker-compose.yml
version: "3.8"
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - ./models:/app/models

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - backend
      - frontend
```

**4단계: 배포**

방법 6과 동일하게 클라우드 VM에 Docker Compose로 올린다.

### 이 방법의 장단점

장점:
- UI 완전 자유 (모바일 대응, 커스텀 컴포넌트 등)
- 백엔드 API를 다른 시스템에서도 호출 가능
- 사용자별 인증/권한/감사 로그
- 수평 확장 가능 (로드밸런서 + 복수 인스턴스)

단점:
- 개발 공수가 방법 1~6의 10배 이상
- 프론트엔드 + 백엔드 각각 유지보수
- Streamlit의 편리한 위젯(st.slider, st.dataframe 등)을 전부 직접 구현해야 함


---

## 부록 A. 정적 HTML 보고서 내보내기

> 난이도: ★★☆☆☆ | 비용: 무료 | 소요 시간: 구현 1시간, 사용 1초
> 적합한 상황: 결과를 이메일 첨부, 비개발자에게 읽기 전용 공유

### 개요

대시보드의 분석 결과를 HTML 파일 하나로 export하는 기능을 대시보드에 추가한다. Plotly 차트는 HTML에 인라인으로 포함돼서 브라우저에서 인터랙티브하게 볼 수 있다. 서버가 필요 없고, 파일을 보내면 끝이다.

### 구현 방법

`dashboard.py`에 내보내기 함수를 추가한다:

```python
import plotly.io as pio

def export_report_html(eval_data, batch_result, charts):
    """분석 결과를 자기완결적 HTML 파일로 내보내기"""
    html_parts = [
        "<html><head><meta charset='utf-8'>",
        "<title>FDS 분석 보고서</title>",
        "<style>body{font-family:sans-serif;max-width:1200px;margin:auto;padding:20px}</style>",
        "</head><body>",
        f"<h1>FDS 분석 보고서</h1>",
        f"<p>생성일시: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>",
    ]

    # Plotly 차트를 HTML로 변환 (CDN 없이 자기완결)
    for name, fig in charts.items():
        html_parts.append(f"<h2>{name}</h2>")
        html_parts.append(pio.to_html(fig, include_plotlyjs='cdn', full_html=False))

    # 배치 결과 테이블
    if batch_result:
        html_parts.append(f"<h2>배치 분석 결과</h2>")
        html_parts.append(f"<p>{batch_result.summary_line}</p>")
        html_parts.append(f"<pre>{batch_result.analysis}</pre>")

    html_parts.append("</body></html>")

    report = "\n".join(html_parts)
    with open("fds_report.html", "w", encoding="utf-8") as f:
        f.write(report)
    return "fds_report.html"
```

대시보드에 "보고서 내보내기" 버튼을 추가하고, 생성된 HTML을 `st.download_button`으로 제공한다. 이 방법은 실시간 탐지는 안 되지만, 주간 보고서나 감사 자료 제출에 적합하다.


---

## 부록 B. 방법별 비교 요약표

| 항목 | 1. 로컬 LAN | 2. ngrok | 3. CF Tunnel | 4. ST Cloud | 5. HF Spaces | 6. Docker+VM | 7. FastAPI |
|------|:-----------:|:--------:|:------------:|:-----------:|:------------:|:------------:|:----------:|
| llama.cpp 사용 | O | O | O | X | X (무료) | 조건부 | 조건부 |
| PC 꺼도 운영 | X | X | X | O | O | O | O |
| 고정 URL | IP고정시 | 무료1개 | 무료 | O | O | O | O |
| 비용 | 무료 | 무료~$8 | 무료 | 무료 | 무료 | 1~5만/월 | 3~10만/월 |
| 동시접속 | ~5명 | ~5명 | ~5명 | ~3명 | ~5명 | 10+명 | 50+명 |
| 유지보수 반영 | 즉시 | 즉시 | 즉시 | 2분 | 2분 | 5~10분 | 10분+ |
| 인증 | 없음 | 유료만 | 무료 | GitHub | HF계정 | Nginx | 직접구현 |
| 구현 난이도 | 5분 | 10분 | 20분 | 30분 | 30분 | 1~2시간 | 수주 |

O = 가능 / X = 불가 / 조건부 = GPU 서버 필요


---

## 부록 C. llama.cpp 아키텍처 의사결정 흐름

대시보드 배포 방법을 선택할 때 가장 먼저 결정해야 하는 것은 "LLM을 어디서 돌릴 것인가"이다.

```
llama.cpp를 꼭 써야 하는가?
 │
 ├─ YES ──→ 대시보드도 같은 PC에서 돌릴 수 있는가?
 │            │
 │            ├─ YES ──→ 방법 1(LAN) 또는 방법 2(ngrok) 또는 방법 3(CF Tunnel)
 │            │          이게 가장 단순하고 현실적인 구성이다.
 │            │
 │            └─ NO ───→ GPU 서버에 llama.cpp + 대시보드를 함께 Docker로 올림
 │                       → 방법 6 (Docker+VM, GPU 인스턴스 — 월 10만원+)
 │
 └─ NO (API도 OK) ──→ PC를 안 켜도 되어야 하는가?
                       │
                       ├─ YES ──→ 방법 4(ST Cloud) 또는 방법 5(HF Spaces)
                       │          LLM은 Anthropic/OpenAI API로 전환
                       │
                       └─ NO ───→ 방법 1/2/3으로 시작하되,
                                  llm_analyzer의 provider를 'anthropic'으로 설정.
                                  llama.cpp 없이도 대시보드 자체는 작동함
                                  (LLM 분석만 클라우드 API 사용)
```

현재 오빠의 상황 (llama.cpp 필수 + PC에서 운영 가능)에서는 방법 2(ngrok)가 최적이며, 이미 성공적으로 운영 중이다. 장기적으로 llama.cpp 의존을 줄이고 싶다면 Anthropic API를 병행 설정해두면 방법 4/5로의 전환이 자연스럽다.


---

> 이 문서의 모든 명령어는 2026-07 기준이며, 각 서비스의 요금/정책은 변경될 수 있으므로 공식 사이트를 확인하시기 바랍니다.
