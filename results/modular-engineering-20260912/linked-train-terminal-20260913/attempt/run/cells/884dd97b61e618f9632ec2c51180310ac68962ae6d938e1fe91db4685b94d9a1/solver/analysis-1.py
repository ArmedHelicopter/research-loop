import csv
import glob
import os
import math

REQUIRED = {"fish_caught", "livebait", "camper", "persons", "child", "hours"}


def num(value):
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def main():
    files = glob.glob("/input/*.csv") + glob.glob("/input/**/*.csv", recursive=True)
    files = list(dict.fromkeys(files))
    selected = None
    rows = []
    for path in files:
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fields = set(reader.fieldnames or [])
                if REQUIRED.issubset(fields):
                    selected = path
                    rows = list(reader)
                    break
        except (OSError, UnicodeError, csv.Error):
            continue

    if selected is None:
        print("No CSV containing the required fish columns was found in /input.")
        return

    valid = []
    for r in rows:
        values = {k: num(r.get(k)) for k in REQUIRED}
        if all(values[k] is not None for k in REQUIRED) and values["hours"] > 0:
            values["rate"] = values["fish_caught"] / values["hours"]
            valid.append(values)

    print(f"file={os.path.basename(selected)} rows={len(rows)} valid={len(valid)}")
    if not valid:
        print("No valid rows with positive hours; rates cannot be computed.")
        return

    total_fish = sum(r["fish_caught"] for r in valid)
    total_hours = sum(r["hours"] for r in valid)
    print(f"overall_rate_weighted={total_fish / total_hours:.4f} fish/hour")
    print(f"overall_rate_trip_mean={sum(r['rate'] for r in valid) / len(valid):.4f} fish/hour")

    groups = {}
    for r in valid:
        key = int(r["livebait"]) if r["livebait"].is_integer() else r["livebait"]
        groups.setdefault(key, []).append(r)
    for key in sorted(groups, key=str):
        g = groups[key]
        weighted = sum(r["fish_caught"] for r in g) / sum(r["hours"] for r in g)
        mean = sum(r["rate"] for r in g) / len(g)
        print(f"livebait={key} n={len(g)} weighted_rate={weighted:.4f} trip_mean={mean:.4f}")

    try:
        import numpy as np
        y = np.array([r["fish_caught"] for r in valid])
        X = np.array([[1, r["livebait"], r["camper"], r["persons"], r["child"], r["hours"]] for r in valid])
        if len(valid) >= X.shape[1]:
            coef, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
            print(f"adjusted_ols_livebait_coefficient={coef[1]:.4f} rank={rank}")
        else:
            print("Adjusted OLS skipped: too few valid rows.")
    except Exception:
        print("Adjusted OLS unavailable; descriptive rates were still computed.")


if __name__ == "__main__":
    main()
