from evoagents.validation import validate_text
from evoagents.tools import ToolRunner


def test_validator_detects_duplicate_documents_and_controls():
    html='<html><head></head><body><button id="next">Next</button></body></html>'
    assert validate_text('deck.html',html)['valid']
    result=validate_text('deck.html',html+html)
    assert not result['valid']
    assert any('Duplicate element IDs' in e for e in result['errors'])
    assert any('after' in e for e in result['errors'])


def test_date_risk_is_advisory_not_false_functional_verdict():
    html='<html><head></head><body><script>new Date(d+"T00:00:00").toISOString()</script></body></html>'
    result=validate_text('dashboard.html',html)
    assert result['valid'] and any('shift' in x for x in result['warnings'])
    assert 'Does not execute' in result['scope']


def test_static_python_check_never_executes(tmp_path):
    runner=ToolRunner(tmp_path/'agents',agent_ids=['dev','qa'])
    runner.execute('dev','write_file',{'path':'script.py','content':'open("executed.txt","w").write("bad")'})
    assert runner.execute('dev','validate_file',{'path':'script.py'})['valid']
    assert not (runner.workspace('dev')/'executed.txt').exists()
    assert not runner.execute('qa','validate_file',{'path':'script.py'})['ok']
    assert not runner.execute('dev','validate_file',{'path':'../script.py'})['ok']
    assert not validate_text('script.py','if True:\ninvalid')['valid']
    assert not validate_text('config.json','{"x":NaN}')['valid']
