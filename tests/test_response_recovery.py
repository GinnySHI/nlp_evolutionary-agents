"""Recovery from serving-stack noise around an otherwise complete action.

Observed on deepseek-flash: trailing commentary after a valid object, leaked
internal tool-call markup, and unterminated objects. Recovery must never
become repair, and must never choose between two candidate actions.
"""
from __future__ import annotations

import pytest

from evoagents.engine import ActionError, _json_object


def test_plain_object_is_unchanged():
    value, note = _json_object('{"action":"message","recipient":"group","content":"hi"}')
    assert value["action"] == "message" and note == ""


def test_fenced_object_is_accepted():
    value, note = _json_object('```json\n{"action":"finish","summary":"done","success":true}\n```')
    assert value["success"] is True and note == ""


def test_trailing_commentary_after_a_complete_object_is_ignored():
    value, note = _json_object(
        '{"action":"tool","name":"list_files","arguments":{}}  Note: I will assume that returns the files.')
    assert value == {"action": "tool", "name": "list_files", "arguments": {}}
    assert "ignored" in note


def test_leaked_internal_markup_after_an_object_is_ignored():
    value, note = _json_object('{}</｜｜DSML｜｜ parameter> </｜｜DSML｜｜ invoke>')
    assert value == {} and "ignored" in note


def test_leading_prose_before_the_object_is_ignored():
    value, note = _json_object('Here is my action: {"action":"remember","lesson":"Check the inbox path."}')
    assert value["action"] == "remember" and "leading text" in note


def test_two_action_objects_are_rejected_rather_than_narrowed():
    with pytest.raises(ActionError, match="exactly one action object"):
        _json_object('{"action":"message","recipient":"group","content":"a"}'
                     '{"action":"finish","summary":"b","success":true}')


def test_two_objects_separated_by_prose_are_also_rejected():
    with pytest.raises(ActionError, match="exactly one action object"):
        _json_object('{"action":"message","recipient":"group","content":"a"} or maybe '
                     '{"action":"finish","summary":"b","success":true}')


@pytest.mark.parametrize("noise", ["note {invalid} ", "note { ", "note {invalid} {still invalid} "])
def test_malformed_brace_noise_cannot_hide_a_second_action(noise):
    with pytest.raises(ActionError, match="exactly one action object"):
        _json_object('{"action":"message","recipient":"group","content":"a"}' + noise +
                     '{"action":"finish","summary":"b","success":true}')


def test_malformed_brace_noise_without_another_object_is_ignored():
    value, note = _json_object('{"action":"message","recipient":"group","content":"a"} note {invalid}')
    assert value["content"] == "a" and "ignored" in note


def test_ambiguous_response_executes_neither_action(tmp_path):
    from evoagents.engine import AgentSpec, SessionEngine

    class Ambiguous:
        stats: dict = {}

        def complete(self, messages, *, json_mode=True):
            return ('{"action":"tool","name":"write_file","arguments":{"path":"first.md","content":"first"}}'
                    ' note {invalid} '
                    '{"action":"tool","name":"write_file","arguments":{"path":"second.md","content":"second"}}')

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"), AgentSpec(id="w", name="W", role="Write")],
        Ambiguous(), max_steps=1)
    engine.start_task("Save one file.")
    engine.run()
    assert engine.status()["metrics"]["invalid_actions"] == 1
    assert engine.status()["metrics"]["tool_calls"] == 0
    assert not (engine.tools.workspace("lead") / "first.md").exists()
    assert not (engine.tools.workspace("lead") / "second.md").exists()


def test_unterminated_object_is_not_repaired():
    with pytest.raises(ActionError, match="Invalid JSON response"):
        _json_object('{"action":"tool","name":"list_files","arguments":{}')


def test_text_without_any_object_is_rejected():
    with pytest.raises(ActionError, match="Invalid JSON response"):
        _json_object("I will now list the files in the workspace.")


def test_non_object_json_array_is_rejected_as_data():
    with pytest.raises(ActionError, match="JSON array of data"):
        _json_object('["action","message"]')


def test_non_object_scalar_json_is_rejected():
    with pytest.raises(ActionError, match="one JSON object"):
        _json_object('42')


def test_non_object_json_with_trailing_text_is_rejected():
    with pytest.raises(ActionError):
        _json_object('"just a string" and then some words')


def test_json_constants_are_still_rejected():
    with pytest.raises(ActionError):
        _json_object('{"action":"complete","summary":"x","artifacts":[],"success":NaN}')


def test_oversized_response_is_rejected():
    with pytest.raises(ActionError, match="100000 characters"):
        _json_object('{"a":"' + "x" * 100_001 + '"}')


def test_recovered_response_is_counted_and_audited(tmp_path):
    """A recovered turn still executes, and the recovery is visible in the audit."""
    import json as _json

    from evoagents.engine import AgentSpec, SessionEngine

    class Noisy:
        stats: dict = {}

        def complete(self, messages, *, json_mode=True):
            return ('{"action":"message","recipient":"group","content":"hello"}'
                    '  </｜｜DSML｜｜ invoke>')

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate"), AgentSpec(id="w", name="W", role="Write")],
        Noisy(), max_steps=1)
    engine.start_task("Say hello to the group.")
    engine.run()
    assert engine.status()["metrics"]["recovered_responses"] == 1
    assert engine.status()["metrics"]["invalid_actions"] == 0
    kinds = [_json.loads(line).get("kind") for line in (tmp_path / "s" / "events.jsonl").read_text().splitlines()]
    assert "response_recovered" in kinds


def test_a_bare_data_array_is_named_as_such_not_as_two_actions():
    """The 22 most common wasted turns in the course run were data arrays."""
    rooms = '[{"id":"atlas","name":"Atlas","capacity":8},{"id":"birch","name":"Birch","capacity":6}]'
    with pytest.raises(ActionError, match="JSON array of data"):
        _json_object(rooms)


def test_a_truncated_data_array_is_also_named_as_such():
    with pytest.raises(ActionError, match="JSON array of data"):
        _json_object('[{"id":"atlas","name":"Atlas"},{"id":"birch","name":"Bir')


def test_data_array_guidance_points_at_write_file():
    with pytest.raises(ActionError) as caught:
        _json_object('[1, 2, 3]')
    assert "write_file" in str(caught.value)


def test_two_real_actions_still_report_the_ambiguity():
    with pytest.raises(ActionError, match="exactly one action object"):
        _json_object('{"action":"message","recipient":"group","content":"a"}'
                     '{"action":"finish","summary":"b","success":true}')


def test_plain_note_field_is_stripped_like_reason(tmp_path):
    from evoagents.engine import AgentSpec, SessionEngine

    class Fake:
        def complete(self, messages, *, json_mode=True):
            return '{"action":"list_files","arguments":{},"note":"checking state first"}'

    engine = SessionEngine.create(
        tmp_path / "s",
        [AgentSpec(id="lead", name="Lead", role="Coordinate", allowed_tools=["list_files"]),
         AgentSpec(id="w", name="W", role="Write")],
        Fake(), max_steps=1)
    engine.start_task("Inspect the workspace.")
    engine.run()
    assert engine.status()["metrics"]["invalid_actions"] == 0
    assert engine.status()["metrics"]["tool_calls"] == 1
