"""Regression coverage for the bounded firmware transport contract."""

import unittest
from types import SimpleNamespace

from custom_components.cyd_ha_monitor.dashboard import dashboard_action_data, validate_dashboard
from custom_components.cyd_ha_monitor.dashboard_transport import (
    DASHBOARD_ACTIONS, DASHBOARD_SECTION_FIELDS, MAX_DASHBOARD_ARGUMENTS,
    dashboard_action_batches,
)


class DashboardTransportTests(unittest.TestCase):
    def test_all_fields_are_sent_in_eight_small_sections_including_empty_values(self):
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None))
        payload = dashboard_action_data(hass, validate_dashboard({}))
        batches = dashboard_action_batches(payload)
        self.assertEqual(tuple(name for name, _ in batches), DASHBOARD_ACTIONS)
        self.assertEqual(len(batches), 8)
        self.assertEqual(max(len(data) for _, data in batches), MAX_DASHBOARD_ARGUMENTS)
        combined = {key: value for _, data in batches for key, value in data.items()}
        self.assertEqual(combined, payload)
        self.assertEqual(len(combined), 126)
        self.assertTrue(all(len(fields) <= 21 for fields in DASHBOARD_SECTION_FIELDS.values()))

    def test_rejects_payload_schema_drift(self):
        with self.assertRaises(ValueError):
            dashboard_action_batches({"unknown_field": 1})
