"""Tests for alert-rule evaluation without Home Assistant runtime dependencies."""

from __future__ import annotations

import unittest

from custom_components.cyd_ha_monitor.alerts import (
    RuleEngine,
    numeric_state,
    validate_rules,
)


def rule(
    *,
    entity_id: str = "sensor.temperature",
    direction: str = "above",
    threshold: float = 20,
    hysteresis: float = 2,
    priority: int = 2,
    title: str = "Warm",
    message: str = "Too warm",
) -> dict[str, object]:
    return {
        "entity_id": entity_id,
        "direction": direction,
        "threshold": threshold,
        "hysteresis": hysteresis,
        "priority": priority,
        "title": title,
        "message": message,
    }


class NumericStateTests(unittest.TestCase):
    def test_rejects_missing_and_non_finite_sensor_values(self) -> None:
        for value in (
            None,
            "unknown",
            "UNAVAILABLE",
            "not a number",
            "nan",
            "inf",
            True,
        ):
            with self.subTest(value=value):
                self.assertIsNone(numeric_state(value))

    def test_accepts_finite_numbers(self) -> None:
        self.assertEqual(numeric_state(" 21.5 "), 21.5)
        self.assertEqual(numeric_state(-3), -3.0)


class RuleValidationTests(unittest.TestCase):
    def test_normalizes_rules(self) -> None:
        result = validate_rules([rule(threshold="20.5", hysteresis=1, priority="3")])
        self.assertEqual(result[0]["threshold"], 20.5)
        self.assertEqual(result[0]["hysteresis"], 1.0)
        self.assertEqual(result[0]["priority"], 3)

    def test_optional_hysteresis_and_priority_use_safe_defaults(self) -> None:
        value = rule()
        value.pop("hysteresis")
        value.pop("priority")
        result = validate_rules([value])
        self.assertEqual(result[0]["hysteresis"], 0.0)
        self.assertEqual(result[0]["priority"], 2)

    def test_rejects_invalid_direction_priority_and_negative_hysteresis(self) -> None:
        for changes in (
            {"direction": "equal"},
            {"priority": 4},
            {"hysteresis": -0.1},
            {"threshold": "nan"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_rules([rule(**changes)])  # type: ignore[arg-type]

    def test_wrong_input_types_raise_type_error(self) -> None:
        for value in (None, {}, "not a rule list", [None]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                validate_rules(value)

        with self.assertRaises(TypeError):
            validate_rules([rule(threshold=True)])


class RuleEngineTests(unittest.TestCase):
    def test_above_rule_activates_and_clears_with_hysteresis(self) -> None:
        engine = RuleEngine([rule()])
        self.assertEqual(engine.update("sensor.temperature", "20"), (False, None))
        changed, alert = engine.update("sensor.temperature", "20.1")
        self.assertTrue(changed)
        self.assertEqual(alert.title if alert else None, "Warm")

        self.assertEqual(engine.update("sensor.temperature", "19"), (False, alert))
        changed, alert = engine.update("sensor.temperature", "18")
        self.assertTrue(changed)
        self.assertIsNone(alert)

    def test_below_rule_uses_opposite_hysteresis_direction(self) -> None:
        engine = RuleEngine(
            [rule(direction="below", threshold=5, hysteresis=1, title="Cold")]
        )
        self.assertEqual(engine.update("sensor.temperature", "4.9")[1].title, "Cold")
        self.assertEqual(engine.update("sensor.temperature", "5.5")[1].title, "Cold")
        changed, alert = engine.update("sensor.temperature", "6")
        self.assertTrue(changed)
        self.assertIsNone(alert)

    def test_unknown_state_does_not_clear_an_active_rule(self) -> None:
        engine = RuleEngine([rule()])
        _, active = engine.update("sensor.temperature", "22")
        self.assertIsNotNone(active)
        self.assertEqual(
            engine.update("sensor.temperature", "unavailable"), (False, active)
        )

    def test_highest_priority_wins_then_lower_priority_is_restored(self) -> None:
        engine = RuleEngine(
            [
                rule(priority=1, title="Notice", message="Warm"),
                rule(
                    entity_id="sensor.critical",
                    threshold=30,
                    hysteresis=1,
                    priority=3,
                    title="Critical",
                    message="Very warm",
                ),
            ]
        )
        self.assertEqual(
            engine.seed({"sensor.temperature": "21", "sensor.critical": "31"}).title,
            "Critical",
        )
        changed, alert = engine.update("sensor.critical", "29")
        self.assertTrue(changed)
        self.assertEqual(alert.title if alert else None, "Notice")
        changed, alert = engine.update("sensor.temperature", "17")
        self.assertTrue(changed)
        self.assertIsNone(alert)

    def test_identical_selected_alert_is_deduplicated(self) -> None:
        engine = RuleEngine([rule()])
        self.assertTrue(engine.update("sensor.temperature", "21")[0])
        self.assertFalse(engine.update("sensor.temperature", "22")[0])

    def test_seed_selects_once_from_all_current_states(self) -> None:
        engine = RuleEngine(
            [
                rule(priority=1),
                rule(entity_id="sensor.critical", threshold=30, priority=3),
            ]
        )
        alert = engine.seed({"sensor.temperature": "21", "sensor.critical": "31"})
        self.assertEqual(alert.priority if alert else None, 3)


if __name__ == "__main__":
    unittest.main()
