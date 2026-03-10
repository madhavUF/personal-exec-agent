"""Tests for usage telemetry report shape."""


def test_usage_report_shape():
    from src.telemetry import usage_report
    r = usage_report()
    assert "totals" in r
    assert "daily" in r
    assert "aggregates" in r
    assert "byModel" in r["aggregates"]
    assert "byProvider" in r["aggregates"]
    assert "latency" in r["aggregates"]

