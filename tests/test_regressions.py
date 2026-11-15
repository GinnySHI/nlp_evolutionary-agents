from types import SimpleNamespace

from evoagents.cli import main
from evoagents.evaluation import check_artifacts


def test_truncated_read_cannot_prove_full_text_equality():
    class Tools:
        def execute(self, *args):
            return {"ok": True, "content": "matching prefix", "truncated": True}
    result = check_artifacts(SimpleNamespace(tools=Tools()), [
        {"type": "text_equals", "agent": "writer", "path": "report.md", "text": "matching prefix"}
    ])
    assert result[0]["passed"] is False
    assert "truncated" in result[0]["error"]


def test_custom_agent_types_fail_cleanly_before_creating_session(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HKGAI_BASE_URL", raising=False)
    agents = tmp_path / "agents.json"
    agents.write_text('[{"id":"lead","name":42,"role":"coordinate"},{"id":"worker","name":"worker","role":"work"}]')
    assert main(["init", "bad-team", "--agents", str(agents)]) == 1
    assert "Custom agents" in capsys.readouterr().err
