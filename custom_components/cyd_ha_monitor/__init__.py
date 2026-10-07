"""Project Cyder: dashboard updates and priority alerts for ESPHome CYDs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .alerts import AlertCommand, RuleEngine
from .dashboard import dashboard_action_data, dashboard_entities, validate_dashboard
from .const import (
    CONF_ATTENTION_PAGE,
    CONF_DEVICE_ID,
    CONF_DASHBOARD_SETTINGS_SAVED,
    CONF_RULES,
    DOMAIN,
    ESPHOME_DOMAIN,
    ISSUE_ACTIONS_UNAVAILABLE,
    ISSUE_DASHBOARD_ACTION_UNAVAILABLE,
    ISSUE_FOCUS_PAGE_ACTION_UNAVAILABLE,
)
from .service_map import ActionServices, async_get_device_action_services

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Runtime:
    """Runtime state for one configured CYD."""

    engine: RuleEngine
    service_names: ActionServices
    device_name: str
    current_command: AlertCommand | None = None
    transition_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    dashboard_options: dict[str, Any] = field(default_factory=dict)
    dashboard_entities: set[str] = field(default_factory=set)
    dashboard_settings_saved: bool = False
    dashboard_update_scheduled: bool = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start observing the configured entities and sending alert actions."""
    from homeassistant.core import callback
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.event import async_track_state_change_event

    resolved = async_get_device_action_services(hass, entry.data[CONF_DEVICE_ID])
    issue_id = f"{ISSUE_ACTIONS_UNAVAILABLE}_{entry.entry_id}"
    if resolved is None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            data={"entry_id": entry.entry_id},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_ACTIONS_UNAVAILABLE,
            translation_placeholders={"device_name": entry.title},
        )
        _LOGGER.error(
            "ESPHome alert actions are unavailable for %s. Reconfigure the selected "
            "device and install/enable firmware actions display_alert, clear_alert, "
            "and dismiss_alert, then reload this integration entry.",
            entry.title,
        )
        return False

    device_name, action_services = resolved
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    rules = entry.options.get(CONF_RULES, [])
    engine = RuleEngine(rules)
    attention_routing_configured = any(
        isinstance(rule, dict) and rule.get(CONF_ATTENTION_PAGE, "none") != "none"
        for rule in rules
    )
    focus_page_issue_id = f"{ISSUE_FOCUS_PAGE_ACTION_UNAVAILABLE}_{entry.entry_id}"
    if attention_routing_configured and action_services.focus_page is None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            focus_page_issue_id,
            data={"entry_id": entry.entry_id},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FOCUS_PAGE_ACTION_UNAVAILABLE,
            translation_placeholders={"device_name": entry.title},
        )
        _LOGGER.warning(
            "Attention page routing is configured for %s, but its ESPHome firmware "
            "does not expose the focus_page action. Install matching CYD firmware.",
            entry.title,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, focus_page_issue_id)
    try:
        dashboard_options = validate_dashboard(entry.options, hass)
    except (TypeError, ValueError):
        _LOGGER.exception("Invalid dashboard settings for %s", entry.title)
        dashboard_options = validate_dashboard({})
    selected_dashboard_entities = dashboard_entities(dashboard_options)
    dashboard_sync_configured = bool(
        selected_dashboard_entities
        or entry.options.get(CONF_DASHBOARD_SETTINGS_SAVED, False)
    )
    dashboard_issue_id = f"{ISSUE_DASHBOARD_ACTION_UNAVAILABLE}_{entry.entry_id}"
    if dashboard_sync_configured and action_services.update_dashboard is None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            dashboard_issue_id,
            data={"entry_id": entry.entry_id},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DASHBOARD_ACTION_UNAVAILABLE,
            translation_placeholders={"device_name": entry.title},
        )
        _LOGGER.warning(
            "Dashboard sensors are configured for %s, but its ESPHome firmware "
            "does not expose the update_dashboard action. Update the CYD firmware "
            "and reload this integration entry.",
            entry.title,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, dashboard_issue_id)

    runtime = Runtime(
        engine,
        action_services,
        device_name,
        dashboard_options=dashboard_options,
        dashboard_entities=selected_dashboard_entities,
        dashboard_settings_saved=entry.options.get(
            CONF_DASHBOARD_SETTINGS_SAVED, False
        ),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    tracked_entities = engine.entities | selected_dashboard_entities

    @callback
    def state_changed(event: Event) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is not None and entity_id in engine.entities:
            changed, current = engine.update(entity_id, new_state.state)
            if changed:
                _schedule_transition(hass, runtime, runtime.current_command, current)
                runtime.current_command = current
        if entity_id in selected_dashboard_entities:
            _schedule_dashboard_update(hass, runtime)

    if tracked_entities:
        unsubscribe = async_track_state_change_event(
            hass, tracked_entities, state_changed
        )
        entry.async_on_unload(unsubscribe)

    current_states = {
        entity_id: state.state
        for entity_id in tracked_entities
        if (state := hass.states.get(entity_id)) is not None
    }
    initial = engine.seed(current_states)
    if initial is not None:
        _schedule_transition(hass, runtime, None, initial)
        runtime.current_command = initial
    if (
        runtime.dashboard_settings_saved or selected_dashboard_entities
    ) and action_services.update_dashboard is not None:
        _schedule_dashboard_update(hass, runtime)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop listeners and clear this integration's currently shown alert."""
    runtime: Runtime | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime is not None and runtime.current_command is not None:
        await _async_send_transition(
            hass,
            runtime,
            runtime.current_command,
            None,
        )
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload subscriptions and active-alert state after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _schedule_transition(
    hass: HomeAssistant,
    runtime: Runtime,
    previous: AlertCommand | None,
    current: AlertCommand | None,
) -> None:
    """Queue clear/replace calls without blocking HA's event listener."""
    hass.async_create_task(_async_send_transition(hass, runtime, previous, current))


def _schedule_dashboard_update(hass: HomeAssistant, runtime: Runtime) -> None:
    """Coalesce rapid sensor changes into one latest-state display update."""
    if (
        runtime.dashboard_update_scheduled
        or runtime.service_names.update_dashboard is None
    ):
        return
    runtime.dashboard_update_scheduled = True
    hass.async_create_task(_async_send_dashboard_update(hass, runtime))


async def _async_send_dashboard_update(hass: HomeAssistant, runtime: Runtime) -> None:
    """Push a formatted snapshot of the configured dashboard sensors."""
    service = runtime.service_names.update_dashboard
    if service is None:
        return
    async with runtime.transition_lock:
        runtime.dashboard_update_scheduled = False
        try:
            await hass.services.async_call(
                ESPHOME_DOMAIN,
                service,
                dashboard_action_data(
                    hass,
                    {
                        **runtime.dashboard_options,
                        CONF_DASHBOARD_SETTINGS_SAVED: runtime.dashboard_settings_saved,
                    },
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Could not update dashboard metrics on ESPHome device %s",
                runtime.device_name,
            )


async def _async_send_transition(
    hass: HomeAssistant,
    runtime: Runtime,
    previous: AlertCommand | None,
    current: AlertCommand | None,
) -> None:
    """Serialize clear/replace service calls for one ESPHome device."""

    async def call_service(service: str, data: dict[str, Any]) -> None:
        try:
            await hass.services.async_call(ESPHOME_DOMAIN, service, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Could not update alert on ESPHome device %s",
                runtime.device_name,
            )

    async with runtime.transition_lock:
        if previous is not None:
            await call_service(
                runtime.service_names.clear_alert,
                {"priority": previous.priority},
            )
        if current is not None:
            await call_service(
                runtime.service_names.display_alert,
                {
                    "priority": current.priority,
                    "title": current.title,
                    "message": current.message,
                    # HA cannot learn about touchscreen dismissals, so alerts
                    # stay active until a sensor update clears them.
                    "dismissible": False,
                },
            )
        if runtime.service_names.focus_page is not None:
            attention_page = (
                current.attention_page
                if current is not None
                else "none"
            )
            if attention_page != "none" or (
                previous is not None and previous.attention_page != "none"
            ):
                await call_service(
                    runtime.service_names.focus_page,
                    {"page": attention_page},
                )


__all__ = ["async_setup_entry", "async_unload_entry"]
