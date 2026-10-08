"""Project Cydex: dashboard updates and priority alerts for ESPHome CYDs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .alerts import AlertCommand, RuleEngine
from .dashboard import dashboard_action_data, dashboard_entities, validate_dashboard
from .dashboard_transport import (
    DASHBOARD_COALESCE_DELAY,
    DASHBOARD_SECTION_DELAY,
    dashboard_action_batches,
)
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
    migrate_entry_title,
)
from .service_map import ActionServices, async_get_device_action_services

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the camera-token-authenticated bounded thumbnail endpoint once."""
    from .camera_thumbnail import async_setup_thumbnails

    await async_setup_thumbnails(hass)
    return True


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
    dashboard_update_dirty: bool = False
    dashboard_task: asyncio.Task[None] | None = None
    stopped: bool = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Start observing the configured entities and sending alert actions."""
    from homeassistant.core import callback
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

    migrated_title = migrate_entry_title(entry.title)
    if migrated_title != entry.title:
        hass.config_entries.async_update_entry(entry, title=migrated_title)

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
            "does not expose all eight bounded update_dashboard_* actions. "
            "The legacy 126-argument action is deliberately not used. Update the CYD firmware "
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
            unit = new_state.attributes.get("unit_of_measurement", "")
            source = new_state.attributes.get("friendly_name", entity_id)
            changed, current = engine.update(
                entity_id,
                new_state.state,
                unit if isinstance(unit, str) else "",
                source if isinstance(source, str) and source.strip() else entity_id,
            )
            cleared_rule_ids = engine.take_cleared_rule_ids()
            if changed:
                _schedule_transition(
                    hass,
                    runtime,
                    runtime.current_command,
                    current,
                    cleared_rule_ids,
                )
                runtime.current_command = current
            elif cleared_rule_ids:
                _schedule_transition(
                    hass, runtime, None, None, cleared_rule_ids
                )
        if entity_id in selected_dashboard_entities:
            _schedule_dashboard_update(hass, runtime)

    if tracked_entities:
        unsubscribe = async_track_state_change_event(
            hass, tracked_entities, state_changed
        )
        entry.async_on_unload(unsubscribe)

    current_states: dict[str, str] = {}
    current_units: dict[str, str] = {}
    current_sources: dict[str, str] = {}
    for entity_id in tracked_entities:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        current_states[entity_id] = state.state
        unit = state.attributes.get("unit_of_measurement", "")
        current_units[entity_id] = unit if isinstance(unit, str) else ""
        source = state.attributes.get("friendly_name", entity_id)
        current_sources[entity_id] = (
            source if isinstance(source, str) and source.strip() else entity_id
        )
    initial = engine.seed(current_states, current_units, current_sources)
    if initial is not None:
        _schedule_transition(hass, runtime, None, initial)
        runtime.current_command = initial
    if action_services.dashboard_actions:
        _schedule_dashboard_update(hass, runtime)

        @callback
        def refresh_dashboard(_now: Any) -> None:
            # Recover after a brief device disconnect even when entity states
            # have not changed. This is bounded/paced, not a retry loop.
            _schedule_dashboard_update(hass, runtime)

        entry.async_on_unload(async_track_time_interval(
            hass, refresh_dashboard, timedelta(seconds=30)
        ))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop listeners and clear this integration's currently shown alert."""
    runtime: Runtime | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if runtime is not None:
        runtime.stopped = True
        if runtime.dashboard_task is not None:
            runtime.dashboard_task.cancel()
            try:
                await runtime.dashboard_task
            except asyncio.CancelledError:
                pass
            runtime.dashboard_task = None
            runtime.dashboard_update_scheduled = False
    if runtime is not None and runtime.current_command is not None:
        await _async_send_transition(
            hass,
            runtime,
            runtime.current_command,
            None,
            runtime.engine.active_rule_ids(),
        )
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
    from .camera_thumbnail import STORE_KEY, selected_cameras

    if (store := hass.data.get(STORE_KEY)) is not None:
        await store.prune(selected_cameras(hass))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload subscriptions and active-alert state after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _schedule_transition(
    hass: HomeAssistant,
    runtime: Runtime,
    previous: AlertCommand | None,
    current: AlertCommand | None,
    cleared_rule_ids: list[str] | None = None,
) -> None:
    """Queue clear/replace calls without blocking HA's event listener."""
    hass.async_create_task(
        _async_send_transition(
            hass, runtime, previous, current, cleared_rule_ids or []
        )
    )


