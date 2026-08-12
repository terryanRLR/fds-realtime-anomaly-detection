# 🔧 이메일 오류 + LLM 출력 정제 수정 리포트

## 이슈 1: 이메일이 `담당자@example.com`으로 전송되는 문제

### 원인

`.env`에 올바른 이메일을 설정했는데도 `담당자@example.com`으로 발송된 이유:

dashboard.py에서 수신자 이메일을 `session_state`에서만 읽고, `.env` 파일은 전혀 참조하지 않았습니다.

```python
# 🔴 Before — .env를 한 번도 안 읽음! 하드코딩된 기본값만 사용
_to = st.session_state.get('notify_email', '담당자@example.com')
```

발생 흐름:

1. 사용자가 `.env`에 `FDS_NOTIFY_EMAIL=실제@회사.com` 설정
2. dashboard.py는 `session_state['notify_email']`을 확인
3. 해당 키가 없으면 → 기본값 `'담당자@example.com'` 사용
4. `example.com` 도메인은 실제로 존재하지 않으므로 → **DNS 조회 실패**

참고: `notifier.py`는 `.env`에서 SMTP 발신자 정보를 읽지만, **수신자** 주소는 대시보드에서 넘겨받는 구조여서 대시보드 쪽의 하드코딩이 원인이었습니다.

### 수정 내용

**dashboard.py:**
- `import os` + `dotenv.load_dotenv()` 추가
- `_DEFAULTS`에 `'notify_email': os.getenv('FDS_NOTIFY_EMAIL', ...)` 추가
- 자동발송(L634), 수동발송(L1328), 사이드바 입력(L939) 3곳 모두 `.env` 연동

```python
# 🟢 After — .env에서 읽고, 미설정 시 경고 로그
'notify_email': os.getenv('FDS_NOTIFY_EMAIL', os.getenv('SMTP_USER', '담당자@example.com'))
```

`.env` 파일에 추가할 항목:
```
FDS_NOTIFY_EMAIL=담당자@실제도메인.com
```

---

## 이슈 2: `<channel|><|channel>thought` 등 특수 토큰이 출력에 포함

### 원인

이 토큰들은 LLM 모델의 **내부 제어 토큰**이 출력으로 누출된 것입니다.

| 토큰 | 출처 | 의미 |
|------|------|------|
| `<\|channel>`, `<channel\|>` | DeepSeek, Qwen 계열 | 채팅 턴 구분 마커 |
| `thought` | CoT 모델 (DeepSeek-R1 등) | 사고 과정 시작 키워드 |
| `<\|im_start>`, `<\|im_end>` | ChatML 포맷 모델 | 메시지 블록 구분 |
| `<think>...</think>` | 추론 모델 | 내부 추론 블록 |

원래 이 토큰들은 모델 서버가 후처리에서 제거해야 하지만, llama.cpp 로컬 서버나 일부 API는 그대로 노출합니다.

### 수정 내용 (2중 방어)

**방어 1 — llama.cpp stop 토큰 확장:**
```python
"stop": [
    "</s>", "\n\n\n",
    "<|channel>", "<channel|>",     # 🆕
    "<|thought>", "<|end|>",        # 🆕
    "<|im_end|>", "<|endoftext|>",  # 🆕
    "<|eot_id|>",                   # 🆕
]
```

**방어 2 — 정규식 후처리 (아래 이슈 3과 통합):**
- `_call()` 반환 직전에 `_clean_output()` 자동 적용
- 모든 LLM 제공자(local, anthropic, openai 등)에 일괄 적용

---

## 이슈 3: 마크다운 억제를 프롬프트가 아닌 정규식으로

### 오빠의 제안에 대한 의견

**100% 동의합니다.** 프롬프트로 마크다운을 억제하는 방식은:
- 모델이 지시를 무시할 수 있음 (특히 로컬 소형 모델)
- 프롬프트 토큰을 낭비함
- 모델마다 준수율이 다름

**정규식 후처리가 더 나은 이유:**
- 모델 무관하게 100% 확실히 제거
- 프롬프트 토큰 절약
- 한 곳에서 관리 가능 (DRY 원칙)

### 구현: `_clean_output()` 정적 메서드

```
호출 흐름:
  _call_llama_cpp() / _call_anthropic() / _call_openai_compat()
    → 원시 텍스트 반환
    → _call() 에서 _clean_output(text, strip_markdown) 적용
    → 정제된 텍스트 반환
```

4단계 정제 파이프라인:

| 단계 | 대상 | 항상 적용 | strip_markdown 시 |
|------|------|----------|------------------|
| 1 | `<think>...</think>` 사고 블록 | ✅ | ✅ |
| 2 | `<\|channel>` 등 특수 토큰 | ✅ | ✅ |
| 2.5 | 잔여 `thought` 키워드 | ✅ | ✅ |
| 3 | `##`, `**`, `` ` ``, `>`, `- ` 등 마크다운 | ❌ | ✅ |
| 4 | 연속 빈 줄 정리 (3줄→2줄) | ✅ | ✅ |

적용 방식:
- **분석 리포트** (1호출): `strip_markdown=False` — 분석 패널에서는 마크다운이 유용
- **Slack 메시지** (2호출): `strip_markdown=True` — 평문 출력
- **이메일 본문** (3호출): `strip_markdown=True` — 평문 출력

### 테스트 결과

```
[1] 실제 오류 패턴  → PASS ✅  (토큰 완전 제거)
[2] 사고 블록       → PASS ✅  (여러줄 블록도 제거)
[3] 종합 시나리오   → PASS ✅  (토큰+마크다운 동시 정제)
[4] 정상 영문       → PASS ✅  ("I thought about..." 보존)
[5] 정상 한글       → PASS ✅  (변경 없음)
```
