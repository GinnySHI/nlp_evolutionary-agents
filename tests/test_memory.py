import json

import pytest

from evoagents.memory import AgentMemory, atomic_json, redact


def test_scoped_retrieval_and_persistence(tmp_path):
    memory = AgentMemory(tmp_path / "one")
    memory.add("The blue banana is confidential.", scope="private")
    memory.add("Validate booking overlaps before saving.", outcome="accepted", kind="episode")
    memory.add("Run overlap checks for each room.")
    reloaded = AgentMemory(tmp_path / "one")
    group = reloaded.retrieve("blue banana room")
    assert all(item["scope"] == "group" for item in group)
    assert "banana" not in json.dumps(group)
    assert "banana" in json.dumps(reloaded.retrieve("banana", scope="private"))
    assert reloaded.stats()["successes"] == 1
    assert reloaded.stats()["lessons"] == 1


def test_corrupt_tail_does_not_discard_old_memory(tmp_path):
    memory = AgentMemory(tmp_path)
    memory.add("A valid lesson")
    with (tmp_path / "group.jsonl").open("a") as stream:
        stream.write('{"truncated":')
    assert len(memory.entries()) == 1


def test_chinese_relevance(tmp_path):
    memory = AgentMemory(tmp_path)
    memory.add("预订会议室前先检查时间冲突")
    memory.add("核实新闻来源")
    assert "会议室" in memory.retrieve("会议室预订冲突", limit=1)[0]["text"]


def test_redaction_and_atomic_save(tmp_path):
    secret = "sk-" + "A" * 24
    atomic_json(tmp_path / "state.json", {"message": secret, "api_key": "any-secret"})
    saved = (tmp_path / "state.json").read_text()
    assert secret not in saved
    assert "any-secret" not in saved
    assert "REDACTED" in saved
    assert not list(tmp_path.glob("*.tmp"))
    assert "secret" not in redact("Authorization: Bearer secret")


def test_memory_scope_validation(tmp_path):
    memory = AgentMemory(tmp_path)
    with pytest.raises(ValueError):
        memory.add("data", scope="../other")
