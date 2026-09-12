# Q3.1 live train-panel readiness audit

Audited revision: 0214866. This was a source-and-train-metadata-only review. No benchmark task body, label, quarantine, validation content, model provider, Docker process, or global configuration was opened or changed.

## Existing production API chain

1. evaluation/modular/train_io.py — TrainPacketExporter.export(item_ids) takes an exact nonempty allowlist from CustodyStore.export_train(), validates frozen inventory/split identity and public-file hashes, and writes train-only PublicTrainPacket values. PublicTrainPacket.task is the required PublicTask. It supports DiscoveryBench and BLADE; it rejects non-public filenames, source/split drift, symlinks and unpinned content.

2. research_loop/modular/panel_plan.py — compile_train_panel(...) accepts prepared PublicTask values, a FrozenRecord per exact task hash in evidence_by_task, frozen budget/scorer/criteria records, and one actual CandidatePackage for every executable runtime-arm hash. It creates the FrozenPanel, its cells, task/scenario/package maps, and binds scenario.base.task to task.content_hash.

3. research_loop/modular/panel_runner.py — run_train_cell(...) is the actual per-cell entry. It validates train domain, identity/task/scenario/package digest, registered variant, and scenario base-task identity before calling the Q3.1-only driver. Q31PredictionDriver sends frozen scenario.controller_input, CandidatePackage record, and exact panel-cell binding in the first request. M4-on freezes its plan and passes it to the final request; M4-off passes the control response. Malformed plans become bound driver_failure events; port exceptions become model_failure events. Both preserve failed runtime receipts.

4. research_loop/modular/model_port.py — CodexModelPort is the live no-tools CLI port. It requires a direct executable, fresh model work root, model gpt-5.6-luna / effort low, slot schemas, call/token ceilings, and a reviewed FrozenBaseContextPolicy. It reserves calls before Codex CLI I/O and writes ledger, events, usage and output hashes. The preceding audit_base_context(executable, fixed_cwd, audit_root, model="gpt-5.6-luna", effort="low") performs only a no-paid debug prompt render and writes an UNQUALIFIED candidate. A separate human review must create and SHA-pin the REVIEWED policy before paid calls.

The existing engineering handoff test is tests/test_modular_compiled_runner.py:test_compiled_q31_runs_every_paired_cell_through_real_runtime_journals. It uses a fixture model for 12 Q3.1 cells, validates compiler-to-runner journals, and obtains engineering_verified rather than a scientific result.

## Exact future controller invocation

After an authorized train-only export, a trusted controller can use the existing APIs in this sequence:

    packets = TrainPacketExporter(custody, snapshot_root, export_root).export(item_ids)
    tasks = [packet.task for packet in packets]
    compiled = compile_train_panel(
        stage=stage, scope_ids=("Q3.1",), tasks=tasks,
        evidence_by_task=evidence_by_task, budget=budget,
        baseline_digest=baseline_digest, p0_control=p0_control,
        packages_by_arm=packages_by_arm, scorer=scorer_identity,
        acceptance_criteria=criteria,
    )
    port = CodexModelPort(
        codex_executable, model_work_root, model="gpt-5.6-luna", effort="low",
        max_calls=2 * len(compiled.panel.cells), max_tokens=frozen_token_ceiling,
        schema_by_slot={"scenario": prediction_plan_schema, "final": candidate_schema},
        frozen_base_context=reviewed_policy,
    )
    result = run_train_cell(
        cell, task=compiled.tasks[cell.task_digest],
        scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash],
        objective=objective, sidecar=run_root / "cells" / cell.digest,
        model=port, audit_verifier=audit_verifier, scorer=None,
    )

The existing command interface only plans or reads traces:

    python -m research_loop.modular plan --baseline BASELINE_COMMIT --output ABSOLUTE_WORK_ROOT/programme-plan.json

There is no production CLI/controller which chains export, review, compile and run. That is the immediate missing reusable software seam. It must create separate fresh roots for the context audit, model ledger and every cell sidecar.

## Historical failed pilots

The retained original failed attempts are the Discovery transport under results/modular-engineering-20260912/train-transport-20260912T193716/ and the BLADE transport under results/modular-engineering-20260912/blade-reviewed-transport-20260912/. They preserve contracts, ledgers and traces, but no original pilot controller Python script is present in the integration tree.

The nearby Python files are later read-only diagnostic/recovery drivers, not reusable Q3.1 controllers:
- results/modular-engineering-20260912/recovered-train-diagnostic-20260912/run-diagnostic.py
- results/modular-engineering-20260912/recovered-blade-diagnostic-20260912/run-diagnostic.py
- results/modular-engineering-20260912/blade-reviewed-transport-20260912/run-diagnostic.py

The Discovery ledger retained a usage-format/context rejection. The BLADE ledger retained a startup notice classified as a context fault. Both pilots remain failed; neither ledger may be resumed or reclassified as a Q3.1 observation.

## Concrete external prerequisites

1. A trusted custody service must supply a nonempty explicit train allowlist with actual frozen inventory, split and snapshot-root access. There is no controller that selects item IDs or turns export receipts into evidence_by_task records.

2. The controller must freeze baseline digest, P0 control, objective, budget, scorer identity, acceptance criteria, exact public evidence per task, and CandidatePackage values whose TrainingManifest identities equal the exported tasks. compile_train_panel checks bindings but does not make or approve these materials.

3. A direct Codex executable, a new empty fixed public cwd outside all label-bearing ancestors, a new audit root, and a newly reviewed FrozenBaseContextPolicy are required. Historic policies cannot qualify a new run: live executable, config-source inventory, environment, shared arguments and rendered base context must match before each call.

4. Fresh external work roots are required for exported packets, audit evidence, port ledger and per-cell sidecars. A reused sidecar is invalid; CodexModelPort cannot continue after incomplete/failed reservation. inspect_terminal_call is read-only recovery, never a replay path.

5. Exact response schemas and a frozen token ceiling are required. Q3.1 allocates two slots per cell, so max_calls must cover two calls per compiled cell. Actual token use is recorded, not treated as matched between arms.

6. run_train_cell requires AuditVerifier with exactly two registered keys of at least 32 bytes even though Q3.1 requests no Docker execution. Keys must remain controller-side. Docker is not required for this driver because execution_limit is zero.

7. scorer=None produces engineering-only runtime receipts. Scientific evidence additionally needs a separately operated typed scorer returning ScientificScorerReceipt bound to cell, trace and frozen scorer digest, complete panel coverage, and substantive calibration. No such trusted scorer service or calibration material is currently invoked by this entry. A successful live run would be execution evidence only.

8. Only Q3.1 has a production driver. A matching Q3.2 cell is rejected even though it is registered; compiling a 48-obligation plan does not execute the other mechanisms.

## First test for the missing controller

Add a subprocess-free trusted-controller integration test: synthetic CustodyStore inventory plus temporary public snapshot files -> TrainPacketExporter.export -> TrainingManifest/CandidatePackage -> compile_train_panel(Q3.1) -> deterministic CodexModelPort fixture runner -> all fresh sidecars -> PanelReceiptVerifier.verify. Require engineering_verified and scientific_verified false for all 12 cells. Negatives must show that unreviewed context, wrong task/package/scenario binding, reused sidecar and a matching Q3.2 scenario stop before any model invocation. This establishes wiring only; it does not establish benchmark quality or scientific validity.
