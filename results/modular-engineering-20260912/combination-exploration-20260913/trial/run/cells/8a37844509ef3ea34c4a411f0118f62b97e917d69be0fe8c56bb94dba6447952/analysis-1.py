import os
import re
import numpy as np
import pandas as pd

PATH = "/input/public_csv"

def find_file(path):
    if os.path.isfile(path):
        return path
    candidates = [os.path.join("/input", f) for f in os.listdir("/input")]
    csvs = [f for f in candidates if f.lower().endswith(".csv")]
    if not csvs:
        raise FileNotFoundError("No CSV file found in /input")
    return csvs[0]

def num(df, col):
    return pd.to_numeric(df[col], errors="coerce")

def fmt(x):
    return "NA" if pd.isna(x) else f"{x:.3f}"

file_path = find_file(PATH)
df = pd.read_csv(file_path)

outcome = "percentage_increase_in_utilitarianism"
needed = [
    outcome, "argument_intensity", "moderator_ethical_stance",
    "audience_interest_level", "average_debate_duration",
    "number_of_sessions", "critical_event_occurred"
]
missing = [c for c in needed if c not in df.columns]
if missing:
    print("Missing required columns: " + ", ".join(missing))
else:
    text_cols = [c for c in ["topic_of_debate", "philosophical_topic"] if c in df.columns]
    ethics = df.copy()
    if text_cols:
        text = ethics[text_cols].fillna("").astype(str).agg(" ".join, axis=1)
        mask = text.str.contains(r"ethic", case=False, regex=True)
        if mask.any():
            ethics = ethics.loc[mask].copy()

    y = num(ethics, outcome)
    print(f"Ethics-focused rows: {len(ethics)}; usable outcome rows: {y.notna().sum()}")
    if y.notna().any():
        print(f"Outcome mean={fmt(y.mean())}, median={fmt(y.median())}, range={fmt(y.min())} to {fmt(y.max())}")

    numeric = ["argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions"]
    for col in numeric:
        x = num(ethics, col)
        valid = pd.concat([x, y], axis=1).dropna()
        corr = valid.iloc[:, 0].corr(valid.iloc[:, 1]) if len(valid) >= 3 else np.nan
        print(f"Correlation outcome vs {col}: r={fmt(corr)} (n={len(valid)})")

    for col in ["moderator_ethical_stance", "critical_event_occurred"]:
        temp = pd.DataFrame({"group": ethics[col].astype(str), "outcome": y}).dropna()
        if not temp.empty:
            means = temp.groupby("group")["outcome"].agg(["mean", "count"]).sort_values("mean", ascending=False)
            summary = "; ".join(f"{idx}: mean={fmt(row['mean'])}, n={int(row['count'])}" for idx, row in means.iterrows())
            print(f"Outcome by {col}: {summary}")

    reg_cols = numeric + ["moderator_ethical_stance", "critical_event_occurred"]
    reg = ethics[reg_cols + [outcome]].copy()
    reg[outcome] = pd.to_numeric(reg[outcome], errors="coerce")
    for col in numeric:
        reg[col] = pd.to_numeric(reg[col], errors="coerce")
    reg = pd.get_dummies(reg, columns=["moderator_ethical_stance", "critical_event_occurred"], drop_first=True, dtype=float).dropna()
    if len(reg) >= max(8, len(reg.columns) + 2):
        X = reg.drop(columns=[outcome]).astype(float)
        X = (X - X.mean()) / X.std(ddof=0).replace(0, 1)
        X = np.column_stack([np.ones(len(X)), X.to_numpy()])
        b = np.linalg.lstsq(X, reg[outcome].to_numpy(), rcond=None)[0]
        pred = X @ b
        r2 = 1 - ((reg[outcome].to_numpy() - pred) ** 2).sum() / ((reg[outcome].to_numpy() - reg[outcome].mean()) ** 2).sum()
        labels = ["intercept"] + list(reg.drop(columns=[outcome]).columns)
        ranked = sorted(zip(labels[1:], b[1:]), key=lambda z: abs(z[1]), reverse=True)[:5]
        print("Standardized regression top effects: " + "; ".join(f"{k}={v:.3f}" for k, v in ranked))
        print(f"Regression R2={fmt(r2)}, n={len(reg)}")
    else:
        print("Regression skipped: insufficient complete observations.")