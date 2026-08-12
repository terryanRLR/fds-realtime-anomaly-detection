"""selftest_dispatch — ops_dispatch(나가는 통보) + audit_store 자체 검증  ✨ v24 신규

무엇을 지키려는가
  **외부로 나간 것은 회수할 수 없다.** 이 층의 계약은 두 줄이다.

    ① 발송을 시도했으면 **반드시** 기록이 남는다 (성공·실패·예외·미설정 전부)
    ② 그 기록은 새로고침으로 사라지지 않는다

  v24 이전에는 둘 다 깨져 있었다 — 6개 발송 경로 중 4개가 audit_append 를
  빠뜨렸고(복붙 구조), 남은 기록도 세션 메모리에만 있었다.
  send_manual() 이 '보내기와 기록'을 한 함수로 묶어 ①을, notify_audit 테이블이
  ②를 담당한다. 이 테스트는 그 두 계약이 유지되는지만 본다.

⚠️ 운영 DB 를 절대 건드리지 않는다. 네트워크도 쓰지 않는다(가짜 Notifier).

실행:  python -m pipeline.selftest_dispatch
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import audit_store as aust
from pipeline import ops_dispatch as odp

fails: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


class FakeNotifier:
    """실패를 **예외가 아니라 False 로** 돌려주는 실제 Notifier 의 습성까지 흉내낸다."""

    def __init__(self, mode="ok"):
        self.mode, self.last_error = mode, ""

    def _do(self):
        if self.mode == "raise":
            raise RuntimeError("SMTP 연결 끊김")
        if self.mode == "false":
            self.last_error = "웹훅 응답 404"
            return False
        return True

    def send_slack(self, text):
        return self._do()

    def send_email(self, to, subject, body):
        return self._do()


DB = str(Path(tempfile.gettempdir()) / "selftest_dispatch.db")
for suf in ("", "-wal", "-shm"):
    if os.path.exists(DB + suf):
        os.remove(DB + suf)
sqlite3.connect(DB).close()
aust._SCHEMA_DONE.discard(DB)

print("=" * 62)
print("[1] 계약① — 시도했으면 반드시 남는다")
check("처음엔 테이블 없음 (읽기가 테이블을 만들지 않는다)", not aust.table_exists(DB))

for mode, want in (("ok", True), ("false", False), ("raise", False)):
    ss = {"reviewer": "홍길동"}
    ok, err = odp.send_manual(ss, channel="slack", body="x",
                              notifier_factory=lambda m=mode: FakeNotifier(m),
                              fraud_type="f", risk_score=0.9, txn_id=f"T_{mode}",
                              db_path=DB)
    rows = [r for r in aust.recent(DB, limit=50) if r["txn_id"] == f"T_{mode}"]
    check(f"{mode:5s} → 기록 1건 · ok={ok}", len(rows) == 1 and ok is want, f"err={err!r}")
    if rows and not want:
        check(f"  실패 사유가 남는다({mode})", bool(rows[0]["error"]), rows[0]["error"][:40])

print("\n[2] 기록 내용 — 나중에 감사할 수 있는가")
r = [x for x in aust.recent(DB, limit=50) if x["txn_id"] == "T_ok"][0]
for field, want in (("channel", "slack"), ("via", "manual"), ("reviewer", "홍길동")):
    check(f"{field} 보존", r[field] == want, f"{r[field]!r}")
check("시각이 UTC 19자", len(r["sent_at"]) == 19, r["sent_at"])
check("위험도 보존", abs(r["risk_score"] - 0.9) < 1e-9, str(r["risk_score"]))

print("\n[3] 계약② — 세션이 비어도 DB 에서 읽힌다")
fresh: dict = {}
check("세션 사본은 비어 있다", not fresh.get(odp.AUDIT_KEY))
check("★ DB 에는 남아 있다", len(aust.recent(DB, limit=50)) >= 3)
s = aust.stats(DB)
check("통계 집계", s["rows"] >= 3 and s["ok"] >= 1 and s["fail"] >= 2, str(s))

print("\n[4] ⚠️ 감사 기록 실패가 발송을 막지 않는가")
#   주객전도 방지 — 기록이 안 되더라도 통보 자체는 나가야 한다.
ok, _ = odp.send_manual({}, channel="slack", body="x",
                        notifier_factory=lambda: FakeNotifier("ok"),
                        fraud_type="f", risk_score=0.5,
                        db_path="Z:/없는경로/none.db")
check("발송은 성공으로 보고된다", ok is True, str(ok))

print("\n[5] auto_send — '보내지 못한 사건'도 기록되는가")
ss = {"auto_slack": True, "auto_email": True, "dual_threshold": False}
det = {"fraud_type": "f", "risk_score": 0.9, "txn_id": "AUTO_1"}
odp.auto_send(det, ss, notifier_factory=lambda: FakeNotifier("ok"),
              email_resolver=lambda: "",                       # 수신처 미설정
              compose_slack=lambda d, t: "본문", compose_email=lambda d, t: "본문",
              db_path=DB)
rows = [x for x in aust.recent(DB, limit=50) if x["txn_id"] == "AUTO_1"]
check("Slack 성공 + Email 미설정 = 2건", len(rows) == 2,
      str([(x["channel"], x["ok"]) for x in rows]))
em = [x for x in rows if x["channel"] == "email"]
check("수신처 미설정이 실패로 기록", em and not em[0]["ok"] and "미설정" in em[0]["error"],
      em[0]["error"] if em else "없음")

ss2 = {"auto_slack": True, "dual_threshold": False}
det2 = {"fraud_type": "f", "risk_score": 0.9, "txn_id": "AUTO_2"}


def _boom(d, t):
    raise ValueError("템플릿 변수 누락")


odp.auto_send(det2, ss2, notifier_factory=lambda: FakeNotifier("ok"),
              email_resolver=lambda: "a@b.c",
              compose_slack=_boom, compose_email=lambda d, t: "x", db_path=DB)
rows = [x for x in aust.recent(DB, limit=50) if x["txn_id"] == "AUTO_2"]
check("본문 생성 예외도 기록", rows and not rows[0]["ok"],
      rows[0]["error"][:40] if rows else "없음")

print("\n[6] 삭제 — 지우기 전에 몇 건인지 세는가")
con = sqlite3.connect(DB)
for i in range(20):
    con.execute(f"INSERT INTO {aust.TABLE} (sent_at, ok, channel, txn_id, via) "
                f"VALUES (datetime('now','-100 days'),?,?,?,'manual')",
                (1 if i % 4 else 0, "slack", f"OLD_{i}"))
con.commit()
con.close()
n_all = aust.count_matching(DB)
n_old = aust.count_matching(DB, before_days=90)
check("전체 대상 카운트", n_all > n_old, f"전체 {n_all} · 90일이전 {n_old}")
check("90일 이전 20건", n_old == 20, str(n_old))

print("\n[7] 삭제 — 실패 기록 보존 + 삭제 흔적")
n, msg = aust.purge(DB, before_days=90, reviewer="홍길동", keep_failed=True)
check("성공분만 삭제(15건)", n == 15, f"{n}건 · {msg}")
left = aust.recent(DB, limit=200)
check("실패 기록은 남는다",
      sum(1 for x in left if not x["ok"] and str(x["txn_id"]).startswith("OLD_")) == 5)
purges = [x for x in left if x["via"] == "purge"]
check("★ 삭제 사실이 로그에 남는다", len(purges) == 1,
      purges[0]["error"] if purges else "없음")
check("누가 지웠는지 남는다", purges and purges[0]["reviewer"] == "홍길동")
check("삭제 흔적은 다음 삭제 대상에서 제외",
      aust.count_matching(DB) == len([x for x in left if x["via"] != "purge"]),
      str(aust.count_matching(DB)))

n2, _ = aust.purge(DB, before_days=None, reviewer="홍길동")
after = aust.recent(DB, limit=200)
check("전체 삭제 후에도 흔적만 남는다",
      after and all(x["via"] == "purge" for x in after),
      str([x["via"] for x in after]))

print("\n[8] 발송 등급 (notify_tier)")
check("이중 모드 OFF → single", odp.notify_tier({"dual_threshold": False}, 0.99) == "single")
ss = {"dual_threshold": True, "th_review": 0.4, "th_confirm": 0.8}
check("0.9 → confirm", odp.notify_tier(ss, 0.9) == "confirm")
check("0.5 → review", odp.notify_tier(ss, 0.5) == "review")
check("0.1 → none", odp.notify_tier(ss, 0.1) == "none")
bad = {"dual_threshold": True, "th_review": 0.8, "th_confirm": 0.4}   # 2차 < 1차
check("2차<1차 설정 방어", odp.notify_tier(bad, 0.9) == "confirm", odp.notify_tier(bad, 0.9))

for suf in ("", "-wal", "-shm"):
    try:
        os.remove(DB + suf)
    except OSError:
        pass

print("\n" + "=" * 62)
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")
