"""Read-only comparison of the legacy structure rules and the parallel evidence engine.

The manifest fixes the symbol list, window, split boundaries, matching key and
observation horizons before the run. Output goes to a new folder; the frozen
market cache, experiments and results are never rewritten.

A pilot manifest is a convenience sample, not an approved evaluation. Its numbers
cannot justify replacing the existing judgment rules.
"""
from argparse import ArgumentParser
from datetime import datetime, timezone
from json import dumps, loads
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import structure_patterns  # noqa: E402
from structure_lifecycle_v2 import analyze as evidence_analyze  # noqa: E402


def load_manifest(path):
    data = loads(Path(path).read_text())
    required = ('symbols', 'window', 'splits', 'horizons', 'match')
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError('manifest-missing:' + ','.join(missing))
    start, end = data['window']['start'], data['window']['end']
    if start > end:
        raise ValueError('manifest-window-invalid')
    for name, (a, b) in data['splits'].items():
        if not (start <= a <= b <= end):
            raise ValueError('manifest-split-outside-window:' + name)
    return data


def cached_candles(db, symbol, start, end):
    """Read the adjusted daily series for a symbol without touching the cache."""
    tz = 'Asia/Seoul' if symbol.endswith(('.KS', '.KQ')) else 'America/New_York'
    digits = symbol.split('.')[0]
    rows = None
    for name in (symbol, digits):
        key = '|'.join(('candles', name, 'D', 'adjusted', tz, 'v1'))
        row = db.execute('SELECT value FROM entries WHERE key=?', (key,)).fetchone()
        if row:
            rows = loads(row[0])['rows']
            break
    if not rows:
        return None
    candles = [dict(time=r['t'], open=r['open'], high=r['high'], low=r['low'],
                    close=r['close'], volume=r['volume'])
               for r in rows if start <= r['t'] <= end]
    return candles or None


def split_of(day, splits):
    for name, (a, b) in splits.items():
        if a <= day <= b:
            return name
    return None


def anchor_time(pattern):
    legacy = pattern.get('anchorTime')
    if legacy:
        return legacy
    peaks = (pattern.get('anchors') or {}).get('peakTimes') or []
    return peaks[0] if peaks else None


def legacy_events(result):
    out = []
    for event in result.get('events') or []:
        if event.get('eventType') != 'confirmed':
            continue
        out.append(dict(type=event.get('type'), direction=event.get('direction'),
                        anchor=anchor_time(event), confirmed=event.get('confirmedBarTime'),
                        close=event.get('close'), trigger=event.get('triggerPrice'),
                        atr=event.get('atr14Previous')))
    return out


def evidence_events(result):
    out = []
    for pattern in result.get('patterns') or []:
        events = pattern.get('events') or []
        confirmed = next((e for e in events if e['eventType'] == 'breakout-confirmed'), None)
        if not confirmed:
            continue
        snapshot = confirmed.get('snapshot') or {}
        failed = any(e['eventType'] == 'breakout-failed' for e in events)
        out.append(dict(type=pattern.get('type'), direction=pattern.get('direction'),
                        anchor=anchor_time(pattern), confirmed=confirmed.get('effectiveBarTime'),
                        close=snapshot.get('close'), trigger=snapshot.get('triggerPrice'),
                        atr=pattern.get('atr14Previous'), patternId=pattern.get('patternId'),
                        state=pattern.get('lifecycleState'), failed=failed))
    return out


def movement(candles, index, event, horizon):
    """Favourable/adverse excursion from the confirmation close, in ATR units."""
    atr = event.get('atr') or 0
    close = event.get('close')
    if not atr or close is None or index is None:
        return None
    sign = 1 if event.get('direction') == 'up' else -1
    window = candles[index + 1:index + 1 + horizon]
    if not window:
        return None
    highs = [r['high'] for r in window]
    lows = [r['low'] for r in window]
    if sign == 1:
        favourable = (max(highs) - close) / atr
        adverse = (close - min(lows)) / atr
    else:
        favourable = (close - min(lows)) / atr
        adverse = (max(highs) - close) / atr
    return dict(favourable=round(favourable, 3), adverse=round(adverse, 3))


