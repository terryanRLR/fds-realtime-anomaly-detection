# FDS 대시보드 팀 공유 세팅 가이드

> dashboard v9.0 + Gemma 4 26B-A4B + ngrok 터널링 구성


## 1. 현재 매개변수 진단

### llama-server.exe — 변경 필요 항목

| 매개변수 | 현재값 | 권장값 | 사유 |
|----------|--------|--------|------|
| `-np` | `1` | `2` ~ `3` | **핵심 변경.** 팀원이 동시 접속하면 LLM 분석 요청이 큐에 쌓여서 한 명이 분석 중이면 나머지는 대기. 최소 2 이상 필요 |
| `-c` | `98304` (96K) | `16384` (16K) | **가장 큰 VRAM 절약.** FDS 프롬프트 최대 ~3K + 응답 1.5K = 약 4.5K 토큰이면 충분. 96K는 논문/소설 생성용 — FDS엔 과도. 줄이면 np 늘릴 VRAM 여유가 생김 |
| `--temperature` | `0.7` | `0.55` | llm_analyzer가 API 요청에 temperature를 안 보내서 **서버 기본값이 그대로 적용됨.** FDS 보고서는 일관성이 중요하므로 살짝 낮추기 권장 (0.5~0.6) |

> **VRAM 트레이드오프**: `-c 98304 -np 1` → `-c 16384 -np 3` 변경 시
> 슬롯당 context = 16384 ÷ 3 ≈ 5,461 토큰 (FDS 최대 사용량 4,500의 1.2배 — 충분)
> KV 캐시 총량은 오히려 줄어들어 VRAM에 여유가 생김

### llama-server.exe — 유지해도 좋은 항목

| 매개변수 | 값 | 판정 |
|----------|-----|------|
| `-fa on` | Flash Attention | ✅ 유지 — 성능 최적화 |
| `--cont-batching` | Continuous batching | ✅ 유지 — np>1일 때 필수 |
| `--jinja` | Jinja 템플릿 | ✅ **필수** — Gemma 4 턴 포맷을 /v1/chat/completions에 자동 적용 |
| `--no-kv-unified` | KV 캐시 비통합 | ✅ 유지 |
| `-ctk turbo3 -ctv turbo3` | KV 캐시 양자화 | ✅ 유지 — VRAM 절약에 기여 |
| `--swa-full` | Sliding Window Attention | ✅ 유지 |
| `--ctx-checkpoints 1` | Context checkpointing | ✅ 유지 |
| `-fit on` | VRAM fit | ✅ 유지 |
| `-to 1800` | 타임아웃 30분 | ✅ 유지 — 배치 분석이 길어질 수 있음 |
| `--repeat-penalty 1.12` | 반복 억제 | ✅ 유지 — llm_analyzer의 `_is_degenerate()` 방어와 시너지 |
| `--top-p 0.9 --top-k 40` | 샘플링 | ✅ 유지 — 합리적 범위 |
| `--host 127.0.0.1 --port 8080` | 로컬 바인딩 | ✅ **반드시 유지** — 외부 노출 차단 (아래 참고) |

### ngrok — 대상 포트 변경 필요!

```
현재 (문제)     :  ngrok http 127.0.0.1:8080    ← llama.cpp API를 외부 노출
권장 (수정)     :  ngrok http 127.0.0.1:8501    ← 대시보드를 외부 노출
```

**왜?** 현재 구성은 llama.cpp API가 인터넷에 열려 있어서:
- 누구든 ngrok URL로 프롬프트를 보낼 수 있음 (GPU 무단 사용)
- 대시보드는 여전히 localhost에서만 접근 가능 → 팀원이 못 씀

수정 후 흐름:
```
팀원 브라우저 → ngrok URL → Streamlit(8501) → localhost:8080(llama.cpp)
                ↑ 외부 노출              ↑ 내부 통신만 (안전)
```

대시보드만 노출하면 llama.cpp는 localhost에 숨겨지고,
팀원은 대시보드 UI를 통해서만 LLM을 사용하게 됨 (직접 API 접근 불가).

### Streamlit — 추가 권장 옵션

```
현재:   streamlit run dashboard.py
권장:   streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

- `--server.address 0.0.0.0` : 같은 LAN의 팀원이 ngrok 없이 직접 `http://오빠IP:8501`로도 접속 가능
- `--server.port 8501` : 명시적 포트 고정 (기본값이긴 하지만 확실히)


