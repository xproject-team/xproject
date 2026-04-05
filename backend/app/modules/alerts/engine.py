"""Alert evaluation engine — applies rules against live metrics to generate Alert records.

This file is unique to the alerts module. It contains rule definitions and the
evaluation loop that determines when an alert should be fired. Keep all rule
logic here so it can be tested independently of the HTTP layer.
"""
from dataclasses import dataclass


@dataclass
class AlertRule:
    """Defines a single alerting rule with threshold and severity."""

    name: str
    severity: str  # info | warning | critical
    description: str


# Built-in alert rules
STOCK_LOW_WARNING = AlertRule("stock_low_warning", "warning", "Item stock below 20%")
STOCK_CRITICAL = AlertRule("stock_critical", "critical", "Item stock below 5%")
ANOMALY_DETECTED = AlertRule("anomaly_detected", "warning", "Consumption anomaly detected")
SALES_SPIKE = AlertRule("sales_spike", "info", "Sales velocity 2x above baseline")

ALL_RULES: list[AlertRule] = [STOCK_LOW_WARNING, STOCK_CRITICAL, ANOMALY_DETECTED, SALES_SPIKE]


async def evaluate_rules(event_id: int, metrics: dict) -> list[AlertRule]:
    """Evaluate all rules against the current metrics snapshot.

    Returns the list of rules that have been triggered.
    """
    triggered: list[AlertRule] = []
    # TODO: implement threshold checks against metrics dict
    return triggered
