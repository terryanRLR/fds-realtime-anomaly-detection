"""
threshold_report — 임계값 실측 · 기대비용 분석 리포트  ✨ v19

v18 → v19 변경 (팀 비용분석 반영)
  🐛 **탐색 범위 결함 수정** — 기존 스윕은 0.05~1.00(0.05 간격)이었다.
     그런데 실제 의사결정 구간은 **0.05 아래**였고, 최적값 0.005는 격자 밖이었다.
     게다가 권장 로직이 고른 0.05는 스윕의 **경계값**이었다 — 최적점이 경계에
     붙으면 "범위 밖에 더 좋은 값이 있다"는 신호인데 놓쳤다.
     → 0.0001부터 로그 간격으로 훑도록 변경.
  ✨ **기대비용 분석 추가** — Macro-F1만으로는 운영 판단을 할 수 없다.
     미탐(FN)과 오탐(FP)은 성격이 다른 비용을 만든다.
       기대비용 = FN건수 × FN단가 + FP건수 × FP단가
  ✨ **제약 하 최적화** — 순수 비용최소는 임계값을 0 근처로 밀어버려 모델이 붕괴한다
     (전량 의심처리 = FN 0이지만 FP 폭증). 그래서 Macro-F1 하한을 제약으로 걸고
     그 안에서 비용을 최소화한다.
  ✨ **유형별 실제 피해액** — 고정 FN단가는 유형에 따라 오차가 크다.
     거래금액 컬럼이 있으면 실제 금액 기준 비용도 함께 계산한다.

판정 규칙 (팀 분석과 동일)
  위험점수 = 1 − P(정상)
  risk ≥ 임계값 → 예측 = argmax(유형)   /   risk < 임계값 → 예측 = 정상
  ※ 위험점수가 0.5를 넘어야 argmax가 사기 유형이 되므로,
     임계값 0.5 이하 구간에서는 이 규칙과 '유형이 사기면 승격' 규칙이 동일하다.

사용법
  python -m tools.threshold_report
  python -m tools.threshold_report --fn-cost 1700 --fp-cost 5 --min-macro-f1 0.6
  python -m tools.threshold_report --daily 300
"""

from __future__ import annotations

import sys
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 🐛 FIX(v19): 저구간을 촘촘히. 의사결정은 0.05 아래에서 일어난다.
SWEEP = [0.0, 0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.008,
         0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0]

DUAL_COMBOS = [(0.001, 0.5), (0.003, 0.7), (0.005, 0.8), (0.005, 0.9),
               (0.01, 0.9), (0.03, 0.9), (0.05, 0.9), (0.1, 0.9)]

DEFAULT_FN_COST = 1700.0     # 만원 — 보이스피싱 건당 평균 피해액
DEFAULT_FP_COST = 5.0        # 만원 — 오탐 1건 대응비용(고객 불편·검토), 보수적 상한
DEFAULT_MIN_F1 = 0.6         # Macro-F1 하한 (model_meta 기준선 0.6138 유지)

AMOUNT_COLS = ("Transaction_Amount", "Transaction_amount", "transaction_amount")


def _load_current_config() -> dict:
    try:
        from pipeline import watcher_config as wcfg
        return wcfg.load()
    except Exception:
        return {}


