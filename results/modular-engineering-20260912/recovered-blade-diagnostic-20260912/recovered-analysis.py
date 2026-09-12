import os
import glob
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore")

root = "/input/data"
if os.path.isdir(root):
    files = sorted(glob.glob(os.path.join(root, "*.csv")) + glob.glob(os.path.join(root, "*.parquet")) + glob.glob(os.path.join(root, "*.json")))
    if not files:
        raise FileNotFoundError("No CSV, Parquet, or JSON data file found under /input/data")
    path = files[0]
elif os.path.isfile(root):
    path = root
else:
    raise FileNotFoundError("/input/data was not found")

if path.lower().endswith(".parquet"):
    df = pd.read_parquet(path)
elif path.lower().endswith(".json"):
    df = pd.read_json(path)
else:
    df = pd.read_csv(path)

print("rows=%d cols=%d" % df.shape)
print("columns=%s" % list(df.columns))

required = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]
missing_cols = [c for c in required if c not in df.columns]
if missing_cols:
    print("missing_required_columns=%s; skipping analyses" % missing_cols)
else:
    print("missingness=%s" % df[required].isna().sum().to_dict())
    for c in required:
        print("nunique_%s=%d" % (c, df[c].nunique(dropna=True)))

    x = df[required].copy()
    for c in required:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    valid = x.dropna()
    print("complete_rows=%d" % len(valid))

    if len(valid):
        y = valid["fish_caught"]
        h = valid["hours"]
        print("fish_summary=n:%d mean:%.6g sd:%.6g min:%.6g max:%.6g zero_fraction:%.6g" %
              (len(y), y.mean(), y.std(ddof=1), y.min(), y.max(), (y == 0).mean()))
        print("hours_summary=mean:%.6g min:%.6g max:%.6g" % (h.mean(), h.min(), h.max()))

        positive = valid[h > 0].copy()
        if len(positive):
            rate = positive["fish_caught"] / positive["hours"]
            print("observed_rate_per_hour=n:%d mean:%.6g median:%.6g sd:%.6g" %
                  (len(rate), rate.mean(), rate.median(), rate.std(ddof=1)))
            print("pooled_rate_per_hour=%.6g" % (positive["fish_caught"].sum() / positive["hours"].sum()))
        else:
            print("rate_analysis=skipped: no positive hours")

        model = valid[(valid["hours"] > 0) & (valid["fish_caught"] >= 0)].copy()
        predictors = ["livebait", "camper", "persons", "child"]
        if len(model) >= 10 and model[predictors].nunique().sum() > 0:
            X = model[predictors].copy()
            X = sm.add_constant(X, has_constant="add")
            try:
                fit = sm.GLM(model["fish_caught"], X,
                             family=sm.families.NegativeBinomial(),
                             offset=np.log(model["hours"])).fit()
                print("negative_binomial_offset_model_n=%d" % len(model))
                print("coefficients=%s" % fit.params.round(6).to_dict())
                print("rate_ratios=%s" % np.exp(fit.params).round(6).to_dict())
                print("pvalues=%s" % fit.pvalues.round(6).to_dict())
            except Exception as e:
                print("model=skipped:%s" % type(e).__name__)
        else:
            print("model=skipped: insufficient valid rows or predictor variation")

print("limitations=Exploratory observational analysis; associations are not causal. Results depend on data quality, coding, missing-value handling, and the chosen count model. The simple rate is a descriptive ratio, and the fitted model uses a fixed negative-binomial dispersion, no validation, and no uncertainty adjustment for clustering or selection. Execution and independent auditing are required before substantive conclusions.")