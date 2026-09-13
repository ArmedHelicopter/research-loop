import os
import re
import numpy as np
import pandas as pd

PATH = "/input/public_csv"

def read_csv(path):
    candidates = [path]
    if os.path.isdir(path):
        candidates = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".csv")]
    if not candidates:
        raise FileNotFoundError("No CSV found at /input/public_csv")
    return pd.read_csv(candidates[0])

def clean_bool(s):
    return s.astype(str).str.strip().str.lower().map({
        "true": 1, "false": 0, "yes": 1, "no": 0, "1": 1, "0": 0
    })

df = read_csv(PATH)
required = [
    "percentage_increase_in_utilitarianism", "moderator_ethical_stance",
    "critical_event_occurred", "argument_intensity", "audience_interest_level",
    "average_debate_duration", "number_of_sessions"
]
missing = [c for c in required if c not in df.columns]
if missing:
    print("Missing required columns: " + ", ".join(missing))
    raise SystemExit

text_cols = [c for c in ["philosophical_topic", "topic_of_debate"] if c in df.columns]
if text_cols:
    text = df[text_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    ethics = text.str.contains(r"ethic|moral|justice|duty|virtue|utilitari|deontolog", regex=True)
    sub = df.loc[ethics].copy()
    if len(sub) == 0:
        sub = df.copy()
        print("No explicit ethics-topic matches; using all rows.")
else:
    sub = df.copy()

num = ["percentage_increase_in_utilitarianism", "argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions"]
for c in num:
    sub[c] = pd.to_numeric(sub[c], errors="coerce")
sub["critical_event"] = clean_bool(sub["critical_event_occurred"])
sub["stance"] = sub["moderator_ethical_stance"].astype(str).str.strip().str.lower()
y = "percentage_increase_in_utilitarianism"
sub = sub.dropna(subset=[y, "stance"])

print(f"Rows analyzed: {len(sub)} (of {len(df)} total)")
if len(sub) == 0:
    print("No analyzable rows.")
    raise SystemExit

means = sub.groupby(["stance", "critical_event"], dropna=False)[y].agg(["count", "mean"]).reset_index()
print("Mean percentage increase by moderator stance and critical event:")
for _, r in means.iterrows():
    event = "unknown" if pd.isna(r["critical_event"]) else ("yes" if r["critical_event"] == 1 else "no")
    print(f"  {r['stance']} / event={event}: n={int(r['count'])}, mean={r['mean']:.3f}")

corr_cols = [c for c in num if c != y]
print("Pearson correlations with percentage increase:")
for c in corr_cols:
    z = sub[[c, y]].dropna()
    if len(z) >= 3 and z[c].nunique() > 1 and z[y].nunique() > 1:
        print(f"  {c}: r={z[c].corr(z[y]):.3f}, n={len(z)}")
    else:
        print(f"  {c}: insufficient variation/data")

try:
    import statsmodels.formula.api as smf
    model_df = sub[[y, "argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions", "stance", "critical_event"]].dropna().copy()
    if len(model_df) >= 12 and model_df["stance"].nunique() >= 2:
        formula = ("percentage_increase_in_utilitarianism ~ argument_intensity + "
                   "audience_interest_level + average_debate_duration + number_of_sessions + "
                   "C(stance) + critical_event + "
                   "argument_intensity:C(stance) + audience_interest_level:C(stance)")
        fit = smf.ols(formula, data=model_df).fit()
        print(f"OLS adjusted R-squared: {fit.rsquared_adj:.3f}; n={int(fit.nobs)}")
        for term in ["argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions", "critical_event"]:
            if term in fit.params.index:
                print(f"  adjusted {term}: coefficient={fit.params[term]:.3f}, p={fit.pvalues[term]:.3g}")
    else:
        print("OLS: insufficient complete rows or stance levels for adjusted analysis.")
except Exception as e:
    print("OLS unavailable; descriptive results above are retained.")