def _infer(models_dir: str, x_path: str, y_path: str):
    """워처와 동일한 경로로 추론."""
    from pipeline.preprocessor import RawRowClassifier

    clf = RawRowClassifier.from_bundle(models_dir)
    if getattr(clf, "model", None) is None:
        raise RuntimeError("모델을 불러오지 못했습니다 — python -m tools.verify_bundle 로 먼저 확인하세요")

    X = (pd.read_parquet(x_path) if str(x_path).endswith((".parquet", ".pq"))
         else pd.read_csv(x_path))
    y_raw = (pd.read_parquet(y_path) if str(y_path).endswith((".parquet", ".pq"))
             else pd.read_csv(y_path))

    classes = [str(c) for c in (clf.classes_ or [])]
    normal = str(getattr(clf, "normal_label", "m"))

    y = y_raw[y_raw.columns[0]].to_numpy()
    if np.issubdtype(np.asarray(y).dtype, np.number):
        if not classes:
            raise RuntimeError("정수 라벨인데 클래스 목록이 없습니다 (model_meta.json 확인)")
        y_true = np.array([classes[int(v)] for v in y])
    else:
        y_true = np.asarray(y).astype(str)
    if len(y_true) != len(X):
        raise RuntimeError(f"X({len(X)}행)와 y({len(y_true)}행)의 행 수가 다릅니다")

    Xp = clf.prep.transform(X)
    P = np.asarray(clf.model.predict_proba(Xp))
    mi = classes.index(normal) if normal in classes else None
    risk = (1.0 - P[:, mi]) if mi is not None else P.max(axis=1)

    # ⚠️ 유형은 '정상을 제외한' 확률 최댓값이어야 한다.
    #   위험점수가 0.5 미만이면 전체 argmax 는 언제나 정상이므로,
    #   전체 argmax 를 쓰면 임계값을 아무리 낮춰도 사기로 잡히지 않는다
    #   (임계값이 무의미해지는 버그). 임계값은 '사기로 볼지'를 정하고,
    #   유형은 '사기라면 어느 유형인지'를 정하는 별개의 판단이다.
    Pf = P.copy()
    if mi is not None:
        Pf[:, mi] = -np.inf
    pred_type = (np.array([classes[i] for i in Pf.argmax(1)]) if classes
                 else np.array([str(i) for i in Pf.argmax(1)]))

    # 유형별 실제 피해액용 거래금액 (있을 때만)
    amounts = None
    for c in AMOUNT_COLS:
        if c in X.columns:
            amounts = pd.to_numeric(X[c], errors="coerce").fillna(0).to_numpy(float)
            break

    name = "model"
    for attr in ("model_path", "path", "_model_path"):
        v = getattr(clf, attr, None)
        if v:
            name = Path(str(v)).name
            break
    return y_true, risk, pred_type, normal, classes, amounts, name


def _eval_at(th, y_true, risk, pred_type, normal, classes, amounts,
             fn_cost, fp_cost):
    """임계값 하나에 대한 전체 지표."""
    from sklearn.metrics import f1_score

    pred = np.where(risk >= th, pred_type, normal)
    is_fraud = (y_true != normal)
    flagged = (pred != normal)

    tp = int((is_fraud & flagged).sum())
    fn = int((is_fraud & ~flagged).sum())
    fp = int((~is_fraud & flagged).sum())
    n_alert = tp + fp
    recall = tp / max(1, int(is_fraud.sum()))
    prec = tp / n_alert if n_alert else 0.0
    macro = f1_score(y_true, pred, average="macro",
                     labels=classes or None, zero_division=0)

    cost = (fn * fn_cost + fp * fp_cost) / 10000.0          # 억원
    cost_real = None
    if amounts is not None:
        miss = is_fraud & ~flagged
        cost_real = (float(amounts[miss].sum()) / 1e8) + (fp * fp_cost / 10000.0)

    return {"th": th, "alerts": n_alert, "tp": tp, "fn": fn, "fp": fp,
            "recall": recall, "precision": prec, "macro_f1": float(macro),
            "cost": cost, "cost_real": cost_real}


