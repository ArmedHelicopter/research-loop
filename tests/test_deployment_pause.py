from research_loop.cli import export
from test_agent_cli import command


def test_pause_rejects_live_entry_before_database_mutation_and_survives_export(tmp_path):
    public = tmp_path / "public"
    export(public)
    (public / ".research-loop-paused").write_text("one-day evidence insufficient", encoding="utf-8")
    for operation in ("run", "enqueue", "promote"):
        args = {"run": [], "enqueue": ["missing.json"], "promote": ["trial", "--reviewer", "operator"]}[operation]
        result = command(public, operation, *args)
        assert result.returncode == 2 and "independent_review" in result.stderr
        assert not (public / "state.sqlite").exists()
    copied = tmp_path / "next-public"
    assert command(public, "export", str(copied)).returncode == 0
    assert (copied / ".research-loop-paused").read_bytes() == (public / ".research-loop-paused").read_bytes()
    assert command(copied, "run").returncode == 2
