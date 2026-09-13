# Prediction mechanisms to the benchmark solver

The Q3.2 and Q5.3 extension uses the existing generic train controller, mechanism
driver, solver and independent primary scorer interfaces. It freezes all 20
cells: both primary benchmarks, both M4 arms, two Q3.2 variants and three Q5.3
variants. Q3.2 reserves four precursor calls and two solver calls per cell; Q5.3
reserves two precursor calls and two solver calls. The complete grid reserves
96 model calls and 20 Docker executions, with no replacement of failed cells.

Only the actual public prediction artifacts may reach the solver. The projection
reconstructs frozen plans and retained branches from the bound caller bundle,
checks actual precursor requests/responses and the final mechanism request, and
compares the actual persisted prediction registry. Controller truth, arm/variant
labels, admissions and planning-status fields remain in controller provenance.
Fixture IDs and wording must be neutral while preserving the intended differences
in mechanisms, predictions, source membership and duplicate titles.

Tests use a real CodexModelPort with synthetic transport, actual Docker, original
journals and independent primary fixture scoring. Adversarial changes to stages,
plans, retained branches, source records, requests or the persisted registry must
be rejected. Model rejection retains the frozen denominator and unused solver
allocation. No private references, validation payloads or paid calls are used.

Q3.2's precursor remains a planning intervention: existing support records are
caller supplied. A downstream benchmark execution does not prove that the three
plans independently acquired data or experimentally discriminated hypotheses.
Those physical/analysis operations, independent mechanism-endpoint scores and
actual scientific effects remain separate required work. Q5.3's deterministic
deduplication is implemented; its benchmark benefit is still to be measured.
