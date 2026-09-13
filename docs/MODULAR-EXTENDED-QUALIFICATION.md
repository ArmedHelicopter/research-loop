# Extended-source qualification gate

The checked manifest at `data-source-metadata/extended-source-qualification.json` binds only the metadata-only live import summary.  It confirms 80 SciCode and 102 ScienceAgentBench inventory entries remain `unknown` exposure, unsplit, and without verified access isolation. It does not read a task, answer, reference, evaluator, label, or private source payload.

Both sources are blocked. The live-import pins differ from the earlier public repository metadata pins, so the first custody action is a signed pin and received-artifact reconciliation. Repository licenses do not settle received dataset terms: SciCode's repository is Apache-2.0; ScienceAgentBench's repository is MIT, while its official README says task licenses can vary. The per-record received-data license evidence remains required. Official source pages: <https://github.com/scicode-bench/SciCode>, <https://github.com/OSU-NLP-Group/ScienceAgentBench>.

SciCode's official material establishes that one main problem can contain subproblems; all substeps must stay in a single `problem_id` group. ScienceAgentBench's recorded source adapter yields only a minimum dataset-folder-root constraint; it does not prove paper, dataset, or artifact independence. The manifest therefore requires a separate custodian to derive provenance/artifact-family tokens from authorised received records and merge their transitive closure before splitting.

An authorised content-derived operation must run outside the optimizer and return only a signed metadata receipt: source pin, received-artifact hashes, opaque record and family tokens, license-review state, exposure-attestation digest, and group membership. It must not return prompts, answers, references, test cases, gold programs, evaluator paths, labels, or validation locators. The custody service can then freeze train/validation group tokens and export train projections; validation still requires the existing independent calibration and panel-lease flow.

`discoverybench` and `blade` remain required core benchmarks. The manifest adds neither a replacement nor a validation qualification.
