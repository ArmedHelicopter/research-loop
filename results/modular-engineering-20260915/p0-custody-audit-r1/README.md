# P0 custody audit check r1

This directory retains the closed synthetic check of the auditor-only P0 custody-state snapshot reader.
The run joined native session 97843 with exit code 0; the JUnit receipt records 3 passing tests and no new paid calls.
The check used synthetic validation identities and synthetic signed receipts only. It did not read actual private custody state,
benchmark payloads, VAL inputs, or credentials, and it made no model or paid API call.

The reader checks caller-pinned state bytes, deterministic custody metadata allocation replay, and an optional independently retained
signed lease receipt. It records receipt absence without inventing issuance. It is a snapshot check, not a complete custody history,
external-custodian or calibration-authority proof, operating-system isolation proof, scientific validation, or a real private/VAL audit.

The full noncredential test-root originals are retained privately. Public files contain the frozen source ZIP, start/join receipts,
JUnit, test log, and archive manifests; no raw runtime sidecars or private test-state records are published.
