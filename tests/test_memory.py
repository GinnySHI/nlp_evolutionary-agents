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


@pytest.mark.parametrize("query", ["unrelated topic", "", "?!", "会议室冲突"])
def test_unrelated_or_empty_queries_do_not_inject_old_memory(tmp_path, query):
    memory = AgentMemory(tmp_path)
    memory.add("Validate booking overlaps before saving.")
    assert memory.retrieve(query) == []


def test_weakly_relevant_episode_ranks_above_unrelated_lessons(tmp_path):
    memory = AgentMemory(tmp_path)
    episode = memory.add("booking " + " ".join(f"detail{i}" for i in range(100)), kind="episode", outcome="failed")
    for index in range(8):
        memory.add(f"Verify news sources carefully {index}")
    assert [item["id"] for item in memory.retrieve("booking")] == [episode["id"]]


def test_lesson_bonus_does_not_override_stronger_relevance(tmp_path):
    memory = AgentMemory(tmp_path)
    episode = memory.add("booking " + " ".join(f"detail{i}" for i in range(40)), kind="episode")
    memory.add("booking " + " ".join(f"detail{i}" for i in range(100)))
    assert memory.retrieve("booking", limit=1)[0]["id"] == episode["id"]


def test_equal_relevance_prefers_lessons_then_recent_records(tmp_path):
    memory = AgentMemory(tmp_path)
    memory.add("booking conflict")
    latest_lesson = memory.add("booking conflict")
    memory.add("booking conflict", kind="episode")
    assert memory.retrieve("booking conflict", limit=1)[0]["id"] == latest_lesson["id"]


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


def test_retrieval_deduplicates_experience_without_changing_audit(tmp_path):
    memory = AgentMemory(tmp_path)
    first = memory.add("Check booking conflicts", task_id="first")
    latest = memory.add("Check  booking\nconflicts", task_id="second")
    memory.add("Check booking availability")
    results = memory.retrieve("booking conflicts", limit=2)
    assert len(results) == 2
    merged = results[0]
    assert merged["id"] == latest["id"]
    assert merged["occurrences"] == 2
    assert [source["id"] for source in merged["sources"]] == [first["id"], latest["id"]]
    assert [source["task_id"] for source in merged["sources"]] == ["first", "second"]
    assert len(memory.entries()) == 3


def test_deduplication_preserves_scope_kind_and_outcome(tmp_path):
    memory = AgentMemory(tmp_path)
    memory.add("booking conflict", scope="private", task_id="secret")
    memory.add("booking conflict", kind="episode", outcome="failed")
    memory.add("booking conflict", kind="episode", outcome="accepted")
    memory.add("booking conflict", kind="lesson")
    results = memory.retrieve("booking conflict")
    assert len(results) == 3
    assert all(item["occurrences"] == 1 and item["scope"] == "group" for item in results)
    assert "secret" not in json.dumps(results)


def test_duplicate_provenance_is_bounded_and_survives_reload(tmp_path):
    memory = AgentMemory(tmp_path)
    for index in range(15):
        memory.add("booking conflict", task_id=str(index))
    result = AgentMemory(tmp_path).retrieve("booking conflict")[0]
    assert result["occurrences"] == 15
    assert len(result["sources"]) == 10
    assert result["sources"][0]["task_id"] == "5"
    assert len(memory.entries()) == 15