## 2. 권장 실행 명령어 (수정 후)

### 터미널 1 — llama.cpp 서버
```cmd
.\llama-server.exe ^
  --model C:\Users\terry\llama-cpp-turboquant\models\gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf ^
  -fa on --cont-batching --no-kv-unified ^
  -ctk turbo3 -ctv turbo3 ^
  -to 1800 -fit on --swa-full --ctx-checkpoints 1 ^
  -np 3 ^
  --host 127.0.0.1 --port 8080 ^
  -c 16384 ^
  --temperature 0.55 --repeat-penalty 1.12 --top-p 0.9 --top-k 40 ^
  --jinja
```

> np·context를 GPU에 맞게 조정:
> - VRAM 12GB: `-np 2 -c 12288` (슬롯당 ~6K)
> - VRAM 16GB: `-np 3 -c 16384` (슬롯당 ~5.5K)
> - VRAM 24GB: `-np 4 -c 24576` (슬롯당 ~6K) — 여유롭게

### 터미널 2 — Streamlit 대시보드
```cmd
call conda activate qaqc_st
cd /d %USERPROFILE%\바탕 화면\QAQC_streamlit
streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

### 터미널 3 — ngrok 터널 (대시보드 노출)
```cmd
ngrok http 127.0.0.1:8501
```

> ngrok 창에 뜨는 `https://xxxx.ngrok-free.app` URL을 팀원에게 공유


## 3. 원클릭 실행 스크립트

동봉된 `start_fds_team.bat`을 더블클릭하면 세 창이 순서대로 뜸:
1. llama.cpp 서버 (10초 대기 후)
2. Streamlit 대시보드 (5초 대기 후)  
3. ngrok 터널

스크립트 상단의 변수를 자신의 환경에 맞게 수정해서 사용.


## 4. 팀원 안내 사항

팀원에게 공유할 때 아래만 알려주면 됨:

```
FDS 대시보드 접속 안내
━━━━━━━━━━━━━━━━━━━━
URL: https://xxxx.ngrok-free.app  (ngrok 창에서 확인)

첫 접속 시 "Visit Site" 버튼을 눌러주세요 (ngrok 무료 경고 페이지).
그 뒤로는 바로 대시보드가 뜹니다.

※ 서버 운영 시간: 오전 9시 ~ 오후 7시 (PC 켜져 있을 때만)
※ LLM 분석은 건당 10~30초 소요됩니다
```


## 5. 보안 체크리스트

- [x] llama.cpp는 `--host 127.0.0.1` → 외부 직접 접근 차단
- [x] ngrok은 대시보드(8501)만 노출 → LLM API 숨김
- [ ] `.env`의 API 키(Anthropic/OpenAI)가 있다면 팀원이 세션5에서 볼 수 있음 → 필요시 제거
- [ ] ngrok 유료 플랜이면 `--basic-auth "user:pass"` 추가로 접근 제한 가능
- [ ] 대시보드의 파일 경로 입력(세션3 폴더 경로 등)은 서버 디렉토리 탐색 위험 → 신뢰할 수 있는 팀원만 공유


## 6. 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| 팀원이 접속은 되는데 LLM 분석이 안 됨 | llama.cpp 서버가 안 떠있음 | 터미널 1 확인 — 서버 로그에 "listening" 떠야 함 |
| "llama.cpp 연결 실패" 에러 | 포트 불일치 | 대시보드 세션5 설정에서 llama.cpp URL이 `http://localhost:8080/v1/chat/completions`인지 확인 |
| 분석이 매우 느림 (1분+) | np=1 + 동시 요청 큐잉 | `-np` 값 올리기, 또는 `-c` 줄이기 |
| ngrok URL이 바뀜 | 무료 플랜 재시작 | ngrok 유료면 고정 도메인 사용, 무료면 재시작마다 팀원에게 새 URL 공유 |
| "Visit Site" 페이지가 계속 뜸 | ngrok 무료 경고 | 한 번 클릭하면 세션 동안 안 뜸. 매번 귀찮으면 ngrok 유료 권장 |
| Streamlit "Source file changed" | dashboard.py 수정 감지 | 정상 동작 — "Rerun" 누르면 반영됨 (hot-reload) |
