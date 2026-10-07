"""Tests for alert-rule evaluation without Home Assistant runtime dependencies."""

from __future__ import annotations

import unittest

from custom_components.cyd_ha_monitor.alerts import (
    RuleEngine,
    numeric_state,
    validate_rules,
)
from custom_components.cyd_ha_monitor.const import CONF_ATTENTION_PAGE


def rule(
    *,
    entity_id: str = "sensor.temperature",
    direction: str = "above",
    threshold: float = 20,
    hysteresis: float = 2,
    priority: int = 2,
    title: str = "Warm",
    message: str = "Too warm",
    attention_page: str = "none",
    warning_threshold: float | None = None,
) -> dict[str, object]:
    value = {
        "entity_id": entity_id,
        "direction": direction,
        "threshold": threshold,
        "hysteresis": hysteresis,
        "priority": priority,
        "title": title,
        "message": message,
        CONF_ATTENTION_PAGE: attention_page,
    }
    if warning_threshold is not None:
        value["warning_threshold"] = warning_threshold
    return value


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
        self.assertEqual(result[0][CONF_ATTENTION_PAGE], "none")

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
            {"attention_page": "unknown_page"},
            {"warning_threshold": 21},
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
        engine = RuleEngine([rule(attention_page="energy")])
        self.assertEqual(engine.update("sensor.temperature", "20"), (False, None))
        changed, alert = engine.update("sensor.temperature", "20.1")
        self.assertTrue(changed)
        self.assertEqual(alert.title if alert else None, "Warm")
        self.assertEqual(alert.attention_page if alert else None, "energy")

        changed, updated = engine.update("sensor.temperature", "19")
        self.assertTrue(changed)
        self.assertEqual(updated.actual, "19")
        self.assertEqual(updated.limit, "> 20")
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
                    attention_page="energy",
                ),
            ]
        )
        seeded = engine.seed(
            {"sensor.temperature": "21", "sensor.critical": "31"},
            units={"sensor.critical": "°C"},
            sources={"sensor.critical": "Boiler temperature"},
        )
        self.assertEqual(seeded.title, "Critical")
        self.assertEqual(seeded.source, "Boiler temperature")
        self.assertEqual(seeded.actual, "31°C")
        self.assertEqual(engine.current.attention_page, "energy")
        changed, alert = engine.update("sensor.critical", "29")
        self.assertTrue(changed)
        self.assertEqual(alert.title if alert else None, "Notice")
        changed, alert = engine.update("sensor.temperature", "17")
        self.assertTrue(changed)
        self.assertIsNone(alert)

    def test_identical_selected_alert_is_deduplicated(self) -> None:
        engine = RuleEngine([rule()])
        changed, first = engine.update(
            "sensor.temperature", "21", "°C", "Freezer probe"
        )
        self.assertTrue(changed)
        changed, updated = engine.update(
            "sensor.temperature", "22", "°C", "Freezer probe"
        )
        self.assertTrue(changed)
        self.assertEqual(first.rule_id, updated.rule_id)
        self.assertEqual(updated.actual, "22°C")
        self.assertEqual(updated.source, "Freezer probe")

    def test_sensor_status_tracks_warning_breach_and_hysteresis(self) -> None:
        engine = RuleEngine([rule(threshold=80, warning_threshold=60, hysteresis=2)])
        self.assertEqual(engine.update("sensor.temperature", "59")[0], False)
        self.assertEqual(engine.sensor_status("sensor.temperature"), 1)
        engine.update("sensor.temperature", "60")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 2)
        engine.update("sensor.temperature", "81")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 3)
        engine.update("sensor.temperature", "79")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 3)
        engine.update("sensor.temperature", "78")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 2)

    def test_lower_limit_warning_band_runs_in_the_opposite_direction(self) -> None:
        engine = RuleEngine(
            [
                rule(
                    direction="below",
                    threshold=5,
                    warning_threshold=7,
                    hysteresis=1,
                )
            ]
        )
        engine.update("sensor.temperature", "8")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 1)
        engine.update("sensor.temperature", "7")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 2)
        engine.update("sensor.temperature", "4")
        self.assertEqual(engine.sensor_status("sensor.temperature"), 3)

    def test_recovered_preempted_rule_is_reported_for_suppression_cleanup(self) -> None:
        engine = RuleEngine(
            [
                rule(priority=1, threshold=20),
                rule(
                    entity_id="sensor.critical",
                    threshold=30,
                    priority=3,
                    title="Critical",
                ),
            ]
        )
        engine.seed({"sensor.temperature": "21", "sensor.critical": "31"})
        lower_rule_id = engine.rules[0].rule_id

        changed, selected = engine.update("sensor.temperature", "18")

        self.assertFalse(changed)
        self.assertEqual(selected.title, "Critical")
        self.assertEqual(engine.take_cleared_rule_ids(), [lower_rule_id])
        self.assertEqual(engine.active_rule_ids(), [engine.rules[1].rule_id])
        self.assertEqual(engine.take_cleared_rule_ids(), [])

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
