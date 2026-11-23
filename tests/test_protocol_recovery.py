"""Regression coverage for real model failures, without relaxing execution gates."""
import json

import pytest

from evoagents.engine import ActionError, AgentSpec, SessionEngine, _json_object
from evoagents.provider import OutputLimitError, ProviderUnavailable


class Client:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.prompts = []

    def complete(self, messages, *, json_mode=True):
        self.prompts.append(messages)
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return json.dumps(action) if isinstance(action, dict) else action


def team(tmp_path, actions, allowed=None):
    client = Client(actions)
    engine = SessionEngine.create(tmp_path/'team', [AgentSpec('lead','Lead','Coordinate',allowed),
                                                  AgentSpec('dev','Dev','Implement')], client, max_steps=10)
    engine.start_task('Produce and verify a local report')
    return engine, client


def question():
    return {'action':'ask_human','question':'What audience?','reason':'Need the audience'}


def test_shorthand_write_and_read_execute_through_normal_validation(tmp_path):
    engine, _ = team(tmp_path, [
        {'action':'write_file','path':'result.md','content':'Evidence'},
        {'action':'read_file','arguments':{'path':'result.md'}}, question()])
    state=engine.run()
    assert state['status']=='waiting_human'
    assert state['metrics']['normalized_actions']==2
    assert state['metrics']['tool_calls']==2
    assert (engine.tools.workspace('lead')/'result.md').read_text()=='Evidence'


def test_shorthand_cannot_bypass_role_permissions(tmp_path):
    engine, _ = team(tmp_path,[{'action':'write_file','path':'result.md','content':'wrong'},question()],['read_file'])
    result=engine.run()
    assert result['metrics']['invalid_actions']==1
    assert result['metrics']['tool_calls']==0
    assert not (engine.tools.workspace('lead')/'result.md').exists()


def test_shorthand_critical_tool_still_requires_exact_approval(tmp_path):
    engine, _ = team(tmp_path,[{'action':'run_python','path':'script.py'}],['run_python'])
    (engine.tools.workspace('lead')/'script.py').write_text('print(42)')
    result=engine.run()
    assert result['pending']['type']=='tool_approval'
    assert result['pending']['tool']=={'name':'run_python','arguments':{'path':'script.py'}}
    assert result['metrics']['tool_calls']==0


@pytest.mark.parametrize('action',[
    {'action':'write_file','path':'x.md','content':'x','approved':True},
    {'action':'write_file','arguments':{'path':'x.md','content':'x'},'path':'other.md'},
    {'action':'write_file','path':'../escape.md','content':'x'},
])
def test_shorthand_never_drops_unknown_or_conflicting_arguments(tmp_path,action):
    engine, _ = team(tmp_path,[action,question()])
    engine.run()
    assert not (engine.tools.workspace('lead')/'x.md').exists()
    assert not (engine.root/'escape.md').exists()
    assert engine.state['metrics']['invalid_actions']+engine.state['metrics']['tool_errors']>=1


@pytest.mark.parametrize('value', ['{}\n{}','[{"action":"finish"}]','{"action":"tool","name":"write_file","arguments":{"content":"unterminated'])
def test_multiple_or_truncated_actions_are_not_guessed(value):
    with pytest.raises(ActionError):
        _json_object(value)


def test_output_limit_recovers_without_executing_partial_output(tmp_path):
    engine, client=team(tmp_path,[OutputLimitError(8192),{'action':'write_file','path':'small.md','content':'short'},question()])
    result=engine.run()
    assert result['status']=='waiting_human'
    assert result['metrics']['agent_turns']==3
    assert result['metrics']['tool_calls']==1
    assert result['metrics']['output_limit_errors']==1
    assert engine.state['output_limit_streak']==0
    assert 'Previous response was not executed' in client.prompts[1][-1]['content']
    assert (engine.tools.workspace('lead')/'small.md').read_text()=='short'


def test_output_limit_recovery_is_bounded_and_persisted(tmp_path):
    engine, _=team(tmp_path,[OutputLimitError(8192)]*3)
    result=engine.run()
    assert result['status']=='failed'
    assert result['metrics']['agent_turns']==3
    assert result['metrics']['tool_calls']==0
    assert result['metrics']['output_limit_errors']==3
    assert json.loads((engine.root/'state.json').read_text())['output_limit_streak']==3


def test_redundant_self_routing_is_audited_without_changing_dispatch(tmp_path):
    engine, _=team(tmp_path,[{'action':'tool','name':'write_file','arguments':{'path':'x.md','content':'ok'},
                            'recipient':'lead','tool':'write_file','reason':'Save the report','_note':'local'},question()])
    result=engine.run()
    assert result['metrics']['invalid_actions']==0
    assert (engine.tools.workspace('lead')/'x.md').read_text()=='ok'
    assert 'action_annotations_removed' in (engine.root/'events.jsonl').read_text()


@pytest.mark.parametrize('annotation', ['inspect workspace', '', None])
def test_placeholder_annotation_does_not_change_tool_dispatch(tmp_path, annotation):
    engine, _ = team(tmp_path, [{'action':'tool','name':'list_files','arguments':{},'_':annotation},question()])
    result = engine.run()
    assert result['metrics']['tool_calls'] == 1
    assert result['metrics']['invalid_actions'] == 0


@pytest.mark.parametrize('extra',[{'recipient':'dev'},{'approved':True},{'tool':'run_python'},{'reason':{'approved':True}}])
def test_annotations_never_hide_cross_agent_routing_or_approval(tmp_path,extra):
    engine,_=team(tmp_path,[{'action':'tool','name':'write_file','arguments':{'path':'x.md','content':'wrong'},**extra},question()])
    result=engine.run()
    assert result['metrics']['invalid_actions']==1
    assert result['metrics']['tool_calls']==0


