import tempfile
from pathlib import Path
import os, sys, json, time
os.environ["TZ"]="Asia/Seoul"
try: time.tzset()
except AttributeError: pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import ops_recheck as rc
from pipeline.pii_masker import PIIMasker

DB = str(Path(tempfile.gettempdir()) / "test_fds.db")
print("="*62)

print("\n[1] 더미 모드 가드 — 모델 없는 상태에서 재검증을 거부하는가")
ok, clf, why = rc.load_guarded(None, str(Path(tempfile.gettempdir()) / "no_models"))
print(f"  ok={ok}")
print(f"  {why[:150]}")
assert ok is False, "❌ 모델이 없는데 통과시킴"
print("  ✅ 거부됨")

print("\n[2] 마스킹 손상도 — 실제 pii_masker 출력으로 검증")
raw = {
    "ID": "TRAIN_000123",
    "Customer_personal_identifier": "이상호",
    "Customer_identification_number": "BJWQxd-WBASPLJ",
    "IP_Address": "171.237.22.26",
    "MAC_Address": "44:b3:37:b1:2e:ce",
    "Location": "강원도 고성군 죽왕면 38.354486 128.509098",
    "Account_account_number": "oVZASOzgcm",
    "Customer_Birthyear": 1980,
    "Transaction_Amount": 1250000,
    "Channel": "MOBILE",
}
print("  원본 손상도:", rc.mask_damage(raw)["level"])
assert rc.mask_damage(raw)["level"] == "ok"

for lvl in ("basic", "standard", "strict"):
    masked = PIIMasker(level=lvl).mask_row(raw)
    d = rc.mask_damage(masked)
    print(f"  {lvl:9s} → level={d['level']:5s} 훼손={len(d['masked'])} 치명={d['critical']}")

std = PIIMasker(level="standard").mask_row(raw)
d = rc.mask_damage(std)
assert d["level"] == "block", f"❌ standard 마스킹본을 막지 못함: {d['level']}"
print("  ✅ standard 이상 마스킹본은 재검증 차단")
print(f"  차단 사유: {d['message'][:110]}...")

print("\n[3] 실제 마스킹 변환 (왜 치명적인지)")
for k in ("Customer_Birthyear","Account_account_number","IP_Address","Location"):
    print(f"  {k:30s} {str(raw[k]):32s} → {std[k]}")

print("\n[4] 저장본 기반 재검증 — 모델 로드 전에 막히는가")
import sqlite3
con = sqlite3.connect(DB)
con.execute("INSERT OR REPLACE INTO detections VALUES (?,?,?,?,?,?,datetime('now','localtime'),?)",
            ("TXN_MASKED","f",0.72,1,"👁 워처 · lgbm",0.45,
             json.dumps({k:str(v) for k,v in std.items()}, ensure_ascii=False)))
con.commit(); con.close()
r = rc.recheck(DB, "TXN_MASKED", model_dir=str(Path(tempfile.gettempdir()) / "no_models"))
print(f"  ok={r['ok']} blocked={bool(r['blocked'])}")
print(f"  원판정: {r['original'].get('fraud_type')} / {r['original'].get('risk_score')}")
print(f"  손상 level: {r['damage']['level']}")
assert r["blocked"] and r["damage"]["level"]=="block"
print("  ✅ 마스킹 차단이 모델 로드보다 먼저 작동")

print("\n[5] 안전 표시 — 평문 PII 재유입 방어")
sv = rc.safe_view(raw, "standard")
assert sv["Customer_personal_identifier"] == "이○○"
print(f"  이름: {raw['Customer_personal_identifier']} → {sv['Customer_personal_identifier']}")
print(f"  계좌: {raw['Account_account_number']} → {sv['Account_account_number']}")
print(f"  마스킹 컬럼: {rc.masked_field_names('standard')}")
print("  ✅ 방어됨")

print("\n[6] 원본 features 직접 주입 경로")
r2 = rc.recheck(DB, "TXN_MASKED", model_dir=str(Path(tempfile.gettempdir()) / "no_models"), features=raw)
print(f"  손상 level={r2['damage']['level']} · blocked={r2['blocked'][:60]}")
assert r2["damage"]["level"]=="ok"
print("  ✅ 원본 경로는 손상 통과, 모델 가드에서만 막힘")

print("\n"+"="*62); print("✅ 전체 통과")
