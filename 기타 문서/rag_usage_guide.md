# RAG 시스템 사용 가이드
> FDS QA 검증 대시보드 — RAG(검색 증강 생성) 설정 및 사용법

---

## 1. RAG 개요

이 시스템의 RAG는 이상거래 탐지 후 LLM이 **"왜 이상인지"** 와 **"어떻게 대응해야 하는지"** 를 설명할 때, 관련 문서를 먼저 검색해 근거 있는 답변을 생성하도록 돕는다.

```
이상거래 탐지 (예: 유형 B, 점수 0.91)
        ↓
Chroma DB에서 "사기유형 B 루팅 VPN 탐지" 쿼리
        ↓
유사 문서 Top-K 반환 (fraud_types_a_to_f.md 청크 등)
        ↓
LLM 프롬프트에 삽입 → 근거 있는 분석 생성
```

---

## 2. 폴더 구조

```
프로젝트 루트/
├── docs/                          ← RAG 문서 폴더
│   ├── fraud_types_a_to_f.md     ← 사기 유형 A~F 시나리오
│   ├── fraud_types_g_to_l.md     ← 사기 유형 G~L 시나리오
│   ├── response_manual.md        ← 단계별 대응 매뉴얼
│   └── feature_dictionary.md     ← 피처 사전 및 데이터 품질
├── chroma_db/                     ← 벡터 DB (자동 생성)
└── pipeline/
    └── rag_searcher.py           ← RAG 검색 엔진
```

---

## 3. 최초 설치 및 초기화

### 패키지 설치
```bash
pip install chromadb sentence-transformers
```

### 벡터 DB 자동 초기화
`rag_searcher.py`는 최초 실행 시 `docs/` 폴더의 모든 `.md` 파일을 자동으로 읽어 임베딩한다.

```python
from pipeline.rag_searcher import RAGSearcher

# 최초 실행 시 자동으로 docs/ 임베딩 수행
rag = RAGSearcher(top_k=3)
# 로그 출력: "임베딩 완료: N개 청크"
```

### 임베딩 모델
```
snunlp/KR-SBERT-V40K-klueNLI-augSTS
```
- 한국어 특화 Sentence-BERT 모델
- 최초 실행 시 자동 다운로드 (약 400MB)
- 이후 캐시 사용으로 빠른 로딩

---

## 4. 사용 방법

### 기본 검색
```python
from pipeline.rag_searcher import RAGSearcher

rag = RAGSearcher(top_k=3)

# 사기 유형과 쿼리로 검색
results = rag.search(
    query="사기유형 B 루팅 VPN 단말 탈취 대응",
    fraud_type="b"
)

for doc in results:
    print(doc)
    print("---")
```

### 파이프라인 내 자동 연동
`main.py`에서는 이상거래 탐지 후 자동으로 RAG 검색이 수행된다.

```python
# main.py 내 자동 흐름
rag_context = rag.search(
    query=f"사기유형 {fraud_type} 이상거래 탐지 대응",
    fraud_type=fraud_type,
)
# → LLM 분석 시 rag_context가 프롬프트에 자동 삽입
```

### 대시보드에서 RAG 문서 수 조절
사이드바의 **"RAG 문서 수"** 슬라이더로 Top-K 값을 1~5 사이에서 조절할 수 있다.
- K=1: 가장 관련성 높은 문서 1개만 참고 (빠름, 간결)
- K=3: 기본값 (권장)
- K=5: 다양한 관점 참고 (느림, 풍부한 답변)

---

## 5. 문서 추가·수정 방법

### 새 문서 추가
`docs/` 폴더에 `.md` 파일을 추가한 뒤 벡터 DB를 재초기화한다.

```python
# 벡터 DB 초기화 후 재구축
import shutil
shutil.rmtree("chroma_db")  # 기존 DB 삭제

from pipeline.rag_searcher import RAGSearcher
rag = RAGSearcher(top_k=3)  # 자동으로 재임베딩
```

### 문서 작성 권장 형식
청크 단위 검색 품질을 높이려면 아래 형식을 권장한다.

```markdown
## 유형 X — 제목

### 개요
2~3문장 요약

### 핵심 지표
- 주요 플래그 및 수치

### 탐지 시그널
| 지표 | 값 |
|------|-----|

### 권장 대응 조치
1. 조치 1
2. 조치 2
```

문단 사이 빈 줄을 충분히 두면 청크 분할이 자연스럽게 이루어진다.

---

## 6. 문제 해결

### chromadb 설치 실패 시
```bash
pip install chromadb --upgrade
# M1/M2 Mac의 경우
pip install chromadb --no-binary chromadb
```

### 한국어 임베딩 모델 다운로드 느릴 때
인터넷 연결 확인 후 재시도. 또는 더 가벼운 모델로 교체:

```python
# rag_searcher.py 내 모델명 변경
model_name="paraphrase-multilingual-MiniLM-L12-v2"  # 경량 다국어 모델
```

### 더미 모드 동작 확인
chromadb 미설치 시 자동으로 더미 검색 결과를 반환한다.
로그에서 `"chromadb / sentence-transformers 미설치 — RAG 더미 모드"` 메시지 확인.

### chroma_db 폴더 오염 시
```bash
rm -rf chroma_db/
python -c "from pipeline.rag_searcher import RAGSearcher; RAGSearcher()"
```

---

## 7. RAG 문서 현황

| 파일명 | 내용 | 예상 청크 수 |
|--------|------|------------|
| fraud_types_a_to_f.md | 유형 A~F 시나리오 + 대응 | 약 30개 |
| fraud_types_g_to_l.md | 유형 G~L 시나리오 + 대응 | 약 30개 |
| response_manual.md | 단계별 대응 매뉴얼 + 규칙 | 약 20개 |
| feature_dictionary.md | 피처 사전 + 품질 기준 | 약 25개 |
| **합계** | | **약 105개 청크** |

---

## 8. 검색 쿼리 예시

| 상황 | 권장 쿼리 |
|------|---------|
| 유형 B 탐지 시 | `"사기유형 b 루팅 VPN 단말 탈취 대응"` |
| 유형 I 탐지 시 | `"사기유형 i ATM 한도 상향 초고액 출금"` |
| 유형 J 탐지 시 | `"미사용 계좌 수취계좌 정지 이체 차단"` |
| 일반 대응 조회 | `"위험점수 0.9 이상 즉시 차단 에스컬레이션"` |
| 오탐 처리 | `"오탐 FP 고객 확인 임계값 조정"` |
| 피처 해석 | `"Transaction_Amount 음수 출금 사기 패턴"` |
