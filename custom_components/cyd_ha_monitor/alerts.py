"""Pure threshold-rule evaluation for alert-only CYD monitoring."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_DIRECTION,
    CONF_ENTITY_ID,
    CONF_HYSTERESIS,
    CONF_MESSAGE,
    CONF_PRIORITY,
    CONF_THRESHOLD,
    CONF_TITLE,
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


@dataclass(frozen=True, slots=True)
class AlertCommand:
    """The alert currently selected for display on the CYD."""

    priority: int
    title: str
    message: str


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

        threshold = _finite_number(value.get(CONF_THRESHOLD), "threshold")
        hysteresis = _finite_number(value.get(CONF_HYSTERESIS, 0), "hysteresis")
        if hysteresis < 0:
            raise ValueError(f"Rule {index} hysteresis cannot be negative")

        validated.append(
            {
                CONF_ENTITY_ID: entity_id.strip(),
                CONF_DIRECTION: direction,
                CONF_THRESHOLD: threshold,
                CONF_HYSTERESIS: hysteresis,
                CONF_PRIORITY: int(priority),
                CONF_TITLE: title.strip(),
                CONF_MESSAGE: message.strip(),
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
        self.rules = [Rule(**item) for item in validate_rules(rules)]
        self._active = [False] * len(self.rules)
        self.current: AlertCommand | None = None

    @property
    def entities(self) -> set[str]:
        """Return the entities whose state changes this engine needs."""
        return {rule.entity_id for rule in self.rules}

    def seed(self, states: Mapping[str, Any]) -> AlertCommand | None:
        """Evaluate all currently known states and return only the final alert."""
        for entity_id, state in states.items():
            self._update_rules(entity_id, state)
        self.current = self._select_alert()
        return self.current

    def update(self, entity_id: str, state: Any) -> tuple[bool, AlertCommand | None]:
        """Apply one state update; return whether the displayed alert changed."""
        before = self.current
        if not self._update_rules(entity_id, state):
            return False, before
        after = self._select_alert()
        self.current = after
        return after != before, after

    def _update_rules(self, entity_id: str, state: Any) -> bool:
        value = numeric_state(state)
        if value is None:
            # Unknown/unavailable/non-numeric states don't reset hysteresis.
            return False

        matched = False
        for index, rule in enumerate(self.rules):
            if rule.entity_id != entity_id:
                continue
            matched = True
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
        return matched

    def _select_alert(self) -> AlertCommand | None:
        for index in sorted(
            range(len(self.rules)),
            key=lambda item: self.rules[item].priority,
            reverse=True,
        ):
            if self._active[index]:
                rule = self.rules[index]
                return AlertCommand(rule.priority, rule.title, rule.message)
        return None
