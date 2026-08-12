"""selftest_preprocessor — Preprocessor / RawRowClassifier 자체 검증  ✨ v24 신규

무엇을 지키려는가

  ① **`predict_batch` == `predict`** — 배치가 단건과 다른 답을 내면 안 된다.
     `pd.DataFrame(리스트)` 는 열의 **합집합**을 만들어서, 키 구성이 다른 행을
     한꺼번에 넣으면 없는 값이 기본값이 아니라 NaN 이 되고 `_derive()` 도
     없어야 할 파생을 켠다. 실측(v24): 같은 행이 단건 0.1839 · 배치 0.9932.
     → 키 구성별로 묶어 변환하는 것으로 해결했고, 이 테스트가 그 계약을 지킨다.

  ② **`Location_region` 17개 시도 매핑** — 모델이 학습한 정수 코드다.
     시도 이름 목록을 한 줄만 건드려도 코드가 밀리는데, 에러 없이 **예측만
     조용히 틀어진다.** 매핑은 명시적으로 못박혀 있어야 한다(v24 실측 확정).

모델·데이터가 없는 환경에서는 해당 항목을 **건너뛴다**(실패로 세지 않는다).

실행:  python -m pipeline.selftest_preprocessor
"""
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from pipeline.preprocessor import (REGION_ALIASES, REGION_MAP_DEFAULT, SIDO_LEVELS,
                                   Preprocessor)

fails: list[str] = []
skips: list[str] = []


