import os
import numpy as np
import pandas as pd
import statsmodels.api as sm

path = "/input/data.csv"
if not os.path.exists(path):
    path = "/input/data"
df = pd.read_csv(path)

outcome = "effective_translations_score"
artifact = "digitized_artifacts_count"
tools = "deciphering_tools_count"
complexity = "script_complexity_level"
education_cols = ["educational_program_availability", "included_in_academic_curriculum"]
media = "media_representation"
needed = [outcome, artifact, tools, complexity, *education_cols, media]
missing_cols = [c for c in needed if c not in df.columns]
if missing_cols:
    raise ValueError("Missing required columns: " + ", ".join(missing_cols))

print("rows", len(df), "columns", len(df.columns))
print("missingness", df[needed].isna().sum().to_dict())
print("variability", df[needed].nunique(dropna=True).to_dict())

work = df[needed].copy()
for c in needed:
    work[c] = pd.to_numeric(work[c], errors="coerce")
work["artifact_tool_ratio"] = np.where(
    work[tools] > 0, work[artifact] / work[tools], np.nan
)
# Educational support is the mean of available binary/ordinal indicators.
work["educational_support"] = work[education_cols].mean(axis=1)
model_cols = [outcome, "artifact_tool_ratio", complexity, "educational_support", media]
model = work[model_cols].replace([np.inf, -np.inf], np.nan).dropna()
print("complete_cases", len(model))
print("analysis_summary", model.describe().round(4).to_dict())

if len(model) >= 6 and model[outcome].nunique() > 1:
    # Log transform reduces leverage from highly unequal artifact/tool ratios.
    model["log_artifact_tool_ratio"] = np.log1p(model["artifact_tool_ratio"])
    predictors = ["log_artifact_tool_ratio", complexity, "educational_support", media]
    X = sm.add_constant(model[predictors], has_constant="add")
    y = model[outcome]
    fit = sm.OLS(y, X).fit(cov_type="HC3")
    print("correlations", model[[outcome, "artifact_tool_ratio", complexity, "educational_support", media]].corr().round(4).to_dict())
    print("ols_n", int(fit.nobs), "r_squared", round(float(fit.rsquared), 4), "adjusted_r_squared", round(float(fit.rsquared_adj), 4))
    result = pd.DataFrame({"coef": fit.params, "p_value": fit.pvalues, "ci_low": fit.conf_int()[0], "ci_high": fit.conf_int()[1]})
    print("ols_coefficients", result.round(4).to_dict(orient="index"))
else:
    print("ols", "not run: fewer than 6 complete variable rows or no outcome variability")