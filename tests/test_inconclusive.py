from research_loop.agent import Agent
from research_loop.cli import toy_task
from research_loop.ontology import Task
from research_loop.provider import Call, FixtureProvider, fixture_role_providers
from research_loop.store import Store


class Uncertain(FixtureProvider):
    def call(self, role, payload):
        response = super().call(role, payload)
        value = {**response.value, "status": "inconclusive"}
        return Call(value, 0, 0, 0.0)


def test_audit_valid_preserves_inconclusive_without_positive_admission(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    try:
        agent = Agent(store)
        agent.initialize()
        agent.enqueue(Task.parse(toy_task("uncertain", "development-uncertainty")))
        _, auditor1, auditor2 = fixture_role_providers()
        result = agent.run_next(Uncertain(), auditor_provider=auditor1, auditor2_provider=auditor2)
        assert result["state"] == "closed"
        assert result["status"] == "inconclusive"
        assert result["audit_valid"] is True
        assert result["evidence_admitted"] is False
        assert result["protocol_violations"] == []
    finally:
        store.close()
