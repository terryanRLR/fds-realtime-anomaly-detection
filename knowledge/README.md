# knowledge/ — RAG 지식베이스 (런타임 데이터)

> ⚠️ **이 폴더는 문서 폴더가 아니라 코드에 가깝습니다.**
> 여기 있는 모든 최상위 `.md` 가 벡터 DB 에 임베딩되어 **LLM 의 판정 근거로 인용**됩니다.
> 사람이 읽는 프로젝트 문서는 [`docs/`](../docs/) 에 있습니다.

---

## 파일

| 파일 | 내용 |
|---|---|
| `fraud_types.md` | 13개 유형별 정의 · **주요 지표(실측치)** · 판단 근거 · 오분류 주의 |
| `response_manual.md` | 위험점수 구간별 · 유형별 즉시/단기/장기 조치 |
| `rule_reference.md` | 규칙 체크리스트 전체와 실측 리프트 (`rule_checker.py` 와 1:1 대응) |

---

## 동작

```
knowledge/*.md
   ↓  pipeline/rag_searcher.py  (mtime 해시로 변경 감지)
chroma_db/  (Chroma + KR-SBERT 임베딩)
   ↓  탐지 시 유형별 검색
LLM 프롬프트에 근거 문서로 첨부 → 화면에도 함께 표시
```

파일을 고치면 다음 분석 때 **자동으로 재색인**됩니다.
인덱스를 완전히 다시 만들려면 `chroma_db/` 를 지우면 됩니다.

---

## 문서 생성 — 숫자를 문서에 박는다

```bash
python -m tools.build_rag_docs            # 3개 파일 생성
python -m tools.build_rag_docs --force    # 덮어쓰기
```

[`tools/build_rag_docs.py`](../tools/build_rag_docs.py) 가 팀 EDA 정의 + **120,000행 전수 검증 결과**를
구체적 수치와 함께 13개 유형 전부에 대해 문서화합니다.

> 설계 의도는 스크립트 docstring 에 있습니다 —
> **"숫자가 문서에 있으면 LLM 은 그것을 인용한다. 없으면 만들어낸다."**
>
> 기존 `fraud_types.md` 는 4개 유형만 3줄씩 있었고 수치가 하나도 없었습니다.
> 그 상태에서 LLM 은 판정 근거를 지어냈습니다.

이것이 멘토 지적 *"RAG 환각 위험을 어떻게 담보하는가"* 에 대한 답 중 하나입니다
→ [`docs/04_tutor_feedback.md` B-4](../docs/04_tutor_feedback.md)

---

## 왜 `docs/` 가 아니라 `knowledge/` 인가

원래 이 파일들은 `docs/` 에 있었습니다.
그런데 [`pipeline/rag_searcher.py`](../pipeline/rag_searcher.py) 가 이렇게 되어 있습니다.

```python
for md_file in sorted(DOCS_DIR.glob("*.md")):   # ← 필터가 없다
    ...
self.collection.add(documents=docs, ids=ids, metadatas=metas)
```

**최상위 `.md` 를 전부 임베딩합니다.**
프로젝트 문서를 `docs/` 에 두는 순간 기획서·이슈로그가
"사기 대응 매뉴얼"로 검색되어 LLM 판정 근거를 오염시킵니다. **아무 에러도 없이.**

→ 상세: [`docs/03b` #B-24](../docs/03b_issues_dashboard_pipeline.md#b-24)

**경로 변경**

| 항목 | 이전 | 현재 |
|---|---|---|
| `rag_searcher.DOCS_DIR` 기본값 | `docs` | **`knowledge`** |
| `tools/build_rag_docs.py --out` | `docs` | **`knowledge`** |
| 환경변수 오버라이드 | `FDS_DOCS_DIR` | 그대로 |

---

## 새 문서를 추가할 때

1. `knowledge/` 에 `.md` 를 둔다
2. **LLM 이 인용해도 되는 내용인지** 확인한다 — 여기 있는 것은 전부 판정 근거가 된다
3. 다음 분석 때 자동 재색인 (또는 대시보드의 `🔄 강제 재색인`)
4. 로그에 `knowledge/ 변경 감지 → 인덱스 재구축` 이 뜨는지 확인

> 프로젝트 문서 · 회고 · 기획서는 **절대 여기 두지 마세요.** [`docs/`](../docs/) 로 갑니다.
