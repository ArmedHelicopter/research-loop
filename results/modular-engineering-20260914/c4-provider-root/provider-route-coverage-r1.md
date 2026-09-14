# Frozen execution-provider routing inventory

Integration `66d5b2a0550e2aa4ec2f1ad916181999b954afba`; C4 `47d020097629a7d6915676fe26917fcfc59ddc54`.

Static coverage: **48 issue IDs + 36 pairs + 5 triples + C4 = 90 unique obligations**, no missing/duplicate IDs. Q6.3 is one of the 48 and has its own phase; it is not a 91st obligation. Every obligation has an actual runtime entry, but **only M4/M5 v4 admits Grok**. Q3.2 has an additional distinct execution route that must also be ported. No tests or execution were performed.

The JSON is authoritative: each obligation refers to an adapter family with exact accepted schemas, controller/validator/driver refs, provider/ledger/policy checks and direct-read source lines. Source hashes and commit IDs bind all cited files.

## Singleton and separate phase routes

| ID | Family | Actual driver / phase | Slots |
|---|---|---|---|
| Q1.1 | singleton | `integration:research_loop/modular/history_panel_drivers.py:203 (Q11HistoryDriver)` | history_baseline, history_rebuilt, final + linked solver 2 |
| Q1.2 | singleton | `integration:research_loop/modular/history_panel_drivers.py:248 (Q12DependencyDriver)` | upstream_before_withdrawal, downstream_after_withdrawal, final + linked solver 2 |
| Q1.3 | singleton | `integration:research_loop/modular/support_panel_drivers.py:150 (Q13RepresentationDriver)` | representation_initial, representation_next, final + linked solver 2 |
| Q1.4 | singleton | `integration:research_loop/modular/support_panel_drivers.py:177 (Q14SupportDriver)` | support_initial, support_rechecked, final + linked solver 2 |
| Q1.5 | singleton | `integration:research_loop/modular/q15_panel_driver.py:18 (Q15HistoryReviewDriver)` | initial_review, reveal_review, final + linked solver 2 |
| Q1.6 | singleton | `integration:research_loop/modular/withdrawal_panel_drivers.py:112 (Q16WithdrawalDriver)` | initial, invalidation, final |
| Q1.7 | singleton | `integration:research_loop/modular/withdrawal_panel_drivers.py:142 (Q17TimeInformationDriver)` | initial, reconstructed, final |
| Q2.1 | singleton | `integration:research_loop/modular/pressure_panel_driver.py:203 (Q21PressureDriver)` | review_1, review_2, review_3, review_4, final |
| Q2.2 | singleton | `integration:research_loop/modular/semantic_panel_drivers.py:240 (Q22CompletionSemanticsDriver)` | semantic_judgement, alternative_analysis, final |
| Q2.3 | singleton | `integration:research_loop/modular/audit_panel_drivers.py:273 (Q23AuditFaultDriver)` | audit_initial, final |
| Q2.4 | singleton | `integration:research_loop/modular/audit_panel_drivers.py:278 (Q24AuditPairDriver)` | audit_initial, final |
| Q2.5 | singleton | `integration:research_loop/modular/polarity_goal_panel_drivers.py:242 (Q25EvidencePolarityDriver)` | assessment, final |
| Q2.6 | singleton | `integration:research_loop/modular/polarity_goal_panel_drivers.py:247 (Q26GoalLockDriver)` | assessment, final |
| Q2.7 | singleton | `integration:research_loop/modular/protocol_panel_driver.py:287 (Q27ProtocolDriver)` | final |
| Q3.1 | singleton | `integration:research_loop/modular/panel_runner.py:51 (Q31PredictionDriver)` | scenario, final + linked solver 2 |
| Q3.2 | singleton | `integration:research_loop/modular/prediction_panel_drivers.py:292 (Q32JointSeparateDriver)` | plan_1, plan_2, plan_3, final + linked solver 2 |
| Q3.3 | singleton | `integration:research_loop/modular/scheduler_panel_drivers.py:215 (M8SchedulerDriver)` | final |
| Q3.4 | singleton | `integration:research_loop/modular/scheduler_panel_drivers.py:215 (M8SchedulerDriver)` | final |
| Q3.5 | singleton | `integration:research_loop/modular/scheduler_panel_drivers.py:215 (M8SchedulerDriver)` | final |
| Q4.1 | singleton | `integration:research_loop/modular/q4_panel_drivers.py:109 (Q41IndependenceDriver)` | initial_1, initial_2, initial_3, initial_4, final |
| Q4.2 | singleton | `integration:research_loop/modular/q4_panel_drivers.py:163 (Q42RoleDriver)` | initial, final |
| Q4.3 | singleton | `integration:research_loop/modular/panel_runner.py:97 (Q43ReviewDriver)` | mechanism_initial, measurement_initial, mechanism_revision, measurement_revision, final + linked solver 2 |
| Q4.4 | singleton | `integration:research_loop/modular/q4_panel_drivers.py:198 (Q44CounterexampleDriver)` | initial, final |
| Q4.5 | singleton | `integration:research_loop/modular/q4_panel_drivers.py:229 (Q45SelfCorrectionDriver)` | initial_1, initial_2, revision_1, revision_2, final |
| Q5.1 | singleton | `integration:research_loop/modular/feasibility_panel_drivers.py:420 (Q51FeasibilityDriver)` | subjective, diagnostic, final |
| Q5.2 | singleton | `integration:research_loop/modular/feasibility_panel_drivers.py:434 (Q52DistinguishabilityDriver)` | subjective, diagnostic, final |
| Q5.3 | singleton | `integration:research_loop/modular/prediction_panel_drivers.py:341 (Q53DedupDriver)` | dedup, final + linked solver 2 |
| Q5.4 | singleton | `integration:research_loop/modular/q54_causal_driver.py:126 (Q54CausalDriver)` | ranking, diagnostic, final |
| Q5.5 | singleton | `integration:research_loop/modular/q55_causal_driver.py:334 (Q55Driver)` | diagnostic, final |
| Q6.1 | q6_operations | `integration:research_loop/modular/train_operations.py:219 (_operation)` | builder_proposal, analysis_program, final_answer |
| Q6.2 | q62 | `integration:research_loop/modular/metaprogram_training.py:404 (_run_cell)` | builder_proposal, analysis_program, final_answer |
| Q6.3 | q63 | `integration:research_loop/modular/metaprogram_training.py:404 (_run_cell)` | builder_proposal, analysis_program, final_answer |
| Q6.4 | singleton | `integration:research_loop/modular/semantic_panel_drivers.py:271 (Q64ScorerRepairDriver)` | first_semantic_judgement, first_alternative_analysis, second_semantic_judgement, second_alternative_analysis, final |
| Q6.5 | q6_operations | `integration:research_loop/modular/train_operations.py:219 (_operation)` | builder_proposal, analysis_program, final_answer |
| Q6.6 | q6_operations | `integration:research_loop/modular/train_operations.py:219 (_operation)` | builder_proposal, analysis_program, final_answer |
| Q7.1 | singleton | `integration:research_loop/modular/exploration_panel_drivers.py:435 (Q71ExplorationAdmissionDriver)` | prospective, diagnostic, final |
| Q7.2 | singleton | `integration:research_loop/modular/exploration_panel_drivers.py:449 (Q72FeasibilityAppealDriver)` | prospective, diagnostic, final |
| Q7.3 | singleton | `integration:research_loop/modular/exploration_extended_panel_drivers.py:380 (ExtendedExplorationDriver)` | prospective, diagnostic, final |
| Q7.4 | singleton | `integration:research_loop/modular/exploration_extended_panel_drivers.py:380 (ExtendedExplorationDriver)` | prospective, diagnostic, final |
| Q7.5 | singleton | `integration:research_loop/modular/exploration_extended_panel_drivers.py:380 (ExtendedExplorationDriver)` | prospective, diagnostic, final |
| Q7.6 | singleton | `integration:research_loop/modular/exploration_extended_panel_drivers.py:380 (ExtendedExplorationDriver)` | prospective, semantic_review, diagnostic, final |
| Q8.1 | singleton | `integration:research_loop/modular/retrieval_stage_panel_drivers.py:91 (RetrievalStagePanelDriver)` | research, competition, distinguish, review_a, review_b, retro_blind, retro_reveal, frontier, final |
| Q8.2 | singleton | `integration:research_loop/modular/retrieval_panel_drivers.py:166 (RetrievalPanelDriver)` | final + linked solver 2 |
| Q8.3 | singleton | `integration:research_loop/modular/retrieval_panel_drivers.py:166 (RetrievalPanelDriver)` | final + linked solver 2 |
| Q8.4 | singleton | `integration:research_loop/modular/retrieval_stage_panel_drivers.py:91 (RetrievalStagePanelDriver)` | final |
| Q8.5 | singleton | `integration:research_loop/modular/retrieval_final_panel_drivers.py:97 (RetrievalFinalPanelDriver)` | final |
| Q8.6 | singleton | `integration:research_loop/modular/retrieval_final_panel_drivers.py:97 (RetrievalFinalPanelDriver)` | review, final |
| Q8.7 | singleton | `integration:research_loop/modular/retrieval_final_panel_drivers.py:97 (RetrievalFinalPanelDriver)` | frontier_review_a, frontier_review_b, frontier, final |

