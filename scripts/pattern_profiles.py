"""Versioned channel thresholds. Legacy is for read-only comparison, not a UI mode."""
from types import MappingProxyType

PROFILES = MappingProxyType({
    'legacy': MappingProxyType(dict(version=1,fit_atr=.25,containment=.8,flat_slope=.02,trend_slope=.03,
        triangle_contacts=5,triangle_min=10,convergence=.6,pole_atr=3,flag_slope=.02,
        parallel_atr=.08,retracement=.5,flag_max=20,max_outside_run=0)),
    'balanced': MappingProxyType(dict(version=2,fit_atr=.4,containment=.7,flat_slope=.03,trend_slope=.02,
        triangle_contacts=5,triangle_min=8,convergence=.75,pole_atr=2.5,flag_slope=.03,
        parallel_atr=.12,retracement=.618,flag_max=30,max_outside_run=2)),
})


def parameters(profile='balanced'):
    if profile not in PROFILES:raise ValueError('unknown-pattern-profile')
    return PROFILES[profile]


def rule_version(family,timeframe='D',profile='balanced'):
    if family not in ('flag','triangle') or timeframe not in ('D','H4'):raise ValueError('unsupported-pattern-timeframe')
    # H4 v3 changes continuity only; daily thresholds and the v1 comparator stay fixed.
    version=3 if timeframe=='H4' and profile=='balanced' else parameters(profile)['version']
    return f"{family}-{timeframe.lower()}-v{version}"
