"""Unit tests must not read/write the user's active market cache."""
import pytest


@pytest.fixture(autouse=True)
def isolated_market_feature(monkeypatch):
    monkeypatch.setenv('CHART_SHARED_CACHE','0')
    monkeypatch.setenv('CHART_HORIZONTAL_PATTERNS','0')
    monkeypatch.setenv('CHART_FLAG_PATTERNS','0')
    monkeypatch.setenv('CHART_SERVER_MONITOR','0')
    monkeypatch.setenv('CHART_TRIANGLE_PATTERNS','0')
