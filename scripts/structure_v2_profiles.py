"""Explicit, hashed thresholds for the structure evidence v2 engine.

These numbers are implementation hypotheses, not rules proved by the 1932 book.
Changing any value changes `configId`, so cached evidence from another setting
cannot be mistaken for the current one. Never overwrite a released profile in
place; add a new profile name and bump `version`.
"""
from hashlib import sha256
from types import MappingProxyType
import json

_BASELINE = dict(
    version=1,
    # Shape discovery. Bars, not calendar days; ties pick the earliest bar.
    toleranceAtr=.25,
    headExcessAtr=.25,
    minSeparationBars=3,
    maxSpanBars=60,
    maxTotalBars=90,
    # Price confirmation. 0.1 ATR keeps the existing displayed trigger honest.
    breakoutAtr=.1,
    invalidationAtr=.3,
    retestBandAtr=.15,
    # Lifetimes in confirmed bars. Expiry is "at least N bars after the anchor".
    candidateBars=20,
    trackingBars=30,
    # Evidence windows. Descriptive only; none of these block a pattern.
    priorTrendBars=30,
    priorTrendMinBars=10,
    flatTrendPct=2.0,
    volumeBaselineBars=20,
    volumeSupportRatio=1.2,
)

PROFILES = MappingProxyType({'baseline': MappingProxyType(_BASELINE)})


def parameters(profile='baseline'):
    if profile not in PROFILES:
        raise ValueError('unknown-structure-evidence-profile')
    return PROFILES[profile]


def config_id(profile='baseline'):
    cfg = dict(parameters(profile))
    digest = sha256(json.dumps(cfg, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return 'structure-evidence-v%d-%s' % (cfg['version'], digest[:10])


def rule_version(timeframe='D', profile='baseline'):
    if timeframe != 'D':
        raise ValueError('unsupported-structure-evidence-timeframe')
    return 'structure-evidence-d-v%d' % parameters(profile)['version']
