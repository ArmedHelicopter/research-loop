# Exact closure association and synthetic fixture expiry

Source 205d7540 passed 35 focused checks. The observation catalogue now binds the
exact authenticated terminal closure digest to the retained evaluator gate.
Independent readback rejects a swapped gate with original journal, catalogue and
receipt unchanged. Successful, partial and rejected observations retain distinct
eligibility. These checks do not replace the separate complete 16-cell run.

Source 83aefb74 passed two synthetic fixture boundary checks. Synthetic login
lifetime is seven days; it remains locally valid at a 24-hour exercise point,
while the production 120-second near-expiry rejection remains intact. The tests
hard-disable account networking. This fixture repair does not estimate the C5
runtime duration and does not itself establish a complete C5 result.

The expiry check completed in its original exec call without yielding a native
session id; its exact native start/completion receipt preserves this distinction.
The closure check retains original native session 8602 and its terminal join.
Both preserve frozen sources, raw reports and noncredential originals. There
were no real model, added paid API or VAL calls. Engineering evidence is not
scientific effectiveness or all-module coverage.
