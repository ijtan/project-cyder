# Project Cyder

Project Cyder configures dashboard sensors and priority alerts for an ESPHome
CYD display from Home Assistant.

## Requirements

- Home Assistant with HACS installed.
- CYD firmware exposing `display_alert`, `clear_alert`, `dismiss_alert`, and
  `update_dashboard` ESPHome actions.

The firmware is installed separately. This repository does not include ESPHome
YAML or install firmware. Update the device once to add `update_dashboard`;
sensor and presentation changes are then made in Home Assistant. Camera setup is
not supported yet.

## Current release

Version 0.2.0 supports HA selection of the main power and daily energy sensors,
up to four named power metrics, Claude usage sources and used/remaining display,
plus Notice, Warning, and Critical threshold alerts.

## Install

1. Install and set up [HACS](https://www.hacs.xyz/docs/use/) if it is not
   already installed.
2. Open Project Cyder in HACS with this button:

[![Open Project Cyder in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ijtan&repository=project-cyder&category=integration)

   This link opens the custom repository in HACS, so you do not need to add it
   manually first. If adding it manually, use `ijtan/project-cyder` and the
   **Integration** category.
3. Download Project Cyder in HACS and restart Home Assistant.
4. Install CYD firmware exposing the required actions.

After installation, use this button to start setup in Home Assistant:

[![Add Project Cyder to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=cyd_ha_monitor)

You can also add **Project Cyder** from **Settings > Devices & services**.
Select the ESPHome display, then open its options.

In **Dashboard and usage**, choose the main power and daily energy sensors,
optional named power metrics, and Claude usage entities. Main power is converted
to kW, daily energy to kWh, and additional power metrics to W when their HA units
are recognized. Choose whether extra Claude usage shows credits used or
remaining. Remaining is the configured limit minus used credits.

In **Alert rules**, choose numeric entities, direction, threshold, hysteresis,
priority, title, and message. Comparisons are strict; an active rule clears
after its value crosses the threshold by the configured hysteresis. Invalid or
unavailable states do not clear active alerts. The highest-priority active rule
is shown: 1 for Notice, 2 for Warning, and 3 for Critical. The first configured
rule wins ties.

Alerts sent by Project Cyder cannot be dismissed on the display. They remain
active until their rules clear because the firmware does not report touchscreen
dismissals to Home Assistant.

## Roadmap

- Add camera selection, starting with snapshots.
- Verify screen rendering and touch behavior on the CYD, then add screenshots.

Report bugs at <https://github.com/ijtan/project-cyder/issues>.

## License

Project Cyder is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
