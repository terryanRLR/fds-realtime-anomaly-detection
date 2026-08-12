import tempfile
from pathlib import Path
import os, sys, time, json, sqlite3
os.environ["TZ"]="Asia/Seoul"
try: time.tzset()
except AttributeError: pass
sys.path.insert(0,'.'); sys.path.insert(0,'pipeline')
from pipeline import analysis_store as astore, review_store as rs
from pipeline.pii_masker import PIIMasker

REAL_REPORT = ("""## 판정 근거

본 거래는 F형(위장 최종인출) 패턴과 높은 적합도를 보입니다. 결정적 근거는 다음 네 가지입니다.

1. **Others 채널 100%** — F형은 12개 유형 중 유일하게 Others 채널에서만 발생합니다. ATM·모바일 채널 발생 건수는 학습 데이터 기준 0건이며, 본 거래 역시 Others 채널입니다.
2. **1천만원 이상 입금 선행** — 거래 직전 대량 입금이 확인됩니다. E→G→F 3단 가설의 최종 단계에 해당합니다.
3. **원격제어 흔적 완전 부재** — 루팅 0%, 악성행위 플래그 0.00. 역설적으로 이 '깨끗함'이 F형의 서명입니다. E형(2.4배)·G형(1.3배)과 명확히 구분됩니다.
4. **거래 후 잔액 z=-0.42** — 전 유형 최저. 계좌를 가장 크게 비우는 인출입니다.

## 이상 패턴

수취계좌의 거래 이력이 z=-0.35로 신규에 가깝습니다. 대포통장 유입(J형) 직후의 인출 단계일 가능성을 배제할 수 없습니다. 접속 거리는 평균 수준으로 A형(원거리 즉시이체)과는 구분됩니다.

## 오탐 체크

- 정기 급여일 아님 — 거래일이 월말·10일·25일 어디에도 해당하지 않습니다
- 수취계좌가 과거 거래 이력에 없습니다 (기존 거래처 정산 가능성 낮음)
- 고객 신용등급은 A로 B형(저신용층 표적) 패턴과 무관합니다
- 다만 **법인 계좌의 대금 정산**일 가능성은 남아 있습니다. 계좌 유형과 사업자 여부를 확인하시기 바랍니다

## 권장 조치

1. 즉시 해당 계좌 출금 정지 및 고객 본인 확인 연락
2. 수취계좌에 대한 지급정지 요청 검토 (금융결제원)
3. 직전 대량 입금 건의 출처 계좌 역추적
4. 본 건이 오탐으로 확인될 경우 반드시 대시보드에 사유를 기록해 주십시오 — 임계값 조정의 근거가 됩니다
""")

