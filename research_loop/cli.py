"""Operator CLI. Run 'export' before connecting the public agent to a model."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from .agent import Agent, DEFAULT_CRITERIA
from .ontology import ContractError, Task, canonical, implementation_hash
from .provider import HTTPProvider, Provider, fixture_role_providers
from .store import Store


def load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def export(destination: Path) -> None:
    destination = destination.resolve()
    if any((p / "data" / "labels").exists() for p in (destination, *destination.parents)):
        raise ContractError("export outside any workspace containing data/labels")
    destination.mkdir(parents=True, exist_ok=False)
    package = destination / "research_loop"
    package.mkdir()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        shutil.copyfile(source, package / source.name)
    pause = Path(__file__).resolve().parents[1] / ".research-loop-paused"
    if pause.exists():
        shutil.copyfile(pause, destination / pause.name)
    (destination / "runtime-manifest.json").write_text(
        canonical({"core_hash": implementation_hash(), "contains_labels": False}), encoding="utf-8")


def scorer(args: list[str]) -> dict[str, Any]:
    result = subprocess.run([sys.executable, "-m", "research_loop.evaluate", *args],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        # Child errors never contain label contents; avoid passing arbitrary output to models.
        raise ContractError(result.stderr.strip() or "private evaluator failed")
    return json.loads(result.stdout)


def role_providers(backend: str) -> tuple[Provider, Provider, Provider]:
    """Assemble (executor, auditor_1, auditor_2) providers with pairwise-distinct identities.

    The fixture backend ships three toy identities. Real deployments configure one
    endpoint per role through environment variables: ``RESEARCH_LOOP_BASE_URL`` /
    ``RESEARCH_LOOP_MODEL`` / ``RESEARCH_LOOP_API_KEY`` for the executor,
    ``RESEARCH_LOOP_AUDITOR_*`` for auditor_1 and ``RESEARCH_LOOP_AUDITOR2_*`` for
    auditor_2. A different model name on a shared base_url is the minimum acceptable
    separation (it yields a distinct identity); distinct base_urls are recommended
    because same-model deployments share hallucination modes. The agent rejects any
    triple whose identities are not pairwise distinct.
    """
    if backend == "fixture":
        return fixture_role_providers()
    return (HTTPProvider.from_env(), HTTPProvider.from_env("RESEARCH_LOOP_AUDITOR_"),
            HTTPProvider.from_env("RESEARCH_LOOP_AUDITOR2_"))


def toy_task(key: str, family: str, *, negative: bool = True) -> dict[str, Any]:
    return {
        "id": key, "family": family, "scope": "toy.assay",
        "question": f"How should the locked assay finding for {key} update its hypothesis?",
        "rule": "A valid negative observation closes this hypothesis negatively. A positive observation may proceed.",
        "prerequisites": {"valid_comparison": True, "artifacts_available": True},
        "evidence": [{"id": "obs", "kind": "observation", "scope": "toy.assay",
                      "content": f"{key}: valid " + ("negative" if negative else "positive") + " observation"}],
        "checks": ["rule_preserved", "evidence_referenced", "no_program_completion"],
    }


def demo(directory: Path) -> dict[str, Any]:
    """Run the real CLI in fresh public processes; synthetic backend only."""
    directory = directory.resolve()
    if directory.exists():
        raise ContractError("demo directory must be new")
    directory.mkdir(parents=True)
    runner = directory / "public"
    export(runner)
    private = directory / "evaluator"
    private.mkdir()
    db = runner / "state.sqlite"

    def command(*args: str) -> Any:
        result = subprocess.run(
            [sys.executable, "-m", "research_loop", "--db", str(db), *args],
            cwd=runner, capture_output=True, text=True, encoding="utf-8", check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        )
        if result.returncode:
            raise ContractError(result.stderr.strip() or "demo subprocess failed")
        return json.loads(result.stdout)

    dev = runner / "development.json"
    dev.write_text(canonical(toy_task("D001", "dev-assay")), encoding="utf-8")
    evaluation = runner / "evaluation-tasks.json"
    evaluation.write_text(canonical([toy_task("E001", "heldout-a"), toy_task("E002", "heldout-b")]), encoding="utf-8")
    labels = private / "expected.json"
    labels.write_text(canonical({"E001": "closed_negative", "E002": "closed_negative"}), encoding="utf-8")
    criteria = runner / "criteria.json"
    criteria.write_text(canonical({**DEFAULT_CRITERIA, "min_pairs": 2}), encoding="utf-8")
    base = command("init")
    command("enqueue", str(dev))
    cycle = command("cycle", "--backend", "fixture", "--proposer", "demo-proposer")
    candidate = cycle["candidate"]
    trial = command("freeze-trial", "--candidate", candidate, "--tasks", str(evaluation),
                    "--criteria", str(criteria), "--labels", str(labels), "--evaluator", "demo-evaluator")
    command("run-trial", trial["trial"], "--backend", "fixture")
    receipt = command("evaluate", trial["trial"], "--labels", str(labels))
    promoted = command("--approver", "demo-reviewer", "promote", trial["trial"],
                       "--reviewer", "demo-reviewer")
    next_task = runner / "next-development.json"
    next_task.write_text(canonical(toy_task("D002", "new-dev-assay")), encoding="utf-8")
    command("enqueue", str(next_task))
    after = command("run", "--backend", "fixture")
    rollback = command("--approver", "demo-reviewer", "rollback", "--reviewer", "demo-reviewer",
                       "--reason", "Exercise reversible deployment.")
    summary = {"mode": "engineering_fixture", "scientific_effectiveness_proven": False,
               "base": base["active_version"], "candidate": candidate, "trial": trial["trial"],
               "before": cycle["run"]["status"], "after": after[0]["status"],
               "promoted": promoted["active_version"], "rollback": rollback["active_version"],
               "evaluation": receipt, "status": command("status")}
    (directory / "demo-result.json").write_text(canonical(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Real backends need one deployment per role: RESEARCH_LOOP_BASE_URL/MODEL/API_KEY "
               "for the executor and RESEARCH_LOOP_AUDITOR_*/RESEARCH_LOOP_AUDITOR2_* for the two "
               "auditors; the three provider identities must be pairwise distinct (a different "
               "model name is the minimum, a separate base_url is recommended).")
    parser.add_argument("--db", default="state.sqlite", help="controller database (operator-owned)")
    parser.add_argument("--approver", action="append", default=[], metavar="ID",
                        help="reviewer identifier authorized to promote or roll back; "
                             "repeatable; default: none, promotion and rollback stay disabled (fail closed)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    p = commands.add_parser("export")
    p.add_argument("directory", type=Path)
    p = commands.add_parser("demo")
    p.add_argument("directory", type=Path)
    p = commands.add_parser("enqueue")
    p.add_argument("task")
    for name in ("run", "cycle", "propose", "run-trial"):
        p = commands.add_parser(name)
        p.add_argument("--backend", choices=["http", "fixture"], default="http")
        if name == "run":
            p.add_argument("--limit", type=int, default=1)
        if name in {"cycle", "propose"}:
            p.add_argument("--proposer", required=True)
        if name == "propose":
            p.add_argument("run_id")
        if name == "run-trial":
            p.add_argument("trial")
    p = commands.add_parser("freeze-trial")
    p.add_argument("--candidate", required=True)
    p.add_argument("--tasks", required=True)
    p.add_argument("--criteria", help="frozen JSON thresholds; defaults require 20 pairs and 2 families")
    p.add_argument("--labels", required=True, help="private evaluator file outside public workspace")
    p.add_argument("--evaluator", required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("trial")
    p.add_argument("--labels", required=True)
    p = commands.add_parser("promote")
    p.add_argument("trial")
    p.add_argument("--reviewer", required=True,
                   help="must be an authorized --approver; promotion is fail closed by default")
    p = commands.add_parser("rollback")
    p.add_argument("--reviewer", required=True)
    p.add_argument("--reason", required=True)
    p = commands.add_parser("recover")
    p.add_argument("run_id")
    args = parser.parse_args()
    if ((Path(__file__).resolve().parents[1] / ".research-loop-paused").exists()
            and args.command in {"enqueue", "run", "cycle", "propose", "freeze-trial", "run-trial", "promote"}):
        parser.exit(2, "independent_review: research-loop live entry paused; use the independently reviewed single-experiment workflow.\n")
    store = None
    try:
        if args.command == "export":
            export(args.directory)
            result: Any = {"public_workspace": str(args.directory.resolve())}
        elif args.command == "demo":
            result = demo(args.directory)
        elif args.command == "evaluate":
            result = scorer(["--db", str(Path(args.db).resolve()), "--trial", args.trial,
                             "--labels", str(Path(args.labels).resolve())])
        else:
            store = Store(args.db)
            agent = Agent(store, approvers=args.approver)
            if args.command == "init":
                result = {"active_version": agent.initialize()}
            elif args.command == "status":
                version = agent.version()
                result = {"active_version": version["id"], "lessons": len(version["lessons"]),
                          "queue": [dict(r) for r in store.db.execute("SELECT * FROM queue ORDER BY seq")],
                          "runs": len(store.all("run")), "trials": len(store.all("trial")),
                          "journal_events": store.verify_journal()}
            elif args.command == "enqueue":
                task = Task.parse(load(args.task))
                agent.enqueue(task)
                result = {"queued": task.id}
            elif args.command == "freeze-trial":
                commitment = scorer(["--commit", "--labels", str(Path(args.labels).resolve())])
                tasks = load(args.tasks)
                if not isinstance(tasks, list):
                    raise ContractError("trial tasks must be a list")
                trial = agent.freeze_trial(
                    args.candidate, [Task.parse(t) for t in tasks],
                    load(args.criteria) if args.criteria else DEFAULT_CRITERIA,
                    evaluator=args.evaluator, label_commitment=commitment["label_commitment"])
                result = {"trial": trial}
            elif args.command == "promote":
                result = {"active_version": agent.promote(args.trial, reviewer=args.reviewer)}
            elif args.command == "rollback":
                result = {"active_version": agent.rollback(reviewer=args.reviewer, reason=args.reason)}
            elif args.command == "recover":
                agent.recover(args.run_id)
                result = {"interrupted_run_closed": args.run_id, "retried": False}
            else:
                executor, auditor_1, auditor_2 = role_providers(args.backend)
                if args.command == "run":
                    if args.limit < 1:
                        raise ContractError("run limit must be positive")
                    result = []
                    for _ in range(args.limit):
                        run = agent.run_next(executor, auditor_provider=auditor_1,
                                             auditor2_provider=auditor_2)
                        if run is None:
                            break
                        result.append(run)
                elif args.command == "cycle":
                    run = agent.run_next(executor, auditor_provider=auditor_1,
                                         auditor2_provider=auditor_2)
                    candidate = agent.propose(run["id"], executor, proposer=args.proposer) if run and run["state"] == "closed" else None
                    result = {"run": run, "candidate": candidate, "active_version": agent.version()["id"]}
                elif args.command == "propose":
                    result = {"candidate": agent.propose(args.run_id, executor, proposer=args.proposer)}
                else:
                    result = agent.run_trial(args.trial, executor, auditor_provider=auditor_1,
                                             auditor2_provider=auditor_2)
        print(canonical(result))
    except (ContractError, OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Operation rejected: {exc}\n")
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    main()