def test_large_file_hash_precedes_context_truncation(tmp_path):
    engine,_=team(tmp_path,[{'action':'write_file','path':'large.md','content':'x'*20000},
                          {'action':'read_file','path':'large.md'},question()])
    engine.run()
    tool_messages=[m for m in engine.state['messages'] if m['kind']=='tool_result']
    assert tool_messages[-1]['context_truncated']
    assert 'sha256' in tool_messages[-1]['content']


def test_readonly_roles_receive_usable_reporting_guidance(tmp_path):
    engine,_=team(tmp_path,[],['read_file'])
    assert 'READ-ONLY workspace role' in engine._prompt('lead')[0]['content']
    assert 'artifacts=[]' in engine._prompt('lead')[0]['content']


@pytest.mark.parametrize('action',[
    {'action':'tool','name':'list_files','arguments':{},'path':'.'},
    {'action':'list_files','arguments':{},'path':'.'},
    {'action':'list_files','arguments':{'path':'.'},'path':'.'},
])
def test_unambiguous_schema_fields_have_one_canonical_location(tmp_path, action):
    engine,_=team(tmp_path,[action,question()])
    result=engine.run()
    assert result['metrics']['invalid_actions']==0
    assert result['metrics']['tool_calls']==1


def test_send_file_recipient_is_argument_not_self_routing(tmp_path):
    engine,_=team(tmp_path,[])
    result=engine._normalize_action('lead',{'action':'send_file','path':'a.md','destination':'a.md','recipient':'dev'})
    assert result['arguments']['recipient']=='dev'


def test_working_context_stays_bounded_preserves_recent_evidence_and_isolates_tasks(tmp_path):
    engine, _ = team(tmp_path, [])
    for i in range(40):
        engine._message("dev", f"evidence-{i}:" + "x" * 15000)
    engine._message("tool", "PRIVATE-LEAD-TOOL", recipient="lead", kind="tool_result")
    context = json.loads(engine._prompt("dev")[1]["content"].split("\n", 1)[1])
    assert sum(len(m["content"]) for m in context["messages"]) <= 65000
    assert "evidence-39:" in context["messages"][-1]["content"]
    assert "PRIVATE-LEAD-TOOL" not in json.dumps(context)
    assert any(m["context_truncated"] for m in context["messages"])
    assert "evidence-0:" in (engine.root / "events.jsonl").read_text()
    engine.state["status"] = "completed"
    engine._save()
    engine.start_task("Continue from the prior files")
    context = json.loads(engine._prompt("dev")[1]["content"].split("\n", 1)[1])
    assert all(m["task_id"] == engine.state["task_id"] for m in context["messages"])
    assert context["previous_tasks"][0]["task"] == "Produce and verify a local report"
    assert "evidence-39:" not in json.dumps(context)


def test_prompt_file_example_decodes_to_actual_newlines(tmp_path):
    engine, _ = team(tmp_path, [])
    protocol = engine._prompt("lead")[0]["content"]
    line = next(line for line in protocol.splitlines() if line.startswith("Correct: ") and '"name":"write_file"' in line)
    action = json.loads(line.removeprefix("Correct: "))
    assert action["arguments"]["content"] == "# Report\nEvidence goes here.\n"


def test_low_budget_reminder_preserves_gates_and_correction_order(tmp_path):
    engine, _ = team(tmp_path, [])
    engine.state['turn_limit'] = 120
    engine.state['metrics']['agent_turns'] = 91
    engine._message('system', 'Invalid argument', recipient='lead', kind='action_error')
    prompt = engine._prompt('lead')
    assert '29 team turns remain' in prompt[-2]['content']
    assert 'do not claim success without verification' in prompt[-2]['content']
    assert 'Previous response was not executed' in prompt[-1]['content']
    assert engine.state['turn_limit'] == 120 and engine.state['status'] == 'running'


def test_provider_outage_pauses_and_resumes_without_resetting_work_or_budget(tmp_path):
    engine, _ = team(tmp_path, [{'action':'write_file','path':'saved.md','content':'progress'},
                               ProviderUnavailable('HTTP 503'), question()])
    state = engine.run()
    assert state['status'] == 'waiting_human' and state['pending']['provider_retry']
    assert state['metrics']['fatal_errors'] == 0 and state['metrics']['agent_turns'] == 2
    assert (engine.tools.workspace('lead')/'saved.md').read_text() == 'progress'
    state = engine.respond('Service is available; retry')
    assert state['metrics']['agent_turns'] == 3 and state['metrics']['tool_calls'] == 1
    assert not state['pending'].get('provider_retry')


def test_worker_checkpoints_return_control_without_accepting_or_leaking_tools(tmp_path):
    actions=[{'action':'delegate','recipient':'dev','task':'Research and report','success_criteria':'Evidence'}]
    actions += [{'action':'read_file','path':'research.md'}]*8
    actions += [question()]
    engine,client=team(tmp_path,actions)
    (engine.tools.workspace('dev')/'research.md').write_text('PRIVATE_TOOL_EVIDENCE')
    result=engine.run()
    assert result['status']=='waiting_human'
    assert result['pending']['agent_id']=='lead'
    assert result['metrics']['checkpoints']==1
    assert engine.state['tasks'][0]['status']=='assigned'
    assert 'PRIVATE_TOOL_EVIDENCE' not in json.dumps(client.prompts[-1])
    assert any(m['kind']=='checkpoint' for m in engine.state['messages'])