DB = str(Path(tempfile.gettempdir()) / "ast.db")
if os.path.exists(DB): os.remove(DB)
con=sqlite3.connect(DB)
con.execute("""CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
 transaction_id TEXT, fraud_type TEXT, risk_score REAL, is_anomaly INTEGER DEFAULT 0,
 input_mode TEXT, true_label TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
con.commit(); con.close()
print("="*62)

# ── detect_service 를 흉내낸 가짜 서비스 (실제 반환 구조 그대로) ──
class Cfg:
    pii_level="standard"; th_review=0.45; th_confirm=0.80
    llm_provider="local"; llm_model="qwen2.5-7b"; db_path=DB
class FakeSvc:
    cfg=Cfg(); clf_mode="lgbm_13class"
    def detect(self, row, source="watcher"):
        return {"txn_id": row["transaction_id"], "fraud_type":"f", "fraud_name":"위장 최종인출",
                "risk_score":0.8734, "tier":"confirm", "is_anomaly":True, "llm_used":True,
                "proba":{c:0.01 for c in "abcdeghijkl"} | {"f":0.62,"m":0.1267},
                "llm":{"analysis":REAL_REPORT,
                       "slack":"🚨 *[확정] 즉시 대응 필요*\nTXN_9001 · 위험 0.87",
                       "email":"안녕하세요,\n\nF형 이상거래가 탐지되었습니다.",
                       "ctx":[{"doc":"f형 패턴","score":0.91}]},
                "sent_slack":True,"sent_email":True,"deduped":False,
                "source":source,"errors":[],"elapsed":2.41}

svc = FakeSvc()
ROW = {"transaction_id":"TXN_9001","Customer_personal_identifier":"이상호",
       "Account_account_number":"oVZASOzgcm","IP_Address":"171.237.22.26",
       "Customer_Birthyear":1980,"Transaction_Amount":12500000,"Channel":"Others"}

print("\n[1] 훅 부착 — 기존 파일 수정 없이 감싸지는가")
before = svc.detect
astore.attach(svc, DB)
print(f"  detect 교체됨: {svc.detect is not before}")
assert svc.detect is not before and getattr(svc,'_astore_attached',False)
print("  ✅ 인스턴스 래핑")

print("\n[2] 탐지 1건 → 캐시가 자동 저장되는가")
det = svc.detect(ROW)
assert det["risk_score"]==0.8734, "❌ 반환값이 변형됨"
c = astore.load(DB, "TXN_9001")
print(f"  캐시 존재: {c is not None} · 반환값 무손상: True")
assert c is not None
print(f"  LLM 분석 {len(c['llm']['analysis'])}자 · 확률 {len(c['proba'])}클래스 "
      f"· 등급 {c['tier']}")
assert "판정 근거" in c["llm"]["analysis"] and "권장 조치" in c["llm"]["analysis"]
print("  ✅ LLM 리포트 보존됨")

print("\n[3] PII 심층 방어 — 원본을 넘겨도 평문이 쌓이지 않는가")
print(f"  입력 이름  : {ROW['Customer_personal_identifier']}")
print(f"  캐시 이름  : {c['row']['Customer_personal_identifier']}")
print(f"  입력 계좌  : {ROW['Account_account_number']}")
print(f"  캐시 계좌  : {c['row']['Account_account_number']}")
assert c["row"]["Customer_personal_identifier"]=="이○○"
assert "*" in c["row"]["Account_account_number"]
raw = open(DB,'rb').read()
assert b"oVZASOzgcm" not in raw, "❌ DB 파일에 평문 계좌번호 존재"
assert "이상호".encode() not in raw, "❌ DB 파일에 평문 이름 존재"
print("  ✅ DB 파일 바이트 검사 — 평문 없음")

print("\n[4] 당시 환경 스냅샷")
for k in ("model","th_review","th_confirm","pii_level","llm_provider","llm_model","elapsed"):
    print(f"  {k:14s} {c[k]}")
assert c["th_review"]==0.45 and c["llm_provider"]=="local"
print("  ✅ 임계값이 바뀌어도 '이 판정의 기준'이 남는다")

print("\n[5] 압축 — 용량 감당 가능한가")
for i in range(40):
    r = dict(ROW); r["transaction_id"]=f"TXN_B{i:04d}"
    svc.detect(r)
s_ = astore.stats(DB)
print(f"  {s_['rows']}건 · 저장 {s_['stored_mb']}MB · 원본 {s_['raw_mb']}MB "
      f"· 압축률 {s_['ratio']}")
per = s_['stored_mb']*1e6/s_['rows']
print(f"  건당 {per:.0f}B → 하루 100건이면 1년 {per*100*365/1e6:.0f}MB")
assert s_["ratio"] < 0.6, f"압축률 {s_['ratio']}"
print("  ✅ 압축 동작")

print("\n[6] 정상거래는 캐시하지 않는가 (용량 낭비 방지)")
class NormSvc(FakeSvc):
    def detect(self, row, source="watcher"):
        d = FakeSvc.detect(self, row, source)
        d.update({"is_anomaly":False,"tier":"none","llm":{},"llm_used":False})
        return d
ns = NormSvc(); astore.attach(ns, DB)
n0 = astore.stats(DB)["rows"]
ns.detect({"transaction_id":"TXN_NORMAL"})
print(f"  정상거래 후 캐시 건수 변화: {n0} → {astore.stats(DB)['rows']}")
assert astore.stats(DB)["rows"]==n0
print("  ✅ 이상거래만 캐시")

print("\n[7] 재분석 이력 (추가 전용)")
svc.detect(ROW)
h = astore.history(DB, "TXN_9001")
print(f"  이력 {len(h)}건 · 최신 id={h[-1]['id']}")
assert len(h)==2
print("  ✅ 덮어쓰지 않음")

print("\n[8] 캐시 유무 배지")
ids = astore.cached_ids(DB, ["TXN_9001","TXN_NOPE"])
print(f"  캐시 보유: {sorted(ids)}")
assert ids=={"TXN_9001"}
print("  ✅ 배지 판정")

print("\n[9] 보존 정책 — 판정된 건은 나이와 무관하게 남는가")
rs.record(DB, "TXN_B0001", "fp", reason="legit_customer", reviewer="김검토")
con=sqlite3.connect(DB)
con.execute("UPDATE analysis_cache SET captured_at=datetime('now','-400 days')")
con.commit(); con.close()
n, msg = astore.prune(DB, keep_days=180, keep_reviewed=True)
print(f"  {msg}")
print(f"  판정된 TXN_B0001 캐시 생존: {astore.load(DB,'TXN_B0001') is not None}")
print(f"  판정없는 TXN_9001 캐시 생존: {astore.load(DB,'TXN_9001') is not None}")
assert astore.load(DB,"TXN_B0001") is not None
assert astore.load(DB,"TXN_9001") is None
print("  ✅ 감사 자료 보존")

print("\n[10] 저장 실패가 탐지를 막지 않는가")
class Boom(FakeSvc):
    pass
b = Boom(); astore.attach(b, "/nonexistent/dir/x.db")
d = b.detect(ROW)
print(f"  잘못된 DB 경로에서도 탐지 반환: {d['risk_score']}")
assert d["risk_score"]==0.8734
print("  ✅ 캐시 실패가 알림을 막지 않음")

print("\n"+"="*62); print("✅ 전체 통과")
