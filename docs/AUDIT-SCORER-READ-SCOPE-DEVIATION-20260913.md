# Scorer read-scope deviation record — 2026-09-13

## Status

This is a read-scope deviation record. It is not a verified data leak
classification, a benchmark result, or an evaluator calibration record.
No answer text is reproduced here.

## Event

While locating DiscoveryBench scorer code, this command was issued from the
scorer-runtime worktree:

```powershell
rg -n "class .*Scor|scorer_fixture|adapted_score|context|variable_f1|relation" E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery --glob '*.py' --glob '*.md' --glob '*.json' --glob '!**/validation/**' --glob '!**/*gold*' --glob '!**/*custody*' --glob '!**/*labels*'
```

The glob was too broad. It covered `discovery/run/raw_calls/*.answer.json`;
the exclusions did not exclude that directory. The tool output included task
answer content from that directory. It did not establish whether any content
was a reference, gold answer, or validation material, and this record does not
make that claim.

The confirmed paths shown in the returned output were:

- `E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery\run\raw_calls\081-t12-B-b_review.answer.json`
- `E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery\run\raw_calls\082-t12-A-a_plan.answer.json`
- `E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery\run\raw_calls\083-t12-A-a_revise.answer.json`
- `E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery\run\raw_calls\084-t12-A-a_final.answer.json`
- `E:\_ryanDev\AI\research-loop-benchmark-20260912\discovery\run\raw_calls\085-t12-pair-judge.answer.json`

The output was truncated. This is therefore not asserted to be a complete
matched-path inventory; obtaining one would require a prohibited repeat scan.

## Use and containment

No files were written, downloaded, copied, or changed in the benchmark worktree.
The exposed content was not used to set a score, threshold, rubric dimension,
test expected value, evaluator reference, or scientific claim. The subsequent
scoring code uses only a typed frozen-rubric transport and test-only synthetic
fixtures; it explicitly documents that no production evaluator is connected.

This agent stopped all benchmark-directory reads after identifying the issue.
It must not perform independent acceptance, unexposed-reference review, or
further benchmark inspection for this work.

## Time and provenance

The event occurred during the 2026-09-13 scorer-runtime repair turn (local
host timezone: Asia/Shanghai). The tool transcript did not capture a reliable
per-command wall-clock timestamp, so no more precise time is claimed.

This record is limited to metadata needed for root-level comparison with the
already-exposed training inventory.
