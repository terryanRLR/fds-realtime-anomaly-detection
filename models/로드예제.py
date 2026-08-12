# -*- coding: utf-8 -*-
"""배포 번들 로드/추론 예제."""
import json, joblib
import pandas as pd
from pathlib import Path
D = Path(__file__).parent
model = joblib.load(D/"lgbm_13class.pkl")
le_tgt = joblib.load(D/"le_target.pkl")
feat = json.load(open(D/"feature_cols.json", encoding="utf-8"))
defaults = json.load(open(D/"feature_defaults.json", encoding="utf-8"))

def prepare(df):
    df = df.copy()
    for c in ["is_fraud", "fraud_type", "label", "y"]:
        if c in df.columns: df = df.drop(columns=[c])
    for c in feat:
        if c not in df.columns: df[c] = defaults[c]
        df[c] = df[c].fillna(defaults[c])
    return df[feat]

def predict(df):
    X = prepare(df)
    idx = model.predict(X)
    return idx, le_tgt.inverse_transform(idx)   # 'a'~'m' (m=정상)
