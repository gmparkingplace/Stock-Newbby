"""비동기 계산 중 동기 감시가 게시해도 수집 시각을 과거로 되돌리지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pattern_service
from market_store import MarketStore
from test_horizontal_patterns import bars, payload


def test_same_revision_newer_publication_wins_over_late_old_work(tmp_path, monkeypatch):
    store = MarketStore(tmp_path / 'publication.sqlite3')
    now = datetime(2026, 2, 1, 23, tzinfo=timezone.utc)
    source = payload(bars(100))
    source['fetchedAt'] = '2026-02-01T22:00:00+00:00'
    analyze = pattern_service.analyze
    calls = []
    try:
        # 같은 자료 개정이 이미 게시되어 있는 상태에서 새 계산을 시작한다.
        pattern_service.evaluate(source, store, now=now)
        source['snapshotEligible'] = not source.get('snapshotEligible', False)
        # signature를 바꿔 캐시 재사용 대신 계산 경합을 재현한다.
        source['lastConfirmedTime'] = source['candles'][-2]['time']
        levels = pattern_service.get_settings(store, source['symbol'])
        key = pattern_service.result_key(source['symbol'], levels)
        def interleave(*args, **kwargs):
            result = analyze(*args, **kwargs)
            current = deepcopy(store.pattern_result(key))
            current['sourceFetchedAt'] = '2026-02-01T22:30:00+00:00'
            # 다른 동기 호출이 동일 개정·더 새 수집시각의 결과를 게시한다.
            store.pattern_publish(key, current, [])
            calls.append(1)
            return result
        monkeypatch.setattr(pattern_service, 'analyze', interleave)
        pattern_service.evaluate(source, store, now=now)
        assert calls == [1]
        assert store.pattern_result(key)['sourceFetchedAt'] == '2026-02-01T22:30:00+00:00'
    finally:
        store.close()
