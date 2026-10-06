"""Analysis failures stay isolated and expose safe diagnostic categories."""
import logging
import sqlite3
from types import SimpleNamespace

import pytest
from test_horizontal_patterns import bars, payload
import market_cache
import pattern_service as svc


@pytest.mark.parametrize('error,code',[
    (ValueError('invalid-ohlcv'),'invalid-data'),
    (sqlite3.OperationalError('DO_NOT_LOG_PRIVATE_SQL'),'storage-error'),
    (RuntimeError('DO_NOT_LOG_PRIVATE_PAYLOAD'),'calculation-error'),
])
def test_attach_error_has_location_without_exception_contents(monkeypatch,caplog,error,code):
    monkeypatch.setattr(svc,'enabled',lambda:True)
    monkeypatch.setattr(svc,'flags_enabled',lambda:True)
    monkeypatch.setattr(svc,'triangles_enabled',lambda:True)
    monkeypatch.setattr(market_cache,'enabled',lambda:True)
    monkeypatch.setattr(market_cache,'services',lambda:SimpleNamespace(store=None))
    calls=[]
    def evaluate(data,store,family):
        calls.append(family)
        if family=='triangle':raise error
        return dict(enabled=True,sourceStatus='ready')
    monkeypatch.setattr(svc,'evaluate',evaluate)
    data=payload(bars());data['symbol']='VELO'
    with caplog.at_level(logging.ERROR,logger=svc.__name__):out=svc.attach(data)
    assert out['triangleAnalysis']==dict(enabled=True,sourceStatus='error',errorCode=code)
    assert out['patternAnalysis']['sourceStatus']==out['flagAnalysis']['sourceStatus']=='ready'
    assert calls==['horizontal','flag','triangle'] and 'triangleAnalysis' not in data
    assert 'family=triangle symbol=VELO' in caplog.text
    assert 'test_pattern_diagnostics.py:' in caplog.text
    assert 'DO_NOT_LOG' not in caplog.text and str(data['candles']) not in caplog.text


def test_symbol_cannot_inject_multiline_log(caplog):
    with caplog.at_level(logging.ERROR,logger=svc.__name__):
        svc.analysis_failure(RuntimeError('DO_NOT_LOG'), 'VELO\nFAKE=secret','triangle')
    assert 'symbol=VELO_FAKE=secret' in caplog.text
    assert '\nFAKE' not in caplog.text and 'DO_NOT_LOG' not in caplog.text
