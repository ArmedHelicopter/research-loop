# Hugging Face source-acquisition metadata

**Read-only scope (2026-09-12).** Queried only official Hugging Face dataset-repository metadata and recursive tree metadata at fixed revisions. No dataset row, viewer preview, annotation, answer, reference, README/card body, or file/blob content was requested. The raw JSON responses saved beside this review are the acquisition evidence.

## Recorded source snapshots

| Dataset repository | Fixed revision from repository API | Repository state | License tag / provenance fields |
| --- | --- | --- | --- |
| `osunlp/ScienceAgentBench` | `9c6e96c9e74572e979b0930ee735041cef528cb7` | `private=false`, `gated=false`, `disabled=false`; API `lastModified=2026-05-01T15:07:13Z` | Tag and card license: `cc-by-4.0`; tag `arxiv:2410.05080`. `cardData.source` was empty, so the API response contains no further source-provenance mapping. |
| `SciCode1/SciCode` | `4510f6a6aa27c43fad7b43da2c59602a86e88480` | `private=false`, `gated=false`, `disabled=false`; API `lastModified=2025-02-17T18:04:31Z` | Tag and card license: `apache-2.0`; tag `arxiv:2407.13168`. `cardData.source` was empty, so the API response contains no further source-provenance mapping. |

## Fixed-revision artifacts

The `oid` below is a Hub Git object identifier reported by the tree endpoint. The
LFS `oid` is explicitly a SHA-256 object identifier; it is not the same thing as
the Git `oid`. File contents were not fetched.

| Repository | Path | Format inferred only from filename | Bytes | Tree `oid` | LFS metadata |
| --- | --- | --- | ---: | --- | --- |
| ScienceAgentBench | `ScienceAgentBench.csv` | CSV | 278,626 | `65c148f52416af4a00437072108c6c1b03dce7dc` | none reported |
| ScienceAgentBench | `data/verified-00000-of-00001.parquet` | Parquet | 129,086 | `3ab66131e23fe3e924c5de9af528440de99679ae` | SHA-256 `c6f937863a220bd1762a00c20a0f79cc8dfca900b819bdb552150310731ae147`, size 129,086, pointer size 131 |
| SciCode | `problems_dev.jsonl` | JSON Lines | 279,558 | `ce8984e15447ef0876e696906d100f3eadf941d0` | none reported |
| SciCode | `problems_test.jsonl` | JSON Lines | 933,500 | `b72b96897f0b72ee560b588b7b80106e00a93d29` | none reported |

Repository control files were also present in the tree but are not acquisition
payloads: ScienceAgentBench `.gitattributes` (2,419 bytes) and `README.md`
(5,705 bytes); SciCode `.gitattributes` (2,461 bytes) and `README.md` (333
bytes). The ScienceAgentBench tree also reports a `data` directory object.

## Controller-only reproducible retrieval routes

A controller can request a fixed artifact without supplying a moving branch
name by using the official Hub resolve route:

```text
https://huggingface.co/datasets/osunlp/ScienceAgentBench/resolve/9c6e96c9e74572e979b0930ee735041cef528cb7/ScienceAgentBench.csv?download=true
https://huggingface.co/datasets/osunlp/ScienceAgentBench/resolve/9c6e96c9e74572e979b0930ee735041cef528cb7/data/verified-00000-of-00001.parquet?download=true
https://huggingface.co/datasets/SciCode1/SciCode/resolve/4510f6a6aa27c43fad7b43da2c59602a86e88480/problems_dev.jsonl?download=true
https://huggingface.co/datasets/SciCode1/SciCode/resolve/4510f6a6aa27c43fad7b43da2c59602a86e88480/problems_test.jsonl?download=true
```

The metadata API reports both repositories as public and ungated, so a token is
not indicated by these source records. These routes are reproducible controller
entry points because each pins a revision and path. They are **not** evidence
that a deployed controller keeps the bytes model-invisible: that requires the
local custody/service boundary, a content-hash receipt after retrieval, and a
solver environment without the route or credentials.

## Raw metadata evidence

| Saved response | Bytes | SHA-256 of saved response |
| --- | ---: | --- |
| `hf-source-acquisition-metadata.scienceagentbench.raw.json` | 2,144 | `8922C5561177DB7CA8AA4557BC737910F643677CB1CA3F3D51FD1B83C9FFBC5A` |
| `hf-source-acquisition-metadata.scienceagentbench.tree.raw.json` | 2,920 | `08157F2BBEBD6EB65B07048466469FBF2D0E3E2C5C4E34091C3222942B71ADE8` |
| `hf-source-acquisition-metadata.scicode.raw.json` | 1,083 | `992D7FB8D6025530CA32E929ABC4904D4C7665DF10338724AFFA33BF498DC9F2` |
| `hf-source-acquisition-metadata.scicode.tree.raw.json` | 2,296 | `C1FDB3F236B3E30786D66AA591795A1861D0D7DA9235DCD776DA2C0A42DA666D` |

## Not established

The metadata does not prove the dataset card's license applies to every record
or a separate evaluator artifact. It does not expose a row-to-paper, dataset,
or artifact-family provenance mapping, a train/validation grouping, prior
exposure, or source completeness beyond these four tracked paths at their fixed
revisions. It also does not validate the content bytes: an acquisition service
must download to a private store, verify the recorded object/size expectations
and its own SHA-256 receipt, inventory the received material, and then create
opaque groups before any solver projection.
