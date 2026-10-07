"""Pure threshold-rule evaluation for alert-only CYD monitoring."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    ATTENTION_PAGE_VALUES,
    CONF_ATTENTION_PAGE,
    CONF_DIRECTION,
    CONF_ENTITY_ID,
    CONF_HYSTERESIS,
    CONF_MESSAGE,
    CONF_PRIORITY,
    CONF_THRESHOLD,
    CONF_TITLE,
    CONF_WARNING_THRESHOLD,
)

DIRECTIONS = frozenset({"above", "below"})
PRIORITIES = frozenset({1, 2, 3})
INVALID_STATES = frozenset({"", "unknown", "unavailable", "none"})


@dataclass(frozen=True, slots=True)
class Rule:
    """A validated threshold rule."""

    entity_id: str
    direction: str
    threshold: float
    hysteresis: float
    priority: int
    title: str
    message: str
    attention_page: str
    warning_threshold: float | None
    rule_id: str


@dataclass(frozen=True, slots=True)
class AlertCommand:
    """The alert currently selected for display on the CYD."""

    priority: int
    title: str
    message: str
    attention_page: str = "none"
    rule_id: str = ""
    actual: str = ""
    limit: str = ""
    source: str = ""


def _finite_number(value: Any, field: str) -> float:
    """Coerce a numeric setting and reject NaN and infinity."""
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{field} must be numeric") from err
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def validate_rules(values: Any) -> list[dict[str, Any]]:
    """Validate and normalize the repeatable rule list from the options flow."""
    if not isinstance(values, list):
        raise TypeError("Rules must be a list")

    validated: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, Mapping):
            raise TypeError(f"Rule {index} must be an object")

        entity_id = value.get(CONF_ENTITY_ID)
        direction = value.get(CONF_DIRECTION)
        priority = value.get(CONF_PRIORITY, 2)
        title = value.get(CONF_TITLE)
        message = value.get(CONF_MESSAGE)
        attention_page = value.get(CONF_ATTENTION_PAGE, "none")
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise ValueError(f"Rule {index} needs a numeric entity")
        if direction not in DIRECTIONS:
            raise ValueError(f"Rule {index} direction must be above or below")
        if isinstance(priority, bool) or str(priority).strip() not in {
            "1",
            "2",
            "3",
        }:
            raise ValueError(f"Rule {index} priority must be 1, 2, or 3")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Rule {index} needs a title")
        if not isinstance(message, str) or not message.strip():
            raise ValueError(f"Rule {index} needs a message")
        if attention_page not in ATTENTION_PAGE_VALUES:
            raise ValueError(f"Rule {index} has an invalid attention page")

        threshold = _finite_number(value.get(CONF_THRESHOLD), "threshold")
        warning_value = value.get(CONF_WARNING_THRESHOLD)
        warning_threshold = (
            None
            if warning_value in (None, "")
            else _finite_number(warning_value, "warning threshold")
        )
        if warning_threshold is not None and (
            warning_threshold >= threshold
            if direction == "above"
            else warning_threshold <= threshold
        ):
            raise ValueError(
                "Warning threshold must be below an upper limit or above a lower limit"
            )
        hysteresis = _finite_number(value.get(CONF_HYSTERESIS, 0), "hysteresis")
        if hysteresis < 0:
            raise ValueError(f"Rule {index} hysteresis cannot be negative")

        validated.append(
            {
                CONF_ENTITY_ID: entity_id.strip(),
                CONF_DIRECTION: direction,
                CONF_THRESHOLD: threshold,
                **(
                    {CONF_WARNING_THRESHOLD: warning_threshold}
                    if warning_threshold is not None
                    else {}
                ),
                CONF_HYSTERESIS: hysteresis,
                CONF_PRIORITY: int(priority),
                CONF_TITLE: title.strip(),
                CONF_MESSAGE: message.strip(),
                CONF_ATTENTION_PAGE: attention_page,
            }
        )
    return validated


def numeric_state(value: Any) -> float | None:
    """Return a finite numeric state, or None for unusable sensor values."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().casefold() in INVALID_STATES:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class RuleEngine:
    """Track rule hysteresis and select the highest-priority active alert."""

    def __init__(self, rules: Any) -> None:
        self.rules = []
        for index, item in enumerate(validate_rules(rules)):
            item.setdefault(CONF_WARNING_THRESHOLD, None)
            identity = json.dumps(item, sort_keys=True, separators=(",", ":"))
            rule_id = hashlib.sha1(f"{index}:{identity}".encode()).hexdigest()[:12]
            self.rules.append(Rule(**item, rule_id=rule_id))
        self._active = [False] * len(self.rules)
        self._latest: dict[str, tuple[float, str, str]] = {}
        self._newly_cleared_rule_ids: list[str] = []
        self.current: AlertCommand | None = None

    @property
    def entities(self) -> set[str]:
        """Return the entities whose state changes this engine needs."""
        return {rule.entity_id for rule in self.rules}

    def seed(
        self,
        states: Mapping[str, Any],
        units: Mapping[str, str] | None = None,
        sources: Mapping[str, str] | None = None,
    ) -> AlertCommand | None:
        """Evaluate all currently known states and return only the final alert."""
        for entity_id, state in states.items():
            self._update_rules(
                entity_id,
                state,
                (units or {}).get(entity_id, ""),
                (sources or {}).get(entity_id, entity_id),
            )
        self.current = self._select_alert()
        return self.current

    def update(
        self, entity_id: str, state: Any, unit: str = "", source: str = ""
    ) -> tuple[bool, AlertCommand | None]:
        """Apply one state update; return whether the displayed alert changed."""
        before = self.current
        if not self._update_rules(entity_id, state, unit, source or entity_id):
            return False, before
        after = self._select_alert()
        self.current = after
        return after != before, after

    def take_cleared_rule_ids(self) -> list[str]:
        """Return rule incidents that recovered since the last read."""
        cleared = self._newly_cleared_rule_ids
        self._newly_cleared_rule_ids = []
        return cleared

    def active_rule_ids(self) -> list[str]:
        """Return every currently breached rule, including preempted alerts."""
        return [
            rule.rule_id
            for rule, active in zip(self.rules, self._active, strict=True)
            if active
        ]

    def rule_priority(self, rule_id: str) -> int:
        """Return a rule's priority, or zero for an unknown incident ID."""
        return next(
            (rule.priority for rule in self.rules if rule.rule_id == rule_id), 0
        )

    def _update_rules(
        self, entity_id: str, state: Any, unit: str = "", source: str = ""
    ) -> bool:
        value = numeric_state(state)
        if value is None:
            # Unknown/unavailable/non-numeric states don't reset hysteresis.
            return False
        self._latest[entity_id] = (value, unit, source or entity_id)

        matched = False
        for index, rule in enumerate(self.rules):
            if rule.entity_id != entity_id:
                continue
            matched = True
            was_active = self._active[index]
            if self._active[index]:
                self._active[index] = (
                    value > rule.threshold - rule.hysteresis
                    if rule.direction == "above"
                    else value < rule.threshold + rule.hysteresis
                )
            else:
                self._active[index] = (
                    value > rule.threshold
                    if rule.direction == "above"
                    else value < rule.threshold
                )
            if was_active and not self._active[index]:
                self._newly_cleared_rule_ids.append(rule.rule_id)
        return matched

    def _select_alert(self) -> AlertCommand | None:
        for index in sorted(
            range(len(self.rules)),
            key=lambda item: self.rules[item].priority,
            reverse=True,
        ):
            if self._active[index]:
                rule = self.rules[index]
                value, unit, source = self._latest.get(
                    rule.entity_id, (0.0, "", rule.entity_id)
                )
                return AlertCommand(
                    priority=rule.priority,
                    title=rule.title,
                    message=rule.message,
                    attention_page=rule.attention_page,
                    rule_id=rule.rule_id,
                    actual=_format_measurement(value, unit),
                    limit=(
                        f"> {_format_measurement(rule.threshold, unit)}"
                        if rule.direction == "above"
                        else f"< {_format_measurement(rule.threshold, unit)}"
                    ),
                    source=source,
                )
        return None

    def sensor_status(self, entity_id: str) -> int:
        """Return 0 neutral, 1 safe, 2 nearing a limit, or 3 breached."""
        current = self._latest.get(entity_id)
        if current is None:
            return 0
        value, _unit, _source = current
        matching = [
            index
            for index, rule in enumerate(self.rules)
            if rule.entity_id == entity_id
        ]
        if not matching:
            return 0
        if any(self._active[index] for index in matching):
            return 3
        warning_rules = [
            self.rules[index]
            for index in matching
            if self.rules[index].warning_threshold is not None
        ]
        if not warning_rules:
            return 0
        if any(
            value >= rule.warning_threshold
            if rule.direction == "above"
            else value <= rule.warning_threshold
            for rule in warning_rules
        ):
            return 2
        return 1

    def is_rule_active(self, rule_id: str) -> bool:
        """Return whether the rule is still breached, including when preempted."""
        return any(
            active and rule.rule_id == rule_id
            for rule, active in zip(self.rules, self._active, strict=True)
        )


def _format_measurement(value: float, unit: str) -> str:
    """Format a compact numeric reading and retain its HA unit."""
    number = f"{value:.2f}".rstrip("0").rstrip(".")
    if number == "-0":
        number = "0"
    unit = unit.strip()
    if not unit:
        return number
    separator = "" if unit.startswith("°") or unit == "%" else " "
    return f"{number}{separator}{unit}"
