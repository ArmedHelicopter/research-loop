# Source review: SciCode and ScienceAgentBench

**Scope.** This metadata and adapter-design review used the official repositories at the recorded pins. It read only the two READMEs, ScienceAgentBench `run_infer.py` and `run_eval.py`, and SciCode `eval/inspect_ai/scicode.py`. It did not fetch a Hugging Face dataset, Drive or SharePoint artifact, instance record, reference program, test result, rubric, or gold payload. The selection/optimization component receives no task text or private evaluation material. A solver can receive a train task only after controller split freezing.

## Fixed sources and declared acquisition

| Source | Pin and inspected files | Declared official acquisition |
| --- | --- | --- |
| ScienceAgentBench | `c26e151ed601ba109dc4d35e057ff8e73fec469d`; README blob `d1eb0900de1820ec40bd1f35c63bc25ff050b26a`; inference blob `833a00da2417c2df4c637d8a8f3f9439cb305938`; evaluator blob `d5f0cb737e96b74ab428d0a9046d194ae2ed2b3b` | Agent-input annotation sheet: <https://huggingface.co/datasets/osunlp/ScienceAgentBench>. Separate full artifact declared as `benchmark_verified.zip`: <https://buckeyemailosu-my.sharepoint.com/:u:/g/personal/chen_8336_osu_edu/IQB870QrmuqwS5Ck33cHpJfkAVt3LsMeariREIwP3AT7byA?e=3ckueC>. Neither belongs in an optimizer or solver acquisition path. |
| SciCode | `8699b7c8fcebd916e429e26d28ac5d2257d25db3`; README blob `4765b4266145ee19e2660520f79ec2a2b45401fa`; Inspect evaluator blob `8537b6a11839158845af9b01cb5bd8d6cdcad667` | The evaluator calls `hf_dataset('SciCode1/SciCode', split='test')`, giving <https://huggingface.co/datasets/SciCode1/SciCode>. The README directs numeric test results to <https://drive.google.com/drive/folders/1W5GZW6_bdiDAiipuFMqdUhvUaHIj6-pR?usp=drive_link>, stored at `eval/data/test_data.h5`; that HDF5 is private-evaluator-only. |

The user has authorized acquisition of relevant sources. These locations still require received-version, inventory and frozen-split binding before solver export; they do not establish local contents or exposure history.

## Source-established schema boundaries

### ScienceAgentBench

`run_infer.py` loads `osunlp/ScienceAgentBench` with `split="validation"`. Its formatted task uses `task_inst`, `dataset_folder_tree`, `dataset_preview`, `output_fname`, a local `dataset_path`, and optional `domain_knowledge`. It uses `gold_program_name` only to name an output and does not put it into the formatted task. `run_eval.py` uses `gold_program_name`, `eval_script_name`, and full artifact material. The README names `datasets/`, `eval_programs/`, `gold_programs/`, and `scoring_rubrics/`.

| Class | Fields/artifact class | Reader |
| --- | --- | --- |
| Train solver after freeze | `task_inst`, `dataset_folder_tree`, `dataset_preview`, `output_fname`, optional `domain_knowledge`, selected train data directory | Train solver only |
| Controller-only grouping | Opaque source-record token, source pin, provenance-family token, dataset/artifact-family token, split assignment | Custody/controller only |
| Private evaluation | `gold_program_name`, `eval_script_name`, `eval_programs/`, `gold_programs/`, `scoring_rubrics/`, validation paths | Restricted evaluator only |

The inspected source does **not** supply a row-to-publication field or a complete dataset-artifact lineage. Matching a `dataset_folder_tree` root is evidence of a shared local artifact, not proof of shared paper provenance. It cannot justify paper-level independent groups alone.

### SciCode

The official Inspect evaluator defaults to `split='test'` and places the complete Hugging Face record in sample metadata. It accesses `problem_id`, `sub_steps`, step prompts, function headers, return lines, optional backgrounds, `required_dependencies`, `test_cases`, and `ground_truth_code`. Its scorer reads `sub_steps[*].test_cases`, `sub_steps[*].ground_truth_code`, and the numeric HDF5 file. The source evaluator therefore cannot serve unchanged as a public adapter: `metadata={k: v for k, v in record.items()}` crosses the private boundary.

| Class | Fields/artifact class | Reader |
| --- | --- | --- |
| Train solver after freeze | Frozen projection of `problem_id`, step prompt, function header, return line, permitted background, `required_dependencies` | Train solver only |
| Controller-only grouping | Opaque record token and custodian-derived family token | Custody/controller only |
| Private evaluation | `test_cases`, `ground_truth_code`, `test_data.h5`, evaluator output and logs | Restricted evaluator only |

`problem_id` is the only grouping-relevant identifier established by this inspected code. The README reports 80 main problems and 338 subproblems, supporting a minimum constraint that all substeps of one `problem_id` stay together. It does not prove that `problem_id` identifies a shared dataset, paper, or artifact family.

## Concrete controller procedure

1. A custody process, isolated from optimization, acquires approved materials and creates a source manifest: source pin, opaque record token, custodian-only record key, provenance-family token, artifact-family token, received-artifact hashes, license-review state, and public/private locator classes. No prompt, answer, test, reference, or gold program enters the optimizer journal.
2. Form groups from the transitive closure of equal provenance-family and artifact-family tokens. For SciCode, keep every substep of a `problem_id` together, then merge only on received-source provenance evidence. For ScienceAgentBench, require a received-source mapping to provenance and artifact families; do not infer publication grouping from `dataset_folder_tree` alone.
3. Freeze a split manifest before task projection: source pin, received-artifact hashes, opaque group-token list, deterministic split seed, train/validation token sets, and fixed denominator. The optimizer sees only aggregate eligibility counts and opaque group tokens; it cannot request a row, prompt, validation locator, or private field.
4. Materialize only frozen train projections for the solver. Keep evaluator paths, references, gold code, tests, rubrics, and every validation projection in a separate evaluator store. Return only a constrained score receipt after a frozen candidate exists.
5. Reject a run if a selected row cannot bind to a group, a group crosses the frozen split boundary, a private locator appears in a solver envelope, or a received-artifact hash changes after freezing.

## Licensing and evidence still required

ScienceAgentBench's README says repository code is MIT, most tasks are CC BY 4.0, and some adapted tasks retain upstream licenses. This is not a per-received-record license manifest. SciCode's repository LICENSE is Apache-2.0; that does not establish a license for its Hugging Face records or HDF5 evaluation artifact. Both source-data license reviews remain pending.

Neither pinned source tree proves an unseen group is unexposed, that a retrieved source is complete, or that a row has a valid shared dataset-paper-artifact grouping. These remain custody and received-data evidence requirements; their absence is not permission to run.