def run(x_path="data/X_va.parquet", y_path="data/y_va.parquet",
        models_dir="models/", daily=300, fn_cost=DEFAULT_FN_COST,
        fp_cost=DEFAULT_FP_COST, min_f1=DEFAULT_MIN_F1, save=True):

    y_true, risk, pred_type, normal, classes, amounts, model_name = _infer(
        models_dir, x_path, y_path)

    n_total = len(y_true)
    is_fraud = (y_true != normal)
    n_fraud = int(is_fraud.sum())
    cur = _load_current_config()
    cur_r = float(cur.get("th_review", 0.005))
    cur_c = float(cur.get("th_confirm", 0.90))

    lines: list[str] = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 104)
    out(f" 임계값 실측 · 기대비용 리포트 — {Path(x_path).name}")
    out(f" 모델 {model_name} · {n_total:,}행 · 사기 {n_fraud:,}건 ({n_fraud/n_total:.2%})")
    out(f" 비용 가정 : 미탐 1건 {fn_cost:,.0f}만원 · 오탐 1건 {fp_cost:,.0f}만원"
        + (" · 거래금액 컬럼 감지 → 실제 피해액도 계산" if amounts is not None else ""))
    out(f" 제약      : Macro-F1 ≥ {min_f1}   (모델 기준선 유지)")
    out(f" 현재 설정 : review {cur_r} / confirm {cur_c} · 하루 유입 {daily:,}건 가정")
    out("=" * 104)

    rows = [_eval_at(th, y_true, risk, pred_type, normal, classes, amounts,
                     fn_cost, fp_cost) for th in SWEEP]
    df = pd.DataFrame(rows)
    df["daily"] = df["alerts"] / n_total * daily

    # ── [1] 스윕 ──
    out("")
    out(" [1] 임계값 스윕   (risk ≥ 임계값 → 사기 유형 예측 · 미만 → 정상)")
    out("-" * 104)
    hdr = (f" {'임계값':>8} {'알림':>7} {'적중':>6} {'미탐':>6} {'오탐':>7}"
           f" {'재현율':>8} {'정밀도':>8} {'MacroF1':>9} {'기대비용':>10} {'하루알림':>9}")
    if amounts is not None:
        hdr += f" {'실제비용':>10}"
    out(hdr)
    out("-" * 104)
    for _, r in df.iterrows():
        mk = ""
        if abs(r["th"] - cur_r) < 1e-9:
            mk = "  ← 현재"
        bad = "" if r["macro_f1"] >= min_f1 else "  ✗제약"
        line = (f" {r['th']:>8.4f} {int(r['alerts']):>7,} {int(r['tp']):>6,} "
                f"{int(r['fn']):>6,} {int(r['fp']):>7,}"
                f" {r['recall']:>7.1%} {r['precision']:>7.1%} {r['macro_f1']:>9.4f}"
                f" {r['cost']:>9.2f}억 {r['daily']:>8.1f}건")
        if amounts is not None and r["cost_real"] is not None:
            line += f" {r['cost_real']:>9.2f}억"
        out(line + mk + bad)
    out("-" * 104)

    # ── [2] 순수 비용최소의 함정 ──
    lo = df.loc[df["cost"].idxmin()]
    out("")
    out(" [2] 순수 비용최소화의 함정")
    out("-" * 104)
    out(f"   비용만 최소화하면 → 임계값 {lo['th']:.4f} · 비용 {lo['cost']:.2f}억 · "
        f"Macro-F1 {lo['macro_f1']:.4f}")
    if lo["macro_f1"] < min_f1:
        out(f"   그러나 Macro-F1 {lo['macro_f1']:.3f} < {min_f1} → **기각**. "
            f"임계값을 0 근처로 내리면 전량 의심처리가 되어 모델이 붕괴한다.")
    z = df[df["th"] == 0.0]
    if not z.empty:
        z = z.iloc[0]
        out(f"   참고: 임계값 0(전량 의심처리) → 비용 {z['cost']:.2f}억 · "
            f"Macro-F1 {z['macro_f1']:.4f} — 오탐 폭증으로 비용도 오히려 증가")
    out("-" * 104)

    # ── [3] 제약 하 최적화 ──
    ok = df[df["macro_f1"] >= min_f1]
    out("")
    out(f" [3] 제약 하 최적화   (Macro-F1 ≥ {min_f1} 안에서 기대비용 최소)")
    out("-" * 104)
    if ok.empty:
        out(f"   Macro-F1 {min_f1} 이상인 임계값이 없습니다. 제약을 낮추거나 모델을 개선하세요.")
        best = None
    else:
        best = ok.loc[ok["cost"].idxmin()]
        peak = df.loc[df["macro_f1"].idxmax()]
        out(f"   ★ 채택 권고 : 임계값 {best['th']:.4f}")
        out(f"                 Macro-F1 {best['macro_f1']:.4f} · 기대비용 {best['cost']:.2f}억 · "
            f"하루 알림 {best['daily']:.1f}건")
        out(f"                 사기 {int(best['tp'])}건 탐지 / 미탐 {int(best['fn'])}건 · "
            f"오탐 {int(best['fp'])}건")
        out(f"   비교 성능최고점 : 임계값 {peak['th']:.4f} · Macro-F1 {peak['macro_f1']:.4f} · "
            f"비용 {peak['cost']:.2f}억  (비용 {peak['cost']-best['cost']:+.2f}억)")
        curr = df.iloc[(df["th"] - cur_r).abs().argmin()]
        if abs(curr["th"] - best["th"]) > 1e-9:
            out(f"   현재 설정({curr['th']:.4f}) 대비 : 비용 {curr['cost']:.2f}억 → "
                f"{best['cost']:.2f}억 ({best['cost']-curr['cost']:+.2f}억) · "
                f"미탐 {int(curr['fn'])} → {int(best['fn'])}건 · "
                f"하루 알림 {curr['daily']:.1f} → {best['daily']:.1f}건")
    out("-" * 104)

    # ── [4] 견고성 — FP 단가 손익분기 ──
    if best is not None:
        out("")
        out(" [4] 결론의 견고성   (FP 단가가 얼마나 비싸야 결론이 뒤집히나)")
        out("-" * 104)
        flipped = False
        for _, r in ok.iterrows():
            if r["th"] <= best["th"] or r["fp"] >= best["fp"]:
                continue
            d_fn, d_fp = best["fn"] - r["fn"], best["fp"] - r["fp"]
            if d_fp <= 0:
                continue
            be = (-d_fn) * fn_cost / d_fp
            if be > 0:
                out(f"   임계값 {r['th']:.4f} 이 이기려면 오탐 1건이 {be:,.0f}만원이어야 함 "
                    f"(가정의 {be/max(fp_cost,1e-9):,.0f}배)")
                flipped = True
                break
        if not flipped:
            out("   가정을 흔들어도 채택값이 뒤집히지 않습니다.")
        near = ok[(ok["cost"] - best["cost"]).abs() < fn_cost * 5 / 10000.0]
        if len(near) > 1:
            ths = ", ".join(f"{v:.4f}" for v in near["th"])
            out(f"   ⚠️ 비용 차이가 미탐 5건 이내인 임계값: {ths}")
            out(f"      표본 사기 {n_fraud}건 기준 이 정도 차이는 분산 범위일 수 있습니다 "
                f"— 단정하지 말고 신뢰구간 확인을 권장합니다.")
        out("-" * 104)

    # ── [5] 유형별 실제 피해액 ──
    if amounts is not None:
        out("")
        out(" [5] 유형별 평균 거래금액 (고정 FN단가 가정의 한계 점검)")
        out("-" * 104)
        s = pd.Series(amounts[is_fraud], index=y_true[is_fraud])
        avg = s.groupby(level=0).mean().sort_values(ascending=False)
        for t, v in avg.items():
            bar = "█" * max(1, int(v / max(avg.max(), 1) * 28))
            out(f"   {t}형 {v/10000:>8,.0f}만원  {bar}")
        out(f"   최고/최저 비율 {avg.max()/max(avg.min(),1):.1f}배 — "
            f"유형 구분 없는 고정 단가는 임계값이 낮아질수록 오차가 커집니다.")
        out("-" * 104)

    # ── [6] 이중 임계값 ──
    out("")
    out(" [6] 이중 임계값 조합   (1차 → Slack만 · 2차 → Slack+Email)")
    out("-" * 104)
    out(f" {'review':>8} {'confirm':>9} | {'Slack/일':>10} {'Email/일':>10} |"
        f" {'재현율':>8} {'미탐':>6} {'MacroF1':>9}")
    out("-" * 104)
    for th_r, th_c in sorted(set(DUAL_COMBOS) | {(round(cur_r, 4), round(cur_c, 4))}):
        t2 = max(th_r, th_c)
        a = _eval_at(th_r, y_true, risk, pred_type, normal, classes, amounts, fn_cost, fp_cost)
        b = _eval_at(t2, y_true, risk, pred_type, normal, classes, amounts, fn_cost, fp_cost)
        mk = "  ← 현재" if (abs(th_r - cur_r) < 1e-9 and abs(th_c - cur_c) < 1e-9) else ""
        out(f" {th_r:>8.4f} {th_c:>9.4f} | {a['alerts']/n_total*daily:>9.1f}건"
            f" {b['alerts']/n_total*daily:>9.1f}건 |"
            f" {a['recall']:>7.1%} {a['fn']:>6,} {a['macro_f1']:>9.4f}{mk}")
    out("-" * 104)

    out("")
    out(" 해석 주의")
    out("   · 검증셋(과거 데이터) 기준입니다. 실제 유입의 사기 비율이 다르면 하루 알림도 달라집니다.")
    out("   · Macro-F1 하한은 '모델 성능을 기준선 아래로 떨어뜨리지 않는다'는 정책 결정입니다.")
    out("     이 값을 낮추면 더 싼 임계값이 선택되므로, 근거를 문서에 남겨야 합니다.")
    out("   · 임계값을 낮추면 유형 특정 정확도는 함께 떨어집니다 — 유형은 참고용으로 안내하세요.")
    out("")
    out(" 적용 : watcher_config.json 의 th_review 수정 (재시작 불필요, 5초 내 반영)")
    out("        또는 대시보드 세션5 → 워처 상태 → 설정")
    out("=" * 104)

    if save:
        try:
            df.to_csv("threshold_report.csv", index=False, encoding="utf-8-sig")
            Path("threshold_report.txt").write_text("\n".join(lines), encoding="utf-8")
            print("\n 저장: threshold_report.csv · threshold_report.txt")
        except Exception as e:
            print(f"\n [!] 파일 저장 실패: {e}")

    return df


def main():
    ap = argparse.ArgumentParser(description="임계값 실측 · 기대비용 리포트")
    ap.add_argument("--x", default="data/X_va.parquet")
    ap.add_argument("--y", default="data/y_va.parquet")
    ap.add_argument("--models", default="models/")
    ap.add_argument("--daily", type=int, default=300, help="하루 평균 유입 건수")
    ap.add_argument("--fn-cost", type=float, default=DEFAULT_FN_COST,
                    help=f"미탐 1건 비용(만원, 기본 {DEFAULT_FN_COST:,.0f})")
    ap.add_argument("--fp-cost", type=float, default=DEFAULT_FP_COST,
                    help=f"오탐 1건 비용(만원, 기본 {DEFAULT_FP_COST:,.0f})")
    ap.add_argument("--min-macro-f1", type=float, default=DEFAULT_MIN_F1,
                    help=f"Macro-F1 하한 제약 (기본 {DEFAULT_MIN_F1})")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    try:
        run(a.x, a.y, a.models, a.daily, a.fn_cost, a.fp_cost,
            a.min_macro_f1, save=not a.no_save)
    except FileNotFoundError as e:
        print(f"파일을 찾지 못했습니다: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"{type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
