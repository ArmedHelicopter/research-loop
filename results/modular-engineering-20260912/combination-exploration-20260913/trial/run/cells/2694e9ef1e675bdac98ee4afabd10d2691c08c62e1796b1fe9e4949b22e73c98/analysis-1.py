import csv
import math
import os

PATH = "/input/public_csv"
REQUIRED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]


def num(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def binary(x):
    s = str(x).strip().lower()
    if s in {"1", "true", "t", "yes", "y"}:
        return 1.0
    if s in {"0", "false", "f", "no", "n"}:
        return 0.0
    return num(x)


def corr(xs, ys):
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    a = sum((x - mx) ** 2 for x in xs)
    b = sum((y - my) ** 2 for y in ys)
    if a <= 0 or b <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(a * b)


def fmt(x):
    return "NA" if x is None else f"{x:.3f}"


def summarize(rows, label):
    if not rows:
        return f"{label}: n=0"
    total_fish = sum(r["fish_caught"] for r in rows)
    total_hours = sum(r["hours"] for r in rows)
    mean_rate = sum(r["fish_caught"] / r["hours"] for r in rows) / len(rows)
    return (f"{label}: n={len(rows)}, weighted_rate={fmt(total_fish / total_hours)}, "
            f"mean_trip_rate={fmt(mean_rate)}")


def main():
    if not os.path.isfile(PATH):
        print("No input file found at /input/public_csv")
        return
    with open(PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        missing = [c for c in REQUIRED if c not in fields]
        if missing:
            print("Missing columns: " + ", ".join(missing))
            return
        rows = []
        for raw in reader:
            r = {
                "fish_caught": num(raw["fish_caught"]),
                "livebait": binary(raw["livebait"]),
                "camper": binary(raw["camper"]),
                "persons": num(raw["persons"]),
                "child": num(raw["child"]),
                "hours": num(raw["hours"]),
            }
            if r["fish_caught"] is None or r["hours"] is None or r["hours"] <= 0:
                continue
            rows.append(r)

    print(f"Valid trips: {len(rows)}")
    print(summarize(rows, "Overall"))
    for col in ("livebait", "camper"):
        vals = sorted({r[col] for r in rows if r[col] is not None})
        for v in vals:
            print(summarize([r for r in rows if r[col] == v], f"{col}={int(v) if v.is_integer() else v}"))

    rates = [r["fish_caught"] / r["hours"] for r in rows]
    for col in ("persons", "child", "hours"):
        pairs = [(r[col], rate) for r, rate in zip(rows, rates) if r[col] is not None]
        print(f"Correlation {col} vs fish_per_hour: {fmt(corr([p[0] for p in pairs], [p[1] for p in pairs]))}")

    if rows:
        med = sorted(r["persons"] for r in rows if r["persons"] is not None)[len([r for r in rows if r["persons"] is not None]) // 2]
        print(summarize([r for r in rows if r["persons"] is not None and r["persons"] <= med], f"persons<=median({med:g})"))
        print(summarize([r for r in rows if r["persons"] is not None and r["persons"] > med], f"persons>median({med:g})"))

    try:
        import numpy as np
        clean = [r for r in rows if all(r[k] is not None for k in ("livebait", "camper", "persons", "child", "hours"))]
        if len(clean) >= 6:
            y = np.array([r["fish_caught"] for r in clean])
            X = np.array([[1, r["hours"], r["livebait"], r["camper"], r["persons"], r["child"]] for r in clean])
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            print("OLS fish_caught coefficients [intercept,hours,livebait,camper,persons,child]: " + ", ".join(fmt(float(x)) for x in beta))
    except Exception:
        pass


if __name__ == "__main__":
    main()
