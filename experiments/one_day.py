"""一天资格验证的订阅传输与公开运行器；不读取评价标签。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
from datetime import datetime, timezone

from research_loop.agent import Agent
from research_loop.ontology import ContractError, Task, canonical, decision, digest, public
from research_loop.provider import Call, INSTRUCTIONS, require_public_workspace
from research_loop.store import Store

DEADLINE = datetime(2026, 9, 11, 23, 34, 24, tzinfo=timezone.utc)
FINAL_INSTRUCTION = (
    "Independently adjudicate this narrow research decision using the supplied locked protocol and "
    "raw evidence. The anonymous draft is fallible. Recompute its scientific status, correcting it "
    "when needed. Do not infer truth from an audit verdict. Preserve valid negative and inconclusive "
    "findings. Return exactly the executor JSON schema: status "
    "(proceed/closed_negative/inconclusive/withdrawn/invalid), rule_hash (copy supplied hash), "
    "evidence_ids (nonempty supplied IDs), reason (brief numerical justification), "
    "declared_program_complete (false)."
)
DISABLED = (
    "shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "hooks", "browser_use",
    "browser_use_external", "computer_use", "image_generation", "view_image", "sleep_tool",
    "workspace_dependencies", "skill_search", "in_app_browser", "goals",
)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(canonical(value), encoding="utf-8")


def schema(role):
    refs = {"type": "array", "items": {"type": "string"}}
    if role.startswith("auditor"):
        properties = {"checks": {"type": "array", "items": {
            "type": "object", "properties": {"id": {"type": "string"},
            "pass": {"type": "boolean"}, "evidence_ids": refs},
            "required": ["id", "pass", "evidence_ids"], "additionalProperties": False}}}
    elif role == "reflector":
        properties = {"instruction": {"type": "string"}, "evidence_ids": refs}
    else:
        properties = {"status": {"type": "string", "enum": ["proceed", "closed_negative",
            "inconclusive", "withdrawn", "invalid"]}, "rule_hash": {"type": "string"},
            "evidence_ids": refs, "reason": {"type": "string"},
            "declared_program_complete": {"type": "boolean"}}
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


class Subscription:
    """显式订阅 CLI；所有真实调用及失败留回执，不自动重试。"""
    def __init__(self, model, effort, executable, directory, budget, limit):
        self.model, self.executable = model, str(executable)
        self.effort = effort
        self.directory, self.budget, self.limit = Path(directory), Path(budget), limit
        self.directory.mkdir(parents=True, exist_ok=True)
        self.context = {}
        self.identity = "codex-subscription:" + digest([model, effort, DISABLED])

    def call(self, role, payload):
        require_public_workspace()
        public(payload)
        now = datetime.now(timezone.utc)
        if now >= DEADLINE:
            raise ContractError("absolute deadline reached")
        ledger = read(self.budget) if self.budget.exists() else {"calls": 0, "tokens": 0}
        if ledger.get("usage_incomplete"):
            raise ContractError("prior usage incomplete; budget cannot be verified")
        if ledger["calls"] >= self.limit or ledger["tokens"] >= 5_000_000:
            raise ContractError("fixed invocation/token budget reached")
        ledger["calls"] += 1
        write(self.budget, ledger)  # reserve before process launch, including failed calls
        prefix = self.directory / f"{ledger['calls']:03d}-{role}"
        spec = prefix.with_suffix(".schema.json")
        write(spec, schema(role))
        instructions = FINAL_INSTRUCTION if role == "final" else INSTRUCTIONS[role]
        prompt = "No tools or file access. Return only JSON.\n" + instructions + "\n" + canonical(payload)
        prefix.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
        output = prefix.with_suffix(".answer.json")
        argv = [self.executable, "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "-C", str(Path.cwd()), "-m", self.model,
                "-s", "read-only", "--json", "--output-schema", str(spec),
                "-o", str(output), "-c", 'model_reasoning_effort="' + self.effort + '"',
                "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
                "-c", "features.skip_host_skill_discovery=true"]
        for feature in DISABLED:
            argv += ["--disable", feature]
        argv += ["-"]
        receipt = {"model_requested": self.model, "reasoning_effort": self.effort, "role": role, "argv": argv,
                   **self.context,
                   "started_utc": now.isoformat(), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                   "seed": None, "temperature": None, "provider_revision": None,
                   "access": "existing ChatGPT subscription", "extra_api_spend": 0}
        started = time.monotonic()
        try:
            result = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                                    encoding="utf-8", timeout=min(180, (DEADLINE-now).total_seconds()))
            prefix.with_suffix(".jsonl").write_text(result.stdout, encoding="utf-8")
            prefix.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
            receipt["exit_code"] = result.returncode
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            usages = [e["usage"] for e in events if e.get("type") == "turn.completed"]
            tool_events = [e for e in events if e.get("item", {}).get("type") in
                           {"command_execution", "mcp_tool_call", "web_search", "file_change"}]
            receipt["usage"] = usages
            receipt["tool_events"] = tool_events
            if usages:
                inp = sum(u["input_tokens"] for u in usages)
                out = sum(u["output_tokens"] for u in usages)
                ledger["tokens"] += inp + out
                write(self.budget, ledger)
            else:
                ledger["usage_incomplete"] = True
                write(self.budget, ledger)
            if result.returncode or len(usages) != 1 or tool_events:
                raise ContractError("subscription completion failed, tool use, or incomplete usage")
            value = read(output)
            receipt["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            return Call(value, inp, out, time.monotonic() - started)
        except subprocess.TimeoutExpired as exc:
            ledger["usage_incomplete"] = True
            write(self.budget, ledger)
            receipt["failure"] = "timeout"
            prefix.with_suffix(".partial.txt").write_bytes(
                exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode())
            raise ContractError("subscription timeout; no retry") from exc
        finally:
            receipt["elapsed_s"] = time.monotonic() - started
            write(prefix.with_suffix(".receipt.json"), receipt)


def adjudicate(provider, task, draft):
    try:
        response = provider.call("final", {"task": task.data(), "rule_hash": task.rule_hash,
                                          "draft": draft})
        return {"decision": decision(response.value, task), "usage": {
            "input_tokens": response.input_tokens, "output_tokens": response.output_tokens,
            "elapsed_s": response.elapsed_s}}
    except Exception as exc:
        return {"decision": None, "failure": type(exc).__name__}


def run(args):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    tasks = [Task.parse(t) for t in read(args.tasks)]
    if args.source_db:
        shutil.copyfile(args.source_db, root / "state.sqlite")
    if args.prior_budget:
        prior = read(args.prior_budget)
        if prior.get("usage_incomplete"):
            raise ContractError("development usage incomplete")
        write(root / "budget.json", {"calls": 0, "tokens": prior["tokens"],
                                    "prior_tokens": prior["tokens"]})
    store = Store(root / "state.sqlite")
    agent = Agent(store)
    version = agent.initialize()
    candidate = args.candidate or version
    if args.candidate:
        agent.version(candidate)
    write(root / "run-manifest.json", {"tasks_sha256": hashlib.sha256(Path(args.tasks).read_bytes()).hexdigest(),
          "baseline_version": version, "candidate_version": candidate,
          "label_commitment": args.label_commitment, "development": args.development,
          "deadline": DEADLINE.isoformat(), "started_utc": datetime.now(timezone.utc).isoformat(),
          "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    providers = [Subscription(model, effort, args.codex, root / "calls", root / "budget.json", args.call_limit)
                 for model, effort in (("gpt-5.6-luna", "low"), ("gpt-5.6-terra", "medium"),
                                       ("gpt-6-astra", "low"))]
    executor, auditor1, final = providers
    try:
        for i, task in enumerate(tasks):
            for arm in (["A", "B"] if i % 2 == 0 else ["B", "A"]):
                for provider in providers:
                    provider.context = {"task_id": task.id, "arm": arm,
                                        "phase": "development" if args.development else "evaluation"}
                if datetime.now(timezone.utc) >= DEADLINE:
                    raise ContractError("absolute deadline reached")
                if arm == "A":
                    try:
                        response = executor.call("executor", {"task": task.data(),
                                                  "rule_hash": task.rule_hash, "lessons": []})
                        raw = decision(response.value, task)
                        before = {"status": raw["status"], "decision": raw}
                    except Exception as exc:
                        before = {"status": "invalid", "decision": None, "failure": type(exc).__name__}
                else:
                    if args.development:
                        agent.enqueue(task)
                        before = agent.run_next(executor, auditor_provider=auditor1, auditor2_provider=final)
                    else:
                        before = agent.execute(task, candidate, executor, phase="evaluation",
                                               run_id=f"{task.id}-{arm}", auditor_provider=auditor1,
                                               auditor2_provider=final)
                # Identical anonymous schema; do not expose B's audit/identity metadata.
                draft = {"status": before["status"], "decision": before.get("decision")}
                result = {"task_id": task.id, "family": task.family, "arm": arm,
                          "before": before, "final": adjudicate(final, task, draft)}
                with (root / "results.jsonl").open("a", encoding="utf-8") as output:
                    output.write(canonical(result) + "\n")
                print(canonical({"task": task.id, "arm": arm, "completed": True}), flush=True)
                if (root / "budget.json").exists() and read(root / "budget.json").get("usage_incomplete"):
                    raise ContractError("usage missing; stop effect run")
        if args.development:
            eligible = [r for r in store.all("run") if r["phase"] == "development"
                        and r["evidence_admitted"] and r["audit_valid"]]
            if eligible:
                executor.context = {"task_id": eligible[0]["task"]["id"], "arm": "B", "phase": "reflection"}
                candidate = agent.propose(eligible[0]["id"], executor, proposer="development-executor")
                write(root / "candidate.json", {"candidate": candidate, "version": agent.version(candidate)})
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--call-limit", type=int, required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--source-db")
    parser.add_argument("--candidate")
    parser.add_argument("--label-commitment")
    parser.add_argument("--prior-budget")
    run(parser.parse_args())