def check(name: str, cond, detail: str = ""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def skip(name: str, why: str):
    print(f"  ⏭  {name} — 건너뜀 ({why})")
    skips.append(name)


print("=" * 62)
print("[1] Location_region — 매핑이 못박혀 있는가")
check("17종", len(REGION_MAP_DEFAULT) == 17, str(len(REGION_MAP_DEFAULT)))
check("코드 0~16 · 중복 없음",
      sorted(REGION_MAP_DEFAULT.values()) == list(range(17)))
check("SIDO_LEVELS 가 코드 순서", list(REGION_MAP_DEFAULT) == SIDO_LEVELS)
# v24 실측(train.csv × X_tr.parquet 94,006행)으로 확정된 값 — 바뀌면 예측이 틀어진다
for name, code in (("강원도", 0), ("경기도", 1), ("경상남도", 2), ("경상북도", 3),
                   ("서울특별시", 8), ("제주특별자치도", 14), ("충청북도", 16)):
    check(f"{name} = {code}", REGION_MAP_DEFAULT.get(name) == code,
          str(REGION_MAP_DEFAULT.get(name)))
check("개편 명칭 별칭 흡수(강원특별자치도→강원도)",
      REGION_ALIASES.get("강원특별자치도") == "강원도")

MODELS = Path("models")
if not (MODELS / "feature_cols.json").exists():
    skip("[2~4] 번들 기반 검증", f"{MODELS}/feature_cols.json 없음")
else:
    prep = Preprocessor.from_bundle(str(MODELS))

    print("\n[2] 시도 인코딩")
    s = pd.Series([f"{n} 어딘가" for n in SIDO_LEVELS])
    enc = prep._encode_region(s)
    check("17개가 서로 다른 코드", len(set(enc.dropna())) == 17, str(sorted(set(enc.dropna()))))
    check("NaN 없음", not enc.isna().any())
    unknown = prep._encode_region(pd.Series(["화성시 어딘가"]))
    check("미등록 시도에서 죽지 않는다", len(unknown) == 1)

    print("\n[3] transform — 누락 컬럼은 기본값으로 채운다")
    row = {"Transaction_Amount": -1_000_000, "Account_balance": 5_000_000,
           "Channel": "ATM"}
    X = prep.transform_row(row)
    check("피처 수가 계약과 일치", list(X.columns) == prep.feature_cols,
          f"{len(X.columns)} vs {len(prep.feature_cols)}")
    check("결측 없이 채워진다", not X.isna().any().any(),
          str([c for c in X.columns if X[c].isna().any()][:4]))

    # ⚠️ 모델은 **정식 resolver** 로 고른다. glob 으로 아무 pkl 이나 집으면
    #   로드에 실패해 MLClassifier 가 조용히 **더미 모드(15% 랜덤 판정)** 로 떨어지고,
    #   그러면 "1행 배치 != 단건" 같은 불가능한 결과가 나온다(실제로 겪었다).
    from pipeline.bundle_io import resolve_model_path
    model_path = resolve_model_path(MODELS)
    base = {"Transaction_Amount": -85_000_000, "Distance": 480,
            "Account_balance": 120_000_000, "Channel": "ATM",
            "Operating_System": "Others", "Customer_Gender": "male"}
    clf = None
    if model_path is None:
        skip("[4] predict_batch 불변식", "번들 모델을 찾지 못함")
    else:
        from pipeline import detect_io as dio
        _c, _mode, _ = dio.resolve_classifier(str(model_path), base)
        # 더미 모드면 예측이 매번 달라 이 검증 자체가 성립하지 않는다 → 건너뛴다
        if _c.predict(base)[:2] != _c.predict(base)[:2]:
            skip("[4] predict_batch 불변식",
                 f"모델이 비결정적(더미 모드로 추정) · mode={_mode[0]}")
        else:
            clf = _c

    if clf is not None:
        print("\n[4] ★ predict_batch == predict (키 구성이 달라도)")

        def agree(rows, label):
            single = [clf.predict(r) for r in rows]
            batch = clf.predict_batch(rows)
            same_t = all(s[0] == b[0] for s, b in zip(single, batch))
            same_r = np.allclose([s[1] for s in single], [b[1] for b in batch],
                                 atol=1e-12)
            check(label, same_t and same_r,
                  "" if same_t and same_r else
                  f"단건 {[round(s[1], 4) for s in single][:3]} vs "
                  f"배치 {[round(b[1], 4) for b in batch][:3]}")

        # 예전에 실제로 깨지던 조합: 한쪽에만 있는 키
        r2 = dict(base)
        r2["Account_one_month_max_amount"] = 16_470_000.0
        agree([base, r2], "키 구성이 다른 두 행")
        agree([r2, base], "역순으로 넣어도 동일")

        random.seed(11)
        pool = []
        for _ in range(30):
            r = dict(base)
            r["Transaction_Amount"] = random.choice([-4e8, -8.5e7, 1e6])
            for k in random.sample(list(r), random.randint(0, 3)):
                r.pop(k)
            pool.append(r)
        agree(pool, f"무작위 이질 행 30개 (그룹 {len({frozenset(r) for r in pool})}개)")

        check("빈 리스트 안전", clf.predict_batch([]) == [])
        one = clf.predict_batch([base])
        check("1행 배치 == 단건", abs(one[0][1] - clf.predict(base)[1]) < 1e-12)

        # 동질 행이면 그룹이 하나뿐이라 속도 이점이 유지되어야 한다
        same = [dict(base) for _ in range(50)]
        check("동질 50행은 그룹 1개", len({frozenset(r) for r in same}) == 1)

TRAIN, XTR = Path("data/train.csv"), Path("data/X_tr.parquet")
if not (TRAIN.exists() and XTR.exists()):
    skip("[5] 원본 대조 재학습", "data/train.csv 또는 X_tr.parquet 없음")
elif not (MODELS / "feature_cols.json").exists():
    skip("[5] 원본 대조 재학습", "번들 없음")
else:
    print("\n[5] 원본 × 산출물 대조 — 58피처가 팀 산출물과 일치하는가 (느림)")
    prep = Preprocessor.from_bundle(str(MODELS))
    before = dict(prep.region_map)
    rep = prep.learn_from_pair(pd.read_csv(TRAIN), pd.read_parquet(XTR))
    after = dict(prep.region_map)
    diff = {k: (before.get(k), after.get(k)) for k in after if before.get(k) != after.get(k)}
    check("★ 시도 매핑을 교정할 것이 없다", not diff, str(diff))
    check("리포트가 '일치'로 기록", "일치" in prep.learned.get("Location_region", ""),
          prep.learned.get("Location_region", ""))

    # v24: 음수 경과시간을 NaN 으로 맞추면서 58피처 전부 100% 가 됐다.
    #   여기가 다시 내려가면 전처리 공식이 팀 산출물과 어긋났다는 뜻이다.
    worst = sorted(rep.items(), key=lambda kv: kv[1])[:3]
    check("★ 58피처 전부 99.9% 이상 일치",
          all(v >= 99.9 for v in rep.values()),
          " · ".join(f"{k} {v}%" for k, v in worst))
    check("Time_difference_seconds 100% (음수 경과시간 → NaN)",
          rep.get("Time_difference_seconds", 0) == 100.0,
          str(rep.get("Time_difference_seconds")))

print("\n" + "=" * 62)
if skips:
    print(f"⏭  건너뜀 {len(skips)}건: {skips}")
if fails:
    print(f"❌ 실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("✅ 전체 통과")