def wilson(successes, total, z=1.96):
    """95% Wilson interval for a rate; small samples stay visibly uncertain."""
    if not total:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return [round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4)]


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return round(values[middle], 3)
    return round((values[middle - 1] + values[middle]) / 2, 3)


def run(manifest, db_path):
    db = sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True)
    splits = manifest['splits']
    horizons = manifest['horizons']
    rows = {name: dict(legacy=[], evidence=[], symbols=0, missing=[], excluded=0)
            for name in splits}
    coverage = []
    try:
        for symbol in manifest['symbols']:
            candles = cached_candles(db, symbol, manifest['window']['start'], manifest['window']['end'])
            if not candles or len(candles) < 60:
                coverage.append(dict(symbol=symbol, bars=0 if not candles else len(candles),
                                     state='no-data'))
                for name in splits:
                    rows[name]['missing'].append(symbol)
                continue
            coverage.append(dict(symbol=symbol, bars=len(candles), state='used',
                                 first=candles[0]['time'], last=candles[-1]['time']))
            index_of = {c['time']: i for i, c in enumerate(candles)}
            cutoff = candles[-1]['time']
            legacy = legacy_events(structure_patterns.analyze(
                candles, symbol, cutoff, False, {}, timeframe='D'))
            new = evidence_events(evidence_analyze(candles, symbol, cutoff))
            for label, source in (('legacy', legacy), ('evidence', new)):
                for event in source:
                    bucket = split_of(event['confirmed'], splits)
                    if bucket is None:
                        continue
                    event['index'] = index_of.get(event['confirmed'])
                    event['lag'] = (event['index'] - index_of[event['anchor']]
                                    if event.get('anchor') in index_of and event['index'] is not None
                                    else None)
                    event['symbol'] = symbol
                    if label == 'evidence':
                        event['moves'] = {str(h): movement(candles, event['index'], event, h)
                                          for h in horizons}
                    rows[bucket][label].append(event)
            for name in splits:
                rows[name]['symbols'] += 1
    finally:
        db.close()

    report = {}
    for name, bucket in rows.items():
        legacy, evidence = bucket['legacy'], bucket['evidence']
        key = tuple(manifest['match']['key'])
        def token(event):
            return (event.get('type'), event.get('anchor'))
        legacy_map = {token(e): e for e in legacy}
        evidence_map = {token(e): e for e in evidence}
        matched = sorted(set(legacy_map) & set(evidence_map))
        stats = dict(
            symbols=bucket['symbols'], missingSymbols=sorted(set(bucket['missing'])),
            legacyConfirmed=len(legacy), evidenceConfirmed=len(evidence),
            matched=len(matched), legacyOnly=len(set(legacy_map) - set(evidence_map)),
            evidenceOnly=len(set(evidence_map) - set(legacy_map)),
            legacyMedianLagBars=median(e['lag'] for e in legacy),
            evidenceMedianLagBars=median(e['lag'] for e in evidence),
            evidenceFailed=sum(1 for e in evidence if e['failed']),
            evidenceFailureRate=(round(sum(1 for e in evidence if e['failed']) / len(evidence), 4)
                                 if evidence else None),
            evidenceFailureInterval=(wilson(sum(1 for e in evidence if e['failed']), len(evidence))
                                     if evidence else None),
            byType={})
        for kind in ('double-top', 'double-bottom', 'head-shoulders', 'inverse-head-shoulders'):
            stats['byType'][kind] = dict(
                legacy=sum(1 for e in legacy if e['type'] == kind),
                evidence=sum(1 for e in evidence if e['type'] == kind))
        for horizon in horizons:
            moves = [e['moves'].get(str(horizon)) for e in evidence if e.get('moves')]
            stats[f'horizon{horizon}'] = dict(
                samples=sum(1 for m in moves if m),
                medianFavourableAtr=median(m['favourable'] for m in moves if m),
                medianAdverseAtr=median(m['adverse'] for m in moves if m))
        report[name] = stats
    return dict(manifest=manifest, generatedAt=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                source=str(db_path), coverage=coverage, splits=report)