Q8.1 uses its per-variant slot map; Q8.4-Q8.7 retain larger schema unions but execute the listed subset. Q3.2 additionally requires `q32_execution.run_q32_prospective_execution_panel`, with program_1/program_2/program_3/final.

## Exact combination routes

| IDs | Family / actual entry | Accepted current schemas | Provider |
|---|---|---|---|
| pair:M1+M2, pair:M1+M3, pair:M1+M5 | `admission`: `integration:research_loop/modular/admission_combination_controller.py:24 (run_admission_train_panels)` | admission-combination-train-config-v1, admission-combination-train-config-v2, admission-combination-train-config-v3 | Codex only |
| pair:M2+M3, pair:M2+M5, pair:M3+M5, triple:M2+M3+M5 | `lineage`: `integration:research_loop/modular/lineage_combination_controller.py:261 (run_lineage_train_panels)` | lineage-combination-train-config-v1, lineage-combination-train-config-v2, lineage-combination-train-config-v3 | Codex only |
| pair:M1+M4, pair:M2+M4, pair:M3+M4 | `state_prediction`: `integration:research_loop/modular/state_prediction_combination_controller.py:205 (run_state_prediction_train_panels)` | state-prediction-combination-train-config-v1, state-prediction-combination-train-config-v2 | Codex only |
| pair:M1+M6, pair:M2+M6, pair:M3+M6 | `state_retrieval`: `integration:research_loop/modular/state_retrieval_combination_controller.py:221 (run_state_retrieval_train_panels)` | state-retrieval-combination-train-config-v1, state-retrieval-combination-train-config-v2 | Codex only |
| pair:M1+M7, pair:M2+M7, pair:M3+M7 | `state_exploration`: `integration:research_loop/modular/state_exploration_combination_controller.py:214 (run_state_exploration_train_panels)` | state-exploration-combination-train-config-v1, state-exploration-combination-train-config-v2 | Codex only |
| pair:M1+M8, pair:M2+M8, pair:M3+M8 | `state_scheduling`: `integration:research_loop/modular/state_scheduling_combination_controller.py:214 (run_state_scheduling_train_panels)` | state-scheduling-combination-train-config-v1, state-scheduling-combination-train-config-v2 | Codex only |
| pair:M4+M6, pair:M5+M6, triple:M4+M5+M6 | `retrieval_review`: `integration:research_loop/modular/retrieval_review_combination_controller.py:157 (run_retrieval_review_panels)` | retrieval-review-combination-train-config-v1, retrieval-review-combination-train-config-v2 | Codex only |
| pair:M4+M7, pair:M5+M7, pair:M6+M7 | `mechanism_exploration`: `integration:research_loop/modular/mechanism_exploration_combination_controller.py:210 (run_mechanism_exploration_train_panels)` | mechanism-exploration-combination-train-config-v1, mechanism-exploration-combination-train-config-v2 | Codex only |
| pair:M4+M8, pair:M5+M8, pair:M6+M8 | `mechanism_scheduling`: `integration:research_loop/modular/mechanism_scheduling_combination_controller.py:210 (run_mechanism_scheduling_train_panels)` | mechanism-scheduling-combination-train-config-v1, mechanism-scheduling-combination-train-config-v2 | Codex only |
| triple:M1+M4+M7 | `admission_prediction_exploration`: `integration:research_loop/modular/admission_prediction_exploration_controller.py:214 (run_admission_prediction_exploration_train_panels)` | admission-prediction-exploration-combination-train-config-v1, admission-prediction-exploration-combination-train-config-v2 | Codex only |
| pair:M4+M5 | `m4_m5`: `integration:research_loop/modular/combination_train_controller.py:294 (run_m4_m5_train_panel)` | m4-m5-train-controller-config-v1, m4-m5-train-controller-config-v2, m4-m5-train-controller-config-v3, m4-m5-train-controller-config-v4 | Codex legacy; Grok only v4 |
| pair:M7+M8 | `exploration_scheduler`: `integration:research_loop/modular/exploration_scheduler_controller.py:226 (run_exploration_scheduler_train_panel)` | exploration-scheduler-train-controller-config-v1, exploration-scheduler-train-controller-config-v2 | Codex only |
| pair:M1+M9, pair:M2+M9, pair:M3+M9 | `state_improvement`: `integration:research_loop/modular/state_improvement_combination_controller.py:264 (run_state_improvement_train)` | state-improvement-train-plan-v1 | Codex only |
| pair:M4+M9, pair:M5+M9, pair:M6+M9 | `mechanism_improvement`: `integration:research_loop/modular/mechanism_improvement_combination_controller.py:292 (run_mechanism_improvement_train)` | mechanism-improvement-train-plan-v1 | Codex only |
| pair:M7+M9, pair:M8+M9, triple:M7+M8+M9 | `execution_improvement`: `integration:research_loop/modular/execution_improvement_combination_controller.py:293 (run_execution_improvement_train)` | execution-improvement-train-plan-v1 | Codex only |
| triple:M3+M6+M9 | `lineage_retrieval_improvement`: `integration:research_loop/modular/lineage_retrieval_improvement_combination_controller.py:292 (run_lineage_retrieval_improvement_train)` | lineage-retrieval-improvement-train-plan-v1 | Codex only |
| C4 | `c4`: `full-loo:research_loop/modular/full_loo_controller.py:250 (run_full_loo_train)` | c4-full-loo-runtime-plan-v1 | Codex only |

