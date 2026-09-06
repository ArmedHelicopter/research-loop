import ast
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from research_loop.cli import demo, export, toy_task
from research_loop.ontology import ContractError, canonical
from research_loop.provider import FixtureProvider, HTTPProvider


ROOT = Path(__file__).resolve().parents[1]


def command(root, *args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "research_loop", *args], cwd=root,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **(env or {})},
    )


def test_full_cli_demo_runs_in_separate_public_processes(tmp_path):
    result = demo(tmp_path / "demo")
    assert result["before"] == "proceed" and result["after"] == "closed_negative"
    assert result["promoted"] == result["candidate"]
    assert result["rollback"] == result["base"]
    assert result["evaluation"]["eligible"]
    assert result["evaluation"]["scientific_effectiveness_proven"] is False
    root = tmp_path / "demo" / "public"
    assert not (root / "data" / "labels").exists()
    assert not list(root.rglob("*labels*.json"))
    assert (tmp_path / "demo" / "evaluator" / "expected.json").exists()
    assert result["status"]["runs"] == 6
    again = command(root, "status")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["active_version"] == result["base"]


def test_export_copies_only_runtime_and_refuses_overwrite_or_nested_labels(tmp_path):
    target = tmp_path / "public"
    export(target)
    assert {p.name for p in target.iterdir()} == {"research_loop", "runtime-manifest.json"}
    assert all(p.suffix == ".py" for p in (target / "research_loop").iterdir())
    with pytest.raises(FileExistsError):
        export(target)
    unsafe = tmp_path / "private-project"
    (unsafe / "data" / "labels").mkdir(parents=True)
    with pytest.raises(ContractError, match="outside"):
        export(unsafe / "nested")


def test_live_backend_refuses_source_worktree_with_labels():
    backend = HTTPProvider(base_url="http://127.0.0.1:9/v1", model="test", api_key="test-placeholder")
    with pytest.raises(ContractError, match="exported workspace"):
        backend.call("executor", {"task": toy_task("test", "test")})


def test_public_agent_modules_do_not_import_scorers_or_read_label_files():
    for name in ("agent.py", "export.py", "ontology.py", "provider.py", "store.py"):
        tree = ast.parse((ROOT / "research_loop" / name).read_text(encoding="utf-8"))
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any("evaluate" in name or "experiments" in name for name in imports)
    # The model transport has no subprocess/eval/exec tool and receives JSON only.
    tree = ast.parse((ROOT / "research_loop" / "provider.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in {"eval", "exec", "open"} for n in ast.walk(tree))


def test_actual_http_wire_and_accounting_from_exported_runner(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            payload = json.loads(request["messages"][1]["content"])
            system = request["messages"][0]["content"]
            role = "auditor_1" if system.startswith("Independently") else "executor"
            value = FixtureProvider().call(role, payload).value
            response = canonical({"choices": [{"message": {"content": canonical(value)}}],
                                  "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = tmp_path / "http-public"
        export(target)
        task = target / "task.json"
        task.write_text(canonical(toy_task("wire", "wire")), encoding="utf-8")
        assert command(target, "init").returncode == 0
        assert command(target, "enqueue", str(task)).returncode == 0
        # One deployment per role; a different model name on the shared local test
        # endpoint yields a distinct identity, which the fail-closed gate requires.
        env = {
            "RESEARCH_LOOP_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "RESEARCH_LOOP_MODEL": "wire-test",
            "RESEARCH_LOOP_API_KEY": "local-test-placeholder",
            "RESEARCH_LOOP_AUDITOR_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "RESEARCH_LOOP_AUDITOR_MODEL": "wire-test-auditor-1",
            "RESEARCH_LOOP_AUDITOR_API_KEY": "local-test-placeholder",
            "RESEARCH_LOOP_AUDITOR2_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "RESEARCH_LOOP_AUDITOR2_MODEL": "wire-test-auditor-2",
            "RESEARCH_LOOP_AUDITOR2_API_KEY": "local-test-placeholder",
        }
        result = command(target, "run", env=env)
        assert result.returncode == 0, result.stderr
        run = json.loads(result.stdout)[0]
        assert run["usage"]["calls"] == 3
        assert run["usage"]["input_tokens"] == 300
        assert run["usage"]["output_tokens"] == 30
        assert run["provider"].startswith("http:")
        assert len(set(run["providers"].values())) == 3
        assert run["providers"]["executor"] == run["provider"]
        assert len(requests) == 3
        assert all(len(r["messages"]) == 2 for r in requests)
        assert "local-test-placeholder" not in result.stdout
        assert "gold_" not in canonical(requests)
        assert "lessons" not in json.loads(requests[1]["messages"][1]["content"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_cli_rollback_is_fail_closed_without_an_explicit_approver(tmp_path):
    root = tmp_path / "cli-rollback"
    export(root)
    db = str(root / "state.sqlite")
    assert command(root, "--db", db, "init").returncode == 0
    denied = command(root, "--db", db, "rollback", "--reviewer", "reviewer", "--reason", "unauthorized")
    assert denied.returncode == 2 and "authorized approver" in denied.stderr
    # The flag only names the approver; the base version still cannot be rolled back.
    allowed = command(root, "--db", db, "--approver", "reviewer", "rollback",
                      "--reviewer", "reviewer", "--reason", "authorized")
    assert allowed.returncode == 2 and "no parent" in allowed.stderr


def test_private_labels_inside_public_export_are_rejected_before_running(tmp_path):
    target = tmp_path / "public"
    export(target)
    labels = target / "expected.json"
    labels.write_text('{"E1":"closed_negative"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "research_loop.evaluate", "--commit", "--labels", str(labels)],
        cwd=target, capture_output=True, text=True, encoding="utf-8", timeout=20,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2
    assert "outside the agent workspace" in result.stderr
