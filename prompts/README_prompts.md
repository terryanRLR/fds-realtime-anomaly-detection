# prompts/ — LLM 프롬프트 커스텀 (선택)

이 폴더에 `analysis_prompt.py` 를 두면 LLM 분석 프롬프트를 교체할 수 있습니다.
**없으면 `llm_analyzer` 내장 폴백 프롬프트를 씁니다 — 그것이 현재 상태입니다.**

```python
# analysis_prompt.py 가 제공해야 하는 것
def get_prompts(...): ...
FRAUD_TYPE_NAMES = {...}
```

로드 지점: [pipeline/llm_analyzer.py:88](../pipeline/llm_analyzer.py#L88)
임포트가 실패하면 경고 로그 한 줄만 남기고 내장 프롬프트로 조용히 넘어갑니다.

```
프롬프트 모듈 사용 불가 → 기본 프롬프트 사용: No module named 'prompts.analysis_prompt'
```

위 로그는 **정상 동작**입니다 — 파일을 두지 않기로 한 상태라는 뜻입니다.

> 화면에서 프롬프트를 고치고 싶다면 이 파일 대신 대시보드의 **프롬프트 편집기**를
> 쓰세요 (`detect_workbench.render_prompt_editor()` — 두 앱 공용).

---

## overrides.json — 화면에서 고친 프롬프트 (자동 생성)

프롬프트 편집기의 **[💾 저장]** 이 쓰는 파일입니다. `analysis` / `slack` / `email` /
`batch` 네 슬롯을 담고, **dashboard.py 와 ops_dashboard.py 가 이 한 벌을 함께 씁니다** —
한쪽에서 저장하면 다른 쪽 분석에도 즉시 반영됩니다(재시작 불필요).

```json
{ "analysis": "당신은 …", "email": "…", "_saved_at": "2026-08-10 10:33:30" }
```

| | |
|---|---|
| 우선순위 | **파일 > 내장 기본 프롬프트.** 세션 사본은 파일 쓰기가 실패했을 때만 쓰입니다 |
| 없을 때 | 내장 기본 프롬프트 — 정상 상태입니다 |
| 깨졌을 때 | 경고 로그 한 줄 남기고 기본 프롬프트로 진행합니다 (앱은 안 멈춥니다) |
| [↩ 기본값 복원] | 해당 슬롯을 파일에서 **삭제** → 두 앱 모두 기본값으로 돌아갑니다 |
| 경로 변경 | 환경변수 `FDS_PROMPT_STORE` |
| Git | `.gitignore` 대상 — 현장에서 고친 문구가 섞이므로 커밋하지 않습니다 |

동시 저장은 쓰기 직전에 다시 읽어 합치고(read-modify-write) 원자적으로 교체하므로,
두 앱이 **서로 다른 슬롯**을 동시에 저장해도 서로를 덮지 않습니다. 같은 슬롯을 같은
순간에 저장하면 나중 저장이 이깁니다.