def _schedule_dashboard_update(hass: HomeAssistant, runtime: Runtime) -> None:
    """Coalesce rapid sensor changes into one latest-state display update."""
    if runtime.stopped or not runtime.service_names.dashboard_actions:
        return
    if runtime.dashboard_update_scheduled:
        runtime.dashboard_update_dirty = True
        return
    runtime.dashboard_update_scheduled = True
    runtime.dashboard_task = hass.async_create_task(_async_send_dashboard_update(hass, runtime))


async def _async_send_dashboard_update(hass: HomeAssistant, runtime: Runtime) -> None:
    """Send one small section at a time; coalesce changes without losing the last."""
    action = "snapshot"
    try:
        while not runtime.stopped:
            await asyncio.sleep(DASHBOARD_COALESCE_DELAY)
            async with runtime.transition_lock:
                if runtime.stopped:
                    return
                runtime.dashboard_update_dirty = False
                batches = dashboard_action_batches(dashboard_action_data(
                    hass,
                    runtime.dashboard_options,
                    runtime.engine,
                ))
                for index, ((action, data), service) in enumerate(
                    zip(batches, runtime.service_names.dashboard_actions, strict=True)
                ):
                    if runtime.stopped:
                        return
                    _LOGGER.debug("Dashboard section %s: %d arguments", action, len(data))
                    await hass.services.async_call(ESPHOME_DOMAIN, service, data, blocking=True)
                    if index + 1 < len(batches):
                        await asyncio.sleep(DASHBOARD_SECTION_DELAY)
            if not runtime.dashboard_update_dirty:
                break
    except asyncio.CancelledError:
        raise
    except Exception as err:
        # Never retry in a tight loop during an API disconnect/panic. A later
        # entity event or integration reload sends a fresh complete snapshot.
        # Exceptions from HA may contain the complete service data (including a
        # camera token). Log the section/error class, never the payload/message.
        _LOGGER.warning(
            "Dashboard update failed for %s: section=%s error_type=%s; "
            "a later event or 30-second refresh will send a full snapshot",
            runtime.device_name, action, type(err).__name__,
        )
    finally:
        runtime.dashboard_update_scheduled = False
        runtime.dashboard_task = None


async def _async_send_transition(
    hass: HomeAssistant,
    runtime: Runtime,
    previous: AlertCommand | None,
    current: AlertCommand | None,
    cleared_rule_ids: list[str] | None = None,
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
        cleared_ids = set(cleared_rule_ids or [])
        same_incident = bool(
            previous is not None
            and current is not None
            and current.rule_id
            and previous.rule_id == current.rule_id
        )
        for rule_id in cleared_ids:
            if previous is not None and previous.rule_id == rule_id:
                continue
            await call_service(
                runtime.service_names.clear_alert,
                {
                    "priority": runtime.engine.rule_priority(rule_id),
                    "rule_id": rule_id,
                    "incident_active": False,
                },
            )
        if previous is not None and not same_incident:
            await call_service(
                runtime.service_names.clear_alert,
                {
                    "priority": previous.priority,
                    "rule_id": previous.rule_id,
                    "incident_active": (
                        current is not None
                        and runtime.engine.is_rule_active(previous.rule_id)
                    ),
                },
            )
        if current is not None:
            await call_service(
                runtime.service_names.display_alert,
                {
                    "priority": current.priority,
                    "title": current.title,
                    "message": current.message,
                    "rule_id": current.rule_id,
                    "actual": current.actual,
                    "limit": current.limit,
                    "source": current.source,
                    "dismissible": True,
                },
            )
        if runtime.service_names.focus_page is not None:
            attention_page = (
                current.attention_page
                if current is not None
                else "none"
            )
            should_update_focus = not same_incident and (
                attention_page != "none"
                or (previous is not None and previous.attention_page != "none")
            )
            if should_update_focus:
                await call_service(
                    runtime.service_names.focus_page,
                    {"page": attention_page},
                )


__all__ = ["async_setup", "async_setup_entry", "async_unload_entry"]
