"""Tests for chartctl vp: CLI -> loopback server -> node(volume-profile.js). Offline.

HTTP is stubbed; node and the real repo volume-profile.js run for real.
"""
import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/chart-assistant/scripts'
spec = importlib.util.spec_from_file_location('chartctl', SCRIPTS / 'chartctl.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

CANDLES = [{'time': f'2026-08-{i + 1:02d}', 'open': 100 + i, 'high': 103 + i,
            'low': 99 + i, 'close': 101 + i, 'volume': 1000 + i * 50}
           for i in range(20)]
LOOKUP = {'symbol': 'TST', 'source': 'toss', 'candles': CANDLES}
VP_SRC = (Path(__file__).resolve().parents[1] / 'results/dashboard/volume-profile.js').read_text()


class Resp:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self.raw


def _stub(monkeypatch, lookup_payload):
    def fake(url, timeout=None):
        if url.endswith('/volume-profile.js'):
            return Resp(VP_SRC.encode())
        if '/api/lookup?code=' in url:
            return Resp(json.dumps(lookup_payload).encode())
        raise AssertionError('unexpected url ' + url)
    monkeypatch.setattr(c, 'urlopen', fake)


def test_vp_latest_contract(monkeypatch):
    _stub(monkeypatch, LOOKUP)
    out = c.run_vp('http://127.0.0.1:9', 'TST', None)
    assert out['symbol'] == 'TST' and out['source'] == 'toss'
    assert out['asOf'] == '2026-08-20' and out['index'] == 19
    vp = out['volumeProfile']
    assert (vp['version'], vp['method'], vp['binCount'], vp['count']) == ('vp-1', 'hlc3', 12, 20)
    assert abs(sum(b['share'] for b in vp['bins']) - 1) < 1e-9
    assert out['jsOrigin'] == 'repo-tree'


def test_vp_exact_asof_and_missing(monkeypatch):
    _stub(monkeypatch, LOOKUP)
    out = c.run_vp('http://127.0.0.1:9', 'TST', '2026-08-10')
    try:
        c.run_vp('http://127.0.0.1:9', 'TST', '2026-08-21')
    except RuntimeError as e:
        assert '해당 날짜 봉 없음' in str(e)
    else:
        raise AssertionError('missing date must be rejected')


def test_vp_short_data_null_not_error(monkeypatch):
    _stub(monkeypatch, dict(LOOKUP, candles=CANDLES[:5]))
    out = c.run_vp('http://127.0.0.1:9', 'TST', None)
    assert out['volumeProfile'] is None


def test_vp_empty_candles_and_server_error(monkeypatch):
    _stub(monkeypatch, dict(LOOKUP, candles=[]))
    try:
        c.run_vp('http://127.0.0.1:9', 'BAD', None)
    except RuntimeError as e:
        assert '차트 자료 없음' in str(e)
    else:
        raise AssertionError('empty candles must fail')
    _stub(monkeypatch, {'error': '조회 결과 없음', 'kind': 'nodata'})
    try:
        c.run_vp('http://127.0.0.1:9', 'X', None)
    except RuntimeError as e:
        assert '조회 오류' in str(e)
    else:
        raise AssertionError('server error must fail')


def test_vp_server_fetch_fallback(monkeypatch, tmp_path):
    _stub(monkeypatch, LOOKUP)
    # 저장소 배치가 아닌 경로에서는 서버 정적 파일로 폴백
    src, origin = c._resolve_vp_js(str(tmp_path / 'skills' / 'x' / 'scripts'), 'http://127.0.0.1:9')
    assert origin == 'server:/volume-profile.js' and 'VolumeProfile' in src


def test_skill_copies_identical():
    a = Path(__file__).resolve().parents[1] / 'skills/chart-assistant/scripts/chartctl.py'
    b = Path(__file__).resolve().parents[1] / 'skills/toss-api-skill/scripts/chartctl.py'
    assert a.read_bytes() == b.read_bytes()