def markdown(result):
    label = '승인 모집단' if result['manifest'].get('status') == 'approved-population-v1' else '파일럿'
    lines = ['# 구조 규칙 비교 (' + label + ')', '',
             f"- 생성: {result['generatedAt']}",
             f"- 자료: `{result['source']}` (읽기 전용)",
             f"- 표본 상태: {result['manifest'].get('status', 'unspecified')}",
             f"- 고지: {result['manifest'].get('note', '')}", '',
             '## 구간별 요약', '',
             '| 구간 | 종목 | 기존 확인 | 신규 확인 | 일치 | 신규만 | 기존만 | 기존 지연(봉) | 신규 지연(봉) | 신규 무효율(95% 구간) |',
             '|---|---|---|---|---|---|---|---|---|---|']
    for name, row in result['splits'].items():
        lines.append('| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            name, row['symbols'], row['legacyConfirmed'], row['evidenceConfirmed'],
            row['matched'], row['evidenceOnly'], row['legacyOnly'],
            row['legacyMedianLagBars'], row['evidenceMedianLagBars'],
            '{} {}'.format(row['evidenceFailureRate'], row.get('evidenceFailureInterval') or '')))
    lines += ['', '## 관찰 지평', '',
              '| 구간 | 지평 | 표본 | 중앙 유리(ATR) | 중앙 불리(ATR) |', '|---|---|---|---|---|']
    for name, row in result['splits'].items():
        for horizon in result['manifest']['horizons']:
            item = row.get('horizon{}'.format(horizon)) or {}
            lines.append('| {} | {}봉 | {} | {} | {} |'.format(
                name, horizon, item.get('samples'), item.get('medianFavourableAtr'),
                item.get('medianAdverseAtr')))
    lines += ['', '## 자료 확인', '', '| 종목 | 봉 수 | 상태 |', '|---|---|---|']
    for item in result['coverage']:
        lines.append('| {} | {} | {} |'.format(item['symbol'], item['bars'], item['state']))
    lines += ['', '## 읽는 법', '',
              '- 대응 기준은 (종류, 첫 앵커 시각) 정확 일치입니다. 기존 규칙은 같은 구조를 여러 앵커 조합으로',
              '  반복 기록하므로 "기존만" 수가 커집니다. 이는 누락이 아니라 중복 기록 차이입니다.',
              '- 확인 지연은 첫 앵커부터 확인 봉까지의 봉 수입니다. 패턴 폭이 긴 헤드앤숄더가 섞여 있어',
              '  기존·신규 지연을 그대로 속도 비교로 읽으면 안 됩니다.',
              '- 신규 무효율은 확인 사건 중 이후 breakout-failed 사건이 있는 비율입니다. 기존 엔진에는',
              '  대응 개념이 없어 비교값이 없습니다.',
              '- 유리·불리는 확인 종가 대비 이후 N봉의 최고·최저를 ATR로 나눈 값의 중앙값입니다.',
              '  비용·슬리피지·체결 불확실성은 포함하지 않았습니다.', '',
              '## 제외', '',
              '- 자료가 없거나 60봉 미만이라 제외한 종목: ' +
              (', '.join(sorted({sym for row in result['splits'].values() for sym in row['missingSymbols']})) or '없음'),
              '', '## 한계', '',
              '- 모집단·기간은 실행 전에 고정했지만 최소 표본 수와 허용 지연·누락 상한은 승인되지 않았습니다.',
              '- 생존편향, 상장폐지, 유동성 구간 분리를 반영하지 않았습니다.',
              '- 확인 지연은 앵커~확인 봉 수라 패턴 폭의 영향을 받습니다.',
              '- 이 결과는 수익성 검증이 아니며 규칙 승격·교체의 단독 근거가 아닙니다.']
    return '\n'.join(lines) + '\n'


def main():
    parser = ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--db', default=str(ROOT / 'logs' / 'market-cache.sqlite3'))
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    result = run(manifest, args.db)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'compare.json').write_text(dumps(result, ensure_ascii=False, indent=2))
    (out / 'compare.md').write_text(markdown(result))
    print(dumps({name: {k: row[k] for k in ('symbols', 'legacyConfirmed', 'evidenceConfirmed',
                                            'matched', 'evidenceOnly', 'legacyOnly')}
                 for name, row in result['splits'].items()}, ensure_ascii=False, indent=2))
    print('report:', out)


if __name__ == '__main__':
    main()
