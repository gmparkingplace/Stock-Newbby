"""Causal daily horizontal crossings; price evidence, never an entry/order verdict."""
from pattern_math import validated, atr14
import math
from market_store import revision

RULE = 'horizontal-d-v1'


def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'support', 'resistance'}:
        raise ValueError('invalid-levels')
    out = {}
    for key in ('support', 'resistance'):
        number = value.get(key)
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)) or number <= 0:
                raise ValueError('invalid-levels')
            number = float(number)
        out[key] = number
    if out['support'] is not None and out['resistance'] is not None and out['support'] >= out['resistance']:
        raise ValueError('support-must-be-below-resistance')
    return out


def analyze(candles, symbol, confirmed_through, provisional=False, levels=None):
    """Replay only supplied bars. ATR: first 14 TR mean, then Wilder recurrence.

    Fixed crossing line/ATR are immutable through the next 10 confirmed bars.
    Retest = wick touches line +/- .1 ATR and close holds trigger side.
    Failure = close crosses line by .1 ATR in the opposite direction. Failure wins.
    """
    levels = settings(levels)
    rows = validated(candles, confirmed_through)
    config_id = revision(levels)[:16]
    events, active, timeline = [], [], []
    atr = atr14(rows)
    prev_levels = {}
    for i, row in enumerate(rows):
        t, c = row['time'], row['close']
        pc = rows[i-1]['close'] if i else c
        confirmed = confirmed_through is not None and t <= confirmed_through
        ready = i >= 20
        current = []
        if ready:
            a = atr[i-1]
            rv_mean = sum(x['volume'] for x in rows[i-20:i])/20
            rvol = row['volume']/rv_mean if rv_mean > 0 else None
            bounds = [('prior-20-high', 'up', max(x['high'] for x in rows[i-20:i])),
                      ('prior-10-low', 'down', min(x['low'] for x in rows[i-10:i]))]
            if levels['resistance'] is not None: bounds.append(('user-resistance', 'up', levels['resistance']))
            if levels['support'] is not None: bounds.append(('user-support', 'down', levels['support']))
            for kind, direction, line in bounds:
                sign = 1 if direction == 'up' else -1
                trigger = line + sign*.1*a
                old = prev_levels.get(kind)
                # Require a price crossing of today's AND yesterday's trigger.
                # A falling rolling boundary or shrinking ATR alone is not a crossing.
                crossed = old is not None and sign*(c-trigger)>0 and sign*(pc-trigger)<=0 and sign*(pc-old['triggerPrice'])<=0
                item = dict(type=kind, direction=direction, boundary=line, triggerPrice=trigger,
                            invalidationPrice=line-sign*.1*a, atr14Previous=a, rvol20Previous=rvol,
                            volumeEvidence='volume-confirmed' if rvol is not None and rvol >= 1.2 else 'volume-insufficient',
                            barTime=t, close=c, status='forming')
                if crossed:
                    item['status'] = 'confirmed' if confirmed else 'breakout-pending' if provisional and i == len(rows)-1 else 'paused'
                    item['patternId'] = revision([symbol, 'D', kind, RULE, line if kind.startswith('user-') else None, t])
                    if confirmed:
                        active.append({**item, 'index':i, 'retested':False, 'failed':False})
                        events.append({**item, 'eventType':'confirmed', 'confirmedBarTime':t, 'anchorTime':t})
                current.append(item)
            prev_levels = {x['type']:x for x in current}
        # No event from provisional/unconfirmed bars, including retest and failure.
        if confirmed:
            for pattern in active:
                age = i-pattern['index']
                if not 1 <= age <= 10 or pattern['failed']: continue
                sign = 1 if pattern['direction'] == 'up' else -1
                failed = sign*(c-pattern['invalidationPrice']) < 0
                touched = row['low'] <= pattern['boundary']+.1*pattern['atr14Previous'] and row['high'] >= pattern['boundary']-.1*pattern['atr14Previous']
                retested = touched and sign*(c-pattern['triggerPrice']) > 0 and not pattern['retested']
                if failed or retested:
                    kind = 'failed' if failed else 'retested'
                    pattern[kind] = True
                    event = {k:v for k,v in pattern.items() if k not in ('index','retested','failed')}
                    events.append({**event, 'status':kind, 'eventType':kind, 'barTime':t,
                                   'confirmedBarTime':t, 'anchorTime':pattern['barTime'], 'close':c})
        timeline.append(dict(barTime=t, confirmed=confirmed, status='ready' if i >= 21 else 'insufficient-data', levels=current))
    for event in events:
        event['ruleVersion'] = RULE
        event['eventId'] = revision([event['patternId'], event['eventType'], event['confirmedBarTime'], RULE])
    return dict(symbol=symbol, timeframe='D', ruleVersion=RULE, levels=levels,
                configId=config_id, confirmedThrough=confirmed_through, timeline=timeline, events=events)
