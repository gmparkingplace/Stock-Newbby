"""CPU 최적화가 전체 결과·인과성·수정 봉 반영을 보존하는지 검사한다."""
import sys
from pathlib import Path
from copy import deepcopy
import random
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pattern_math
import flag_patterns
import triangle_patterns
import structure_patterns


def bars(n=170, seed=17):
    from datetime import date, timedelta
    rng=random.Random(seed);close=100.;out=[]
    for i in range(n):
        start=close;close=max(20,close+rng.uniform(-2,2))
        out.append(dict(time=(date(2025,1,1)+timedelta(days=i)).isoformat(),open=start,
                        high=max(start,close)+rng.uniform(.1,2),low=min(start,close)-rng.uniform(.1,2),
                        close=close,volume=rng.randint(500,2000)))
    return out


def test_prefix_pivots_equal_original_each_bar_and_no_future():
    rows=bars();prefix=pattern_math.pivot_prefix(rows)
    for i in range(len(rows)):
        assert prefix(i)==pattern_math.pivots(rows,i)
        assert prefix(i)==pattern_math.pivots(rows[:i+1],i)
    hi,lo=prefix(len(rows)-1);hi.clear();lo.clear()
    assert prefix(len(rows)-1)==pattern_math.pivots(rows,len(rows)-1)


@pytest.mark.parametrize('module',[flag_patterns,triangle_patterns])
@pytest.mark.parametrize('seed',[1,17,41])
def test_fast_prefix_preserves_all_output(module,seed,monkeypatch):
    rows=bars(seed=seed);original=deepcopy(rows)
    actual=module.analyze(rows,'TEST',rows[-2]['time'],True)
    monkeypatch.setattr(module,'pivot_prefix',lambda data:lambda i:pattern_math.pivots(data,i))
    expected=module.analyze(rows,'TEST',rows[-2]['time'],True)
    assert actual==expected and rows==original
    # 수정 봉은 새 호출에서 반영하며 이전 인덱스를 재사용하지 않는다.
    rows[30]['high']+=20
    slow=module.analyze(rows,'TEST',rows[-2]['time'],True)
    monkeypatch.setattr(module,'pivot_prefix',pattern_math.pivot_prefix)
    assert module.analyze(rows,'TEST',rows[-2]['time'],True)==slow


def test_neckline_cache_is_call_local_and_exact(monkeypatch):
    rows=bars(220);original=deepcopy(rows)
    actual=structure_patterns.analyze(rows,'TEST',rows[-1]['time'])
    # 함수 본문에서 국소 캐시만 제거한 기준 구현과 완전 동일한 결과를 비교한다.
    import inspect
    source=inspect.getsource(structure_patterns.analyze)
    source=source.replace('neckline_for(i1, i2, side)','_neckline(rows, i1, i2, side)').replace('neckline_for(il, ir, side)','_neckline(rows, il, ir, side)')
    namespace=dict(structure_patterns.__dict__);exec(source,namespace)
    assert actual==namespace['analyze'](rows,'TEST',rows[-1]['time'])
    assert rows==original
    rows[80]['low']-=10
    assert structure_patterns.analyze(rows,'TEST',rows[-1]['time'])==namespace['analyze'](rows,'TEST',rows[-1]['time'])
