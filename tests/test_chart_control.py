import importlib.util
from pathlib import Path
import time
import pytest
spec=importlib.util.spec_from_file_location('chart_control',Path(__file__).resolve().parents[1]/'scripts/chart_control.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_ack_is_required_and_not_replayed():
    s=mod.ControlStore();s.register({'tab':'abcdefgh','snapshot':{'symbol':'AAPL'}})
    c=s.submit({'action':'inspect'})
    assert c['status']=='queued'
    assert s.register({'tab':'abcdefgh'})['command']['id']==c['id']
    assert s.register({'tab':'abcdefgh'})['command'] is None
    result=s.result({'id':c['id'],'tab':'abcdefgh','snapshot':{'symbol':'AAPL'}})
    assert result['status']=='done' and result['result']['symbol']=='AAPL'

def test_expired_command_never_runs():
    s=mod.ControlStore();s.register({'tab':'abcdefgh'})
    c=s.submit({'action':'view','args':{'period':'6M'}})
    s.commands[c['id']]['deadline']=time.time()-1
    assert s.register({'tab':'abcdefgh'})['command'] is None
    assert s.commands[c['id']]['status']=='expired'

def test_tab_isolation_ambiguity_and_busy():
    s=mod.ControlStore();s.register({'tab':'abcdefgh'});s.register({'tab':'ijklmnop'})
    with pytest.raises(ValueError):s.submit({'action':'inspect'})
    c=s.submit({'action':'inspect','tab':'abcdefgh'})
    assert s.register({'tab':'ijklmnop'})['command'] is None
    with pytest.raises(ValueError):s.submit({'action':'view','tab':'abcdefgh'})
    with pytest.raises(ValueError):s.result({'id':c['id'],'tab':'ijklmnop'})

@pytest.mark.parametrize('body',[{'action':'order'}, {'action':'view','args':{'javascript':'alert(1)'}},{'action':'view','args':{'symbol':'a/b'}},{'action':'auto','args':{'enabled':'yes'}},{'action':'view','args':{'asOf':'yesterday'}}])
def test_reject_unsupported_commands(body):
    s=mod.ControlStore();s.register({'tab':'abcdefgh'})
    with pytest.raises(ValueError):s.submit(body)
