"""Descriptive evidence for structure candidates.

Nothing here blocks or promotes a pattern. Numbers are returned with their
sample size and an explicit `unknown` when the history is too short, so a
missing baseline cannot masquerade as weak or strong volume.

Reason codes are shared by the API and the dashboard; the Korean text lives in
one place so the server and UI cannot drift apart.
"""
from structure_geometry_v2 import neckline_at

REASONS = {
    'candidate-detected': '극점과 목선이 확인되어 후보로 기록했습니다.',
    'breakout-confirmed': '종가가 기준가를 넘어 구조 확인 사건을 기록했습니다.',
    'close-beyond-trigger': '종가가 기준가를 넘어 확인 조건을 충족했습니다.',
    'close-at-trigger': '종가가 기준가와 같아 다음 확정 봉을 기다립니다.',
    'close-short-of-trigger': '종가가 기준가에 미달해 아직 확인 전입니다.',
    'close-back-inside-trigger': '확인 뒤 종가가 기준가 안쪽으로 돌아왔습니다.',
    'volume-supported': '해당 봉 거래량이 직전 평균을 뚜렷이 넘었습니다.',
    'volume-weak': '해당 봉 거래량이 직전 평균을 뚜렷이 넘지 않았습니다.',
    'volume-unknown': '비교할 거래량 표본이 부족합니다.',
    'volume-boosted-later': '확인 뒤 거래량을 동반한 재돌파가 나타났습니다.',
    'prior-trend-up': '구조 형성 전 흐름은 상승이었습니다.',
    'prior-trend-down': '구조 형성 전 흐름은 하락이었습니다.',
    'prior-trend-flat': '구조 형성 전 흐름은 뚜렷하지 않았습니다.',
    'prior-trend-unknown': '구조 형성 전 흐름을 판단할 봉이 부족합니다.',
    'reversal-context': '형성 전 흐름과 반대 방향의 확인이라 반전 구조로 볼 수 있습니다.',
    'continuation-risk': '형성 전 흐름과 같은 방향의 확인이라 추세 지속일 수 있습니다.',
    'retest-in-progress': '기준선을 다시 시험하는 중입니다.',
    'retest-held': '기준선 재시험 뒤 방향을 유지했습니다.',
    'breakout-failed': '종가가 무효 기준을 넘어 구조가 무효화됐습니다.',
    'candidate-invalidated': '확인 전에 구조가 무효화됐습니다.',
    'candidate-expired': '확인 전 후보 기한이 끝났습니다.',
    'tracking-expired': '확인 뒤 추적 기한이 끝났습니다.',
}


def describe(code):
    return REASONS.get(code, code)


def depth(rows, candidate):
    """Depth from the extreme peak/head to the neckline at the last anchor."""
    last_index = candidate['peaks'][-1][0]
    anchor = neckline_at(candidate, last_index)
    prices = [price for _, price in candidate['peaks']]
    extreme = max(prices) if candidate['sign'] == -1 else min(prices)
    gap = abs(extreme - anchor)
    return dict(abs=gap, pct=gap / extreme * 100, atr=gap / candidate['atr0'])


def prior_trend(rows, structure_start, cfg):
    """Closes strictly before the first anchor. Never includes the pattern."""
    end = structure_start
    begin = max(0, end - cfg['priorTrendBars'])
    count = end - begin
    unknown = dict(available=False, bars=max(0, count), returnPct=None,
                   slopePctPerBar=None, direction='unknown', reversalContext=None)
    if count < cfg['priorTrendMinBars']:
        return unknown
    first, last = rows[begin]['close'], rows[end - 1]['close']
    if first <= 0:
        return unknown
    return_pct = (last - first) / first * 100
    xs = range(count)
    ys = [rows[begin + k]['close'] for k in range(count)]
    x_mean, y_mean = (count - 1) / 2, sum(ys) / count
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator if denominator else 0
    direction = ('up' if return_pct >= cfg['flatTrendPct']
                 else 'down' if return_pct <= -cfg['flatTrendPct'] else 'flat')
    return dict(available=True, bars=count, returnPct=return_pct,
                slopePctPerBar=slope / y_mean * 100 if y_mean else None,
                direction=direction, reversalContext=None)


def trend_for(rows, candidate, cfg):
    trend = prior_trend(rows, candidate['peaks'][0][0], cfg)
    if not trend['available'] or trend['direction'] in ('flat', 'unknown'):
        trend['reversalContext'] = None
        return trend
    trend['reversalContext'] = (
        (candidate['sign'] == -1 and trend['direction'] == 'up') or
        (candidate['sign'] == 1 and trend['direction'] == 'down'))
    return trend


def formation_volume(rows, candidate):
    start, end = candidate['peaks'][0][0], candidate['peaks'][-1][0]
    middle = (start + end) // 2
    first = [rows[k]['volume'] for k in range(start, middle + 1)]
    second = [rows[k]['volume'] for k in range(middle + 1, end + 1)]
    if not first or not second:
        return dict(firstHalfMean=None, secondHalfMean=None, ratio=None, status='unknown')
    first_mean = sum(first) / len(first)
    second_mean = sum(second) / len(second)
    ratio = second_mean / first_mean if first_mean > 0 else None
    return dict(firstHalfMean=first_mean, secondHalfMean=second_mean,
                ratio=ratio, status='measured' if ratio is not None else 'unknown')


def volume_ratio(rows, index, cfg):
    bars = cfg['volumeBaselineBars']
    if index < bars:
        return None, 'unknown'
    baseline = sum(rows[k]['volume'] for k in range(index - bars, index)) / bars
    if baseline <= 0:
        return None, 'unknown'
    ratio = rows[index]['volume'] / baseline
    return ratio, 'supported' if ratio >= cfg['volumeSupportRatio'] else 'weak'


def base_evidence(rows, candidate, cfg):
    """Evidence fixed when the candidate is discovered."""
    return dict(structureBars=candidate['spanBars'],
                separations=[candidate['peaks'][k + 1][0] - candidate['peaks'][k][0]
                             for k in range(len(candidate['peaks']) - 1)],
                depth=depth(rows, candidate),
                priorTrend=trend_for(rows, candidate, cfg),
                formationVolume=formation_volume(rows, candidate))


def summary(base, cfg, breakout_ratio, breakout_status, latest_ratio, latest_status,
            boosted_at=None, retest_volume=None):
    evidence = dict(base)
    evidence['breakoutVolume'] = dict(ratio=breakout_ratio, status=breakout_status,
                                      baselineBars=cfg['volumeBaselineBars'])
    evidence['latestVolume'] = dict(ratio=latest_ratio, status=latest_status)
    evidence['volumeBoostedAt'] = boosted_at
    evidence['retestVolume'] = retest_volume
    return evidence
