"""Offline checks only. No real credentials or live network calls."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock
import io
import sys
import urllib.error
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

spec = importlib.util.spec_from_file_location('toss_market', Path(__file__).resolve().parents[1] / 'scripts/toss_market.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_credentials_external_file(tmp_path, monkeypatch):
    file = tmp_path / 'test.txt'
    file.write_text('Open API\nClient Id: dummy-id\nClient Secret: dummy-secret\n')
    monkeypatch.setenv('TOSS_CREDENTIALS_FILE', str(file))
    assert m.read_credentials() == {'id': 'dummy-id', 'secret': 'dummy-secret'}


def test_token_reused_in_memory(monkeypatch):
    monkeypatch.setattr(m, 'read_credentials', lambda: {'id': 'dummy-id', 'secret': 'dummy-secret'})
    c = m.TossClient()
    c._request = Mock(return_value={'access_token': 'dummy-token', 'expires_in': 86400})
    assert c.token() == c.token() == 'dummy-token'
    assert c._request.call_count == 1


def test_account_and_orders_not_enabled():
    c = m.TossClient()
    c.token = Mock(side_effect=AssertionError('must not authenticate'))
    for path in ['/api/v1/orders', '/api/v1/accounts']:
        with pytest.raises(m.TossError, match='endpoint-not-enabled'):
            c.get(path)


def test_error_body_and_token_not_exposed(monkeypatch):
    error = urllib.error.HTTPError('https://openapi.tossinvest.com/api/v1/prices', 403,
                                  'secret-body', {}, io.BytesIO(b'dummy-secret dummy-token'))
    monkeypatch.setattr(m.urllib.request, 'urlopen', Mock(side_effect=error))
    with pytest.raises(m.TossError) as e:
        m.TossClient()._request('/api/v1/prices', token='dummy-token')
    assert e.value.status == 403
    assert 'dummy' not in str(e.value)
    assert 'secret' not in str(e.value)


def test_rate_limit_retry_metadata_and_counters_are_safe(monkeypatch):
    error = urllib.error.HTTPError('https://openapi.tossinvest.com/api/v1/candles?symbol=AAPL',
                                  429, 'private', {'Retry-After': '180'}, io.BytesIO(b'dummy-secret'))
    monkeypatch.setattr(m.urllib.request, 'urlopen', Mock(side_effect=error))
    client = m.TossClient()
    with pytest.raises(m.TossError) as failure:
        client._request('/api/v1/candles', params={'symbol': 'AAPL'}, token='dummy-token')
    assert failure.value.retry_after == 180
    assert failure.value.retry_at is not None
    metrics = client.metrics.snapshot()
    row = metrics['/api/v1/candles']
    assert (row['calls'], row['failures'], row['inFlight']) == (1, 1, 0)
    assert row['statuses'] == {'429': 1}
    assert row['lastErrorKind'] == 'rate-limited'
    assert 'dummy' not in str(metrics) and 'AAPL' not in str(metrics)


def test_invalid_retry_header_is_ignored(monkeypatch):
    error = urllib.error.HTTPError('https://example.invalid', 429, '', {'Retry-After': 'secret'}, None)
    monkeypatch.setattr(m.urllib.request, 'urlopen', Mock(side_effect=error))
    with pytest.raises(m.TossError) as failure:
        m.TossClient()._request('/api/v1/candles')
    assert failure.value.retry_after is None


def test_network_failure_counters_close_inflight(monkeypatch):
    monkeypatch.setattr(m.urllib.request, 'urlopen', Mock(side_effect=TimeoutError))
    client = m.TossClient()
    with pytest.raises(m.TossError):
        client._request('/api/v1/prices')
    row = client.metrics.snapshot()['/api/v1/prices']
    assert row['inFlight'] == 0 and row['statuses'] == {'network': 1}


def test_symbol_mapping():
    assert m.toss_symbol('005930.KS') == '005930'
    assert m.toss_symbol('aapl') == 'AAPL'
    with pytest.raises(m.TossError):
        m.toss_symbol('BTC-USD')


def test_candle_order_boundary_and_zero_volume():
    row = {'timestamp':'2026-09-07T09:00:00+09:00','openPrice':'100','highPrice':'110',
           'lowPrice':'90','closePrice':'105','volume':'0'}
    older = dict(row, timestamp='2026-09-04T09:00:00+09:00')
    out = m.normalize_candles([row, older, row], 'Asia/Seoul')
    assert [r['t'] for r in out] == ['2026-09-04','2026-09-07']
    assert out[-1]['volume'] == 0
    with pytest.raises(m.TossError):
        m.normalize_candles([dict(row, closePrice=None)], 'Asia/Seoul')
    with pytest.raises(m.TossError):
        m.normalize_candles([dict(row, highPrice='95')], 'Asia/Seoul')


def test_candle_refresh_replaces_corrected_history():
    row = {'timestamp':'2026-09-04T09:00:00+09:00','openPrice':'100','highPrice':'110',
           'lowPrice':'90','closePrice':'105','volume':'0'}
    client = Mock()
    client.get.return_value = {'candles':[row], 'nextBefore':None}
    store = m.CandleStore(client)
    assert store.daily('005930.KS','Asia/Seoul')[0][0]['close'] == 105
    client.get.return_value = {'candles':[dict(row, closePrice='104')], 'nextBefore':None}
    assert store.daily('005930.KS','Asia/Seoul', force=True)[0][0]['close'] == 104

def test_candle_cache_hit_preserves_source_fetched_at():
    row = {'timestamp':'2026-09-04T09:00:00+09:00','openPrice':'100','highPrice':'110',
           'lowPrice':'90','closePrice':'105','volume':'0'}
    client = Mock()
    client.get.return_value = {'candles':[row], 'nextBefore':None}
    store = m.CandleStore(client)
    _, cached_first, fetched_first = store.daily('005930.KS','Asia/Seoul', force=True)
    _, cached_second, fetched_second = store.daily('005930.KS','Asia/Seoul')
    assert cached_first is False
    assert cached_second is True
    assert fetched_second == fetched_first


def stream_module():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import toss_stream
    return toss_stream


def test_trade_shape_and_private_topics_ignored():
    stream = stream_module()
    event = {'type':'message','topic':'trade:us:AAPL',
             'data':{'price':'243.26','volume':'8','timestamp':'2026-09-07T21:30:00+09:00','currency':'USD'}}
    assert stream.normalize_trade(event)['price'] == 243.26
    assert stream.normalize_trade(dict(event,topic='personal:order:3')) is None
    bad = dict(event, data=dict(event['data'],price='NaN'))
    assert stream.normalize_trade(bad) is None
    assert stream.topic_for('005930.KS') == 'trade:kr:005930'


def test_stream_symbol_isolation_and_bounded_queue():
    import queue
    stream = stream_module()
    hub = stream.TradeHub()
    a,b = queue.Queue(maxsize=2),queue.Queue(maxsize=2)
    hub.listeners = {a:'trade:us:AAPL',b:'trade:kr:005930'}
    for value in range(4):hub.publish({'n':value},'trade:us:AAPL')
    assert b.empty()
    assert [a.get()['n'],a.get()['n']] == [2,3]


def test_second_listener_gets_existing_ack(monkeypatch):
    stream = stream_module()
    hub = stream.TradeHub()
    hub.thread = Mock()
    hub.thread.is_alive.return_value = True
    hub.status = 'connected'
    hub.accepted = {'trade:us:AAPL'}
    listener = hub.subscribe('AAPL')
    assert listener.get()['state'] == 'subscribed'
    hub.unsubscribe(listener)
