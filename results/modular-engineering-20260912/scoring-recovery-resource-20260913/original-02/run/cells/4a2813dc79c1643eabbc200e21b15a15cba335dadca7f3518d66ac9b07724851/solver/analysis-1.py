import csv
import math
import os
import statistics

PATH = "/input/public_csv"
TARGET = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity", "audience_interest_level",
    "average_debate_duration", "number_of_sessions"
]

def num(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None

def pearson(xs, ys):
    if len(xs) < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    denx = sum((x - mx) ** 2 for x in xs)
    deny = sum((y - my) ** 2 for y in ys)
    if denx == 0 or deny == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(denx * deny)

def solve(A, b):
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-10:
            return None
        M[c], M[p] = M[p], M[c]
        q = M[c][c]
        M[c] = [z / q for z in M[c]]
        for r in range(n):
            if r != c:
                q = M[r][c]
                M[r] = [M[r][j] - q * M[c][j] for j in range(n + 1)]
    return [M[i][-1] for i in range(n)]

try:
    with open(PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
except Exception as e:
    print("Unable to read /input/public_csv: " + str(e))
    raise SystemExit

ethics = []
for r in rows:
    topic = ((r.get("philosophical_topic") or "") + " " + (r.get("topic_of_debate") or "")).lower()
    if "ethic" in topic:
        ethics.append(r)
if not ethics:
    ethics = rows

print("Rows analyzed: %d (ethics-focused filter; fallback to all rows if no match)." % len(ethics))
y = [num(r.get(TARGET)) for r in ethics]
for col in NUMERIC:
    pairs = [(num(r.get(col)), yy) for r, yy in zip(ethics, y)]
    pairs = [(x, z) for x, z in pairs if x is not None and z is not None]
    if len(pairs) >= 2:
        print("Pearson r(%s, %s) = %.3f, n=%d" % (col, TARGET, pearson([p[0] for p in pairs], [p[1] for p in pairs]), len(pairs)))

for col in ("moderator_ethical_stance", "critical_event_occurred"):
    groups = {}
    for r in ethics:
        z = num(r.get(TARGET))
        key = (r.get(col) or "missing").strip().lower()
        if z is not None:
            groups.setdefault(key, []).append(z)
    for key, vals in sorted(groups.items()):
        print("Mean %s=%s: %s (n=%d)" % (col, key, round(statistics.mean(vals), 3), len(vals)))

# Descriptive OLS with intercept, numeric predictors, and categorical indicators.
complete = []
stances = sorted({(r.get("moderator_ethical_stance") or "missing").strip().lower() for r in ethics})
for r in ethics:
    vals = [num(r.get(TARGET))] + [num(r.get(c)) for c in NUMERIC]
    if all(v is not None for v in vals):
        ev = (r.get("critical_event_occurred") or "missing").strip().lower()
        st = (r.get("moderator_ethical_stance") or "missing").strip().lower()
        complete.append((r, vals[0], vals[1:], ev, st))
if complete:
    levels = sorted({x[3] for x in complete})
    base_stance = stances[0] if stances else "missing"
    base_event = levels[0] if levels else "missing"
    X = []
    Y = []
    labels = ["intercept"] + NUMERIC
    labels += ["stance=" + s for s in stances if s != base_stance]
    labels += ["critical_event=" + e for e in levels if e != base_event]
    for r, target, nums, event, stance in complete:
        row = [1.0] + nums
        row += [1.0 if stance == s else 0.0 for s in stances if s != base_stance]
        row += [1.0 if event == e else 0.0 for e in levels if e != base_event]
        X.append(row); Y.append(target)
    k = len(labels)
    A = [[sum(row[i] * row[j] for row in X) for j in range(k)] for i in range(k)]
    b = [sum(X[t][i] * Y[t] for t in range(len(Y))) for i in range(k)]
    beta = solve(A, b)
    if beta is not None:
        mean_y = statistics.mean(Y)
        pred = [sum(a * q for a, q in zip(row, beta)) for row in X]
        sse = sum((a - q) ** 2 for a, q in zip(Y, pred))
        sst = sum((a - mean_y) ** 2 for a in Y)
        r2 = 1 - sse / sst if sst else None
        print("OLS complete cases: %d; R-squared: %s" % (len(Y), "%.3f" % r2 if r2 is not None else "undefined"))
        print("OLS coefficients: " + ", ".join("%s=%.4g" % (a, q) for a, q in zip(labels, beta)))
    else:
        print("OLS unavailable: predictors are rank-deficient.")
else:
    print("OLS unavailable: insufficient complete numeric cases.")