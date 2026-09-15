# Deterministic CSV measurement authorities (v2)

`build_csv_measurement_admission_verifier` creates the only CSV-aware M1
consumer. It accepts a task-digest keyed set of `CsvMeasurementDataset`
objects, so each public TRAIN task has its own exact CSV byte parent and frozen
original-bound specifications. A specification covers exactly one typed
`FrozenAdmissionMaterial.originals` entry through that entry's immutable
record digest. It cannot be substituted with a generated explanation.

The workers are separate pinned source files:

- `csv_reader_measurement_worker.py` parses with `csv.reader`.
- `csv_dictreader_measurement_worker.py` parses with `csv.DictReader`.

They reject absent or duplicate headers, row-width errors, absent requested
columns, malformed numeric cells, and non-finite `NaN`/infinite decimal
values. They support only `row_count`, `nonempty_count`, and exact
`decimal_sum`. Decimal sums use integer coefficients and exponents, so the
aggregate does not depend on Python's default 28-digit Decimal context.

Every source callback creates one immutable receipt at
`receipt_root/<cell_digest>/<authority>-<request_digest>.json`; there is no
global reusable authority receipt. One owned child process computes all at most
32 frozen specifications for that authority/request; its timeout is 20 seconds.
Thus a 16-cell controller has exactly 32 source callbacks and at most 32 child
processes (40 seconds of child timeout per cell, 640 seconds if serialized).
The receipt retains stdout, stderr, exit code, timeout status, elapsed time,
every individual result, exact CSV/spec/worker/Python hashes, and known zero
local cost. A source execution failure yields an `unknown` signed provenance
verdict and remains retained evidence; it cannot become accepted provenance.

The signed ordinary admission response includes the raw-receipt digest. On
`qualify`, `replay`, and `assessments`,
`CsvMeasurementAdmissionMaterialVerifier` verifies the original signed
qualification first, then verifies the original typed material, current CSV
bytes, frozen specs, worker sources, Python executable, and raw receipt. The
admission-prediction M1+M4+M7 controller accepts this concrete verifier type
and freezes its full binding in the controller configuration. Existing v1
verifiers stay unchanged.

Both workers may agree on a frozen aggregate because they share the same CSV.
That establishes only scoped measurement validity. A completed measurement
that differs from the frozen expected value produces `ScientificState` values
`validity="unknown"`, `support="undetermined"`, `novelty="unknown"`, and
`investment="repair"`; this is a legitimate M1 rejection. No outcome in this
path establishes independent data, causal support, a scientific hypothesis, or
scientific utility.
