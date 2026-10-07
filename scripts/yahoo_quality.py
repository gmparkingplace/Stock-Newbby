"""Keep the latest valid Yahoo price segment without inventing replacement bars."""
import math


def latest_valid_segment(data, minimum=80):
    """Restart every indicator after the last malformed source candle.

    Removing just a bad row would bridge a data gap and carry a corrupted ATR
    or OBV seed forward. Keep the subsequent segment and disclose the history
    omitted. An invalid latest bar or insufficient remaining history fails.
    """
    if not data['t'].is_monotonic_increasing or data['t'].duplicated().any():
        raise ValueError('야후 봉 날짜 오류 · 조회 자료 확인 필요')
    invalid = []
    for index, row in enumerate(data[['open', 'high', 'low', 'close', 'volume']].itertuples(index=False, name=None)):
        try:
            numbers = [float(value) for value in row]
        except (TypeError, ValueError):
            numbers = [math.nan]
        if any(not math.isfinite(value) for value in numbers):
            invalid.append(index)
            continue
        o, h, low, c = (round(value, 4) for value in numbers[:4])
        if min(o, h, low, c) <= 0 or numbers[4] < 0 or h < max(o, low, c) or low > min(o, h, c):
            invalid.append(index)
    if not invalid:
        return data, []
    start = invalid[-1] + 1
    if len(data) - start < minimum:
        raise ValueError('야후 봉 자료 오류 · 오류 이후 정상 자료 부족')
    def stamp(index):
        value = data['t'].iloc[index]
        return value.item() if hasattr(value, 'item') else value
    warning = dict(code='invalid-yahoo-bars', count=len(invalid),
                   invalidTimes=[stamp(i) for i in invalid],
                   excludedHistoryBars=start, analysisFrom=stamp(start))
    return data.iloc[start:].copy().reset_index(drop=True), [warning]
