import os, sys, time, sqlite3, tempfile
from pathlib import Path
# TZ 강제는 POSIX 전용 — Windows CRT 는 IANA 이름을 못 읽어 엉뚱한 오프셋으로 떨어진다.
if hasattr(time, "tzset"):
    os.environ["TZ"]="Asia/Seoul"
    time.tzset()
sys.path.insert(0,'.'); sys.path.insert(0,'pipeline')
from pipeline import ops_alert as oa, ops_queries as oq, review_store as rs

# ⚠️ 예전에는 DB="fds_results.db" 였다. 이 테스트는 경보를 울리려고 transactions 에
#   합성 알림(TXN_NEW_*/TXN_DUP/TXN_BURST_*/TXN_QUIET)을 **INSERT** 하므로,
#   그대로 돌리면 운영 원장에 테스트 행 18건이 영구히 남는다(실제로 그렇게 됐다).
#   자기 소유의 임시 DB를 만들어 쓴다 — 어떤 경우에도 운영 DB를 건드리지 않는다.
DB = str(Path(tempfile.gettempdir()) / "alert_selftest.db")
for _s in ("", "-wal", "-shm"):
    if os.path.exists(DB+_s):
        os.remove(DB+_s)
_con = sqlite3.connect(DB)
_con.execute("""CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT, fraud_type TEXT, risk_score REAL, is_anomaly INTEGER DEFAULT 0,
    input_mode TEXT, true_label TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
# 과거 알림 30건 — [1]의 '첫 폴링은 침묵' 검증에 기준선이 될 행이 필요하다
for _i in range(30):
    _con.execute("INSERT INTO transactions (transaction_id,fraud_type,risk_score,"
                 "is_anomaly,input_mode,processed_at) VALUES (?,?,?,1,'watcher:inbox',"
                 "datetime('now',?))", (f"TXN_OLD_{_i:03d}", "f", 0.9, f"-{_i+1} hours"))
_con.commit(); _con.close()
print(f"임시 DB: {DB} (과거 알림 30건)")

# shared=False — 이 테스트는 **코드 기본값**의 동작(중복억제 30분·버스트 3 등)을
#   검증한다. alarm_prefs.json 은 사용자가 바꾼 값이라, 얹으면 담당자의 설정에 따라
#   테스트가 붙었다 떨어졌다 한다. 실제로 그렇게 깨진 적이 있다.
ss = {}; oa.init_state(ss, shared=False); ss["alarm_on"]=True
print("="*62)

def add(tid, score, ft="f"):
    con=sqlite3.connect(DB)
    # 원장은 UTC 로 쓴다 — datetime('now','localtime') 은 미래 시각으로 기록돼
    #   utc_expr 의 'auto' 휴리스틱이 로컬로 오인식한다(운영 코드와 동일 규칙).
    con.execute("INSERT INTO transactions (transaction_id,fraud_type,risk_score,"
                "is_anomaly,input_mode,processed_at) VALUES (?,?,?,1,'watcher:inbox',"
                "datetime('now'))",(tid,ft,score))
    con.commit(); con.close()

print("\n[1] 최초 폴링 — 과거 알림이 한꺼번에 울리면 안 됨")
a = oa.poll_new(oq, DB, ss)
print(f"  경보 {len(a)}건 · 워터마크={ss['_alarm_seen_id']}")
assert len(a)==0, "❌ 첫 실행에 과거가 울림"
print("  ✅ 침묵 (워터마크만 설정)")

print("\n[2] 새 확정 등급 유입 → 울려야 함")
add("TXN_NEW_A", 0.91)
a = oa.poll_new(oq, DB, ss)
print(f"  경보 {len(a)}건: {[(x['txn_id'],x['risk_score'],x['tier']) for x in a]}")
assert len(a)==1 and a[0]["tier"]=="confirm"
print("  ✅ 울림")

print("\n[3] 같은 폴링 재호출 → 중복 안 울림")
assert len(oa.poll_new(oq, DB, ss))==0
print("  ✅ 워터마크 동작")

print("\n[4] 등급 필터 — confirm 설정에서 review(0.45~0.80)는 무시")
add("TXN_NEW_B", 0.55)
a = oa.poll_new(oq, DB, ss)
print(f"  confirm 모드 경보 {len(a)}건")
assert len(a)==0, "❌ review 가 새어나옴"
ss["alarm_tier"]="review"; add("TXN_NEW_C", 0.55)
a = oa.poll_new(oq, DB, ss)
print(f"  review 모드 경보 {len(a)}건 → {[x['tier'] for x in a]}")
assert len(a)==1
print("  ✅ 등급 필터 동작")

print("\n[5] 중복 억제 — 같은 거래 재유입")
ss["alarm_tier"]="confirm"
add("TXN_DUP", 0.95); a=oa.poll_new(oq,DB,ss); print(f"  1차: {len(a)}건")
add("TXN_DUP", 0.95); b=oa.poll_new(oq,DB,ss); print(f"  2차: {len(b)}건 (dedup {ss['alarm_dedup_min']}분)")
assert len(a)==1 and len(b)==0
print("  ✅ 억제됨")

print("\n[6] 버스트 제한 — 대량 유입 시 100번 울리지 않는가")
for i in range(12): add(f"TXN_BURST_{i}", 0.85+i*0.005)
a = oa.poll_new(oq, DB, ss)
print(f"  12건 유입 → 경보 {len(a)}건 (상한 {ss['alarm_max_burst']})")
assert len(a)==ss["alarm_max_burst"]
print(f"  ✅ 상위 {len(a)}건만 · 점수 내림차순 {[round(x['risk_score'],3) for x in a]}")

print("\n[7] 조용한 시간대")
h = time.localtime().tm_hour
ss["alarm_quiet_from"]=h; ss["alarm_quiet_to"]=(h+1)%24
add("TXN_QUIET", 0.99)
a = oa.poll_new(oq, DB, ss)
print(f"  현재 {h}시, 무음 {h}~{(h+1)%24}시 → 경보 {len(a)}건")
assert len(a)==0
ss["alarm_quiet_from"]=0; ss["alarm_quiet_to"]=0
print("  ✅ 무음")

print("\n[8] 소음 예보 — 켜기 전에 대가를 보여주는가")
for tier in ("confirm","review","all"):
    ss["alarm_tier"]=tier
    f = oa.noise_forecast(oq, rs, DB, ss, hours=168)
    print(f"  {tier:8s} → {f['per_day']:5.1f}회/일 · 오탐률 "
          f"{f['fp_rate']*100 if f['fp_rate'] is not None else 0:.0f}% · "
          f"헛알람 {f['wasted']}회/일")
print("  ✅ 등급별 소음량 산출")

print("\n[9] 렌더 산출물 검증")
class FakeSt:
    class components:
        class v1:
            @staticmethod
            def html(h, height=0): FakeSt.last=h
    last=""
import ops_ui as ui
oa.render(FakeSt, [{"txn_id":"TXN_X","risk_score":0.93,"fraud_type":"f",
                    "tier":"confirm","시각":"2026-08-06 16:00:00","source":"watcher"}],
          ss, ui.get_theme("amber"), ui.fraud_label, "ko")
h = FakeSt.last
for chk, name in [("window.parent","부모 DOM 탈출"),("opsRadarSweep","레이더 SVG"),
                  ("prefers-reduced-motion","접근성"),("createOscillator","사이렌"),
                  ("Notification","데스크톱 알림"),("searchParams.set","딥링크"),
                  ("exponentialRampToValueAtTime","클릭노이즈 방지")]:
    print(f"  {'✅' if chk in h else '❌'} {name}")
    assert chk in h
print(f"  페이로드 길이 {len(h):,}자")

print("\n"+"="*62); print("✅ 전체 통과")
