"""Thin A/B runner. Labels are read only at scoring time in this process."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from experiments.sep_of_powers.render_prompt import (
    load_task,
    render_lock_prompt,
    render_observe_prompt,
    render_prompt,
)
from experiments.sep_of_powers.score import hash_rule, load_label, parse_output, score_pair

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks" / "pilot"
LABEL_DIR = ROOT / "data" / "labels" / "pilot"


class LLMUnavailable(RuntimeError):
    pass


def discover_llm() -> dict[str, str]:
    """Return endpoint settings or raise LLMUnavailable. Does not score tasks."""
    key = (
        os.environ.get("XAI_API_KEY")
        or os.environ.get("GROK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_APIKEY")
    )
    if not key:
        raise LLMUnavailable("no XAI_API_KEY / GROK_API_KEY / OPENAI_API_KEY in environment")
    if os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"):
        base = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1")
        model = os.environ.get("RESEARCH_LOOP_MODEL", "grok-4-fast")
    else:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model = os.environ.get("RESEARCH_LOOP_MODEL", "gpt-4.1-mini")
    return {"api_key": key, "base_url": base.rstrip("/"), "model": model}


def chat_complete(cfg: dict[str, str], prompt: str, *, max_tokens: int, temperature: float) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": cfg["model"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LLMUnavailable(str(exc)) from exc
    choice = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage") or {}
    return {
        "text": choice,
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "elapsed_s": time.time() - t0,
        "raw": payload,
    }


def run_arm_a(cfg: dict[str, str], task: dict[str, Any], *, max_tokens: int, temperature: float) -> dict[str, Any]:
    prompt = render_prompt(task, arm="A")
    call = chat_complete(cfg, prompt, max_tokens=max_tokens, temperature=temperature)
    return {
        "arm": "A",
        "task_id": task["id"],
        "prompts": [prompt],
        "raw_output": call["text"],
        "lock_hash": None,
        "prompt_tokens": call["prompt_tokens"],
        "completion_tokens": call["completion_tokens"],
        "elapsed_s": call["elapsed_s"],
    }


def run_arm_b(cfg: dict[str, str], task: dict[str, Any], *, max_tokens: int, temperature: float) -> dict[str, Any]:
    lock_prompt = render_lock_prompt(task)
    lock_call = chat_complete(cfg, lock_prompt, max_tokens=max_tokens, temperature=temperature)
    try:
        committed = str(parse_output(lock_call["text"]).get("decision_rule") or "").strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        committed = task["locked_rule"].strip()
    if not committed:
        committed = task["locked_rule"].strip()
    digest = hash_rule(committed)
    observe_prompt = render_observe_prompt(task, committed_rule=committed)
    obs_call = chat_complete(cfg, observe_prompt, max_tokens=max_tokens, temperature=temperature)
    return {
        "arm": "B",
        "task_id": task["id"],
        "prompts": [lock_prompt, observe_prompt],
        "raw_output": obs_call["text"],
        "lock_hash": digest,
        "committed_rule": committed,
        "prompt_tokens": lock_call["prompt_tokens"] + obs_call["prompt_tokens"],
        "completion_tokens": lock_call["completion_tokens"] + obs_call["completion_tokens"],
        "elapsed_s": lock_call["elapsed_s"] + obs_call["elapsed_s"],
    }


def score_run(run: dict[str, Any]) -> dict[str, Any]:
    task = load_task(TASK_DIR / f"{run['task_id']}.json")
    label = load_label(LABEL_DIR / f"{run['task_id']}.json")
    scored = score_pair(task, label, run["raw_output"], lock_hash=run.get("lock_hash"))
    scored.update(
        {
            "arm": run["arm"],
            "prompt_tokens": run["prompt_tokens"],
            "completion_tokens": run["completion_tokens"],
            "elapsed_s": run["elapsed_s"],
        }
    )
    return scored


def list_task_ids() -> list[str]:
    return sorted(p.stem for p in TASK_DIR.glob("T*.json"))
