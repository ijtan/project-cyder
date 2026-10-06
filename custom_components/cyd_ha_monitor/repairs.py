"""Repairs flows for CYD ESPHome action availability."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import FlowType, RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class ActionsUnavailableRepairFlow(RepairsFlow):
    """Forward the user to device reconfiguration after firmware/service changes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        if user_input is not None:
            entry_id = self.data.get("entry_id")
            if not isinstance(entry_id, str):
                return self.async_abort(reason="entry_not_found")
            if (entry := self.hass.config_entries.async_get_entry(entry_id)) is None:
                return self.async_abort(reason="entry_not_found")
            result = await self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": SOURCE_RECONFIGURE,
                    "entry_id": entry_id,
                    "unique_id": entry.unique_id,
                },
            )
            return self.async_abort(
                reason="reconfigure",
                next_flow=(FlowType.CONFIG_FLOW, result["flow_id"]),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the repair flow for the missing ESPHome actions issue."""
    return ActionsUnavailableRepairFlow()