## Actionable boundaries

- **G1** Only pair:M4+M5 v4 admits Grok. All 89 other unique obligations and the extra Q3.2 execution route require versioned provider admission/ledger integration. A callable ModelPort protocol is not controller admission. Source: `integration:research_loop/modular/combination_train_controller.py:229 (_service_preflight)`; `integration:research_loop/modular/train_controller.py:204`.
- **G2** Q6.1/Q6.2/Q6.3/Q6.5/Q6.6 are absent from the 43-entry singleton DRIVERS; they have separate actual phase entries. Never report train_controller as all48 execution coverage. Source: `integration:research_loop/modular/panel_runner.py:200`; `integration:research_loop/modular/train_operations.py:25`; `integration:research_loop/modular/improvement_training.py:32 (run_candidate_training)`; `integration:research_loop/modular/metaprogram_training.py:480 (run_metaprogram_training)`.
- **G3** Q3.2 singleton Q32JointSeparateDriver is a planning route; the prospective execution route owns four calls and three measurements per cell with independent 180s Codex ports. Port both routes, without double-counting the Q ID. Source: `integration:research_loop/modular/prediction_panel_drivers.py:292 (Q32JointSeparateDriver)`; `integration:research_loop/modular/q32_execution.py:263 (_run_q32_compiled)`.
- **G4** Q6.2 intentionally reuses q63 plan/receipt types but is a separate experiment. M9 pair/triple builders and C4 are not Q6.3 metaprogram coverage. Source: `integration:research_loop/modular/improvement_training.py:14 (freeze_candidate_training)`; `integration:research_loop/modular/metaprogram_training.py:260 (FrozenMetaTrainingPlan)`; `full-loo:research_loop/modular/full_loo_controller.py:250 (run_full_loo_train)`.
- **G5** Execution-improvement and lineage-retrieval-improvement inherit error messages saying state improvement; their exact DESIGNS are two pairs plus M7/M8/M9 triple, and M3/M6/M9 triple respectively. Dead pair:M1+M9 conditionals in mechanism/state-derived families do not expand their DESIGNS. Source: `integration:research_loop/modular/execution_improvement_panel.py:9`; `integration:research_loop/modular/lineage_retrieval_improvement_panel.py:9`; `integration:research_loop/modular/mechanism_improvement_combination_controller.py:417`.
- **G6** Generic run_combination_cell and generic full-loo design registration are not the actual C4 nine-module runtime. C4 uses explicit FullLooPanel and its own closed scorer obligation. Source: `integration:research_loop/modular/combination_panels.py:330 (run_combination_cell)`; `full-loo:research_loop/modular/full_loo_panel.py:20 (FullLooPanel)`; `full-loo:research_loop/modular/full_loo_controller.py:250 (run_full_loo_train)`.
- **G7** FrozenProviderLedger can copy a dict but bind_events/phase _safe_call require Codex field names and reviewed context. A broad type-gate change would leave replay/accounting invalid. Source: `integration:research_loop/modular/state_improvement_build.py:141 (FrozenProviderLedger)`; `integration:research_loop/modular/metaprogram_training.py:338 (_safe_call)`; `integration:research_loop/modular/metaprogram_training.py:685`.
- **G8** Q3.2 dedicated controller checks type, counts, token threshold, model/effort, timeout and empty calls, but not schema equality or the reviewed-policy helper. The Codex port still applies protected-call context checks and restricts mock context to explicit non-subprocess fixtures. Freeze this distinct policy boundary in its native adapter rather than claiming parity with singleton preflight. Source: `integration:research_loop/modular/q32_execution.py:263 (_run_q32_compiled)`; `integration:research_loop/modular/model_port.py:429 (CodexModelPort.__init__)`; `integration:research_loop/modular/model_port.py:530 (CodexModelPort._invoke_protected)`.

## Assignment counts

| Adapter wave | Unique obligations |
|---|---:|
| ordinary | 73 |
| build/phase | 15 |
| existing M4/M5 v4 | 1 |
| C4 | 1 |

The ordinary wave also owns the extra Q3.2 route. This assigns current seams; it does not change any schema, approve generation, satisfy P0 or close C5/Q6.3 science.

JSON SHA-256: `f4462422283f61a1f4641b959a4e4ecce9ab46843e57de44efce93fba08db485`.
