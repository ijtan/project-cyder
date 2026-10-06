# Project Cyder

Project Cyder configures Home Assistant threshold alerts for ESPHome CYD
displays. Home Assistant monitors numeric entities and sends priority alerts to
the selected display through its ESPHome actions.

## Requirements

- Home Assistant with HACS installed.
- An ESPHome display exposing the `display_alert`, `clear_alert`, and
  `dismiss_alert` actions.

This integration configures alerts only. This repository does not include
ESPHome YAML or install firmware. Dashboard pages, usage display preferences,
and cameras are not configurable here.

## Current release

Version 0.1.0 lets you select an ESPHome display and configure numeric-entity
threshold alerts in Home Assistant. It sends Notice, Warning, and Critical
alerts through the display's ESPHome actions. A live Home Assistant setup and
alert call have not yet been verified.

## Install

1. Install and set up [HACS](https://www.hacs.xyz/docs/use/) if it is not
   already installed.
2. Open Project Cyder in HACS with this button:

[![Open Project Cyder in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ijtan&repository=project-cyder&category=integration)

   This link opens the custom repository in HACS, so you do not need to add it
   manually first. If adding it manually, use `ijtan/project-cyder` and the
   **Integration** category.
3. Download Project Cyder in HACS and restart Home Assistant.

After installation, use this button to start setup in Home Assistant:

[![Add Project Cyder to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=cyd_ha_monitor)

You can also add **Project Cyder** from **Settings > Devices & services**.
Select the ESPHome display, then open the integration options to add alert rules.

Each rule selects a numeric entity, direction, threshold, hysteresis, priority,
title, and message. Threshold comparisons are strict. An active rule clears
after its value crosses the threshold by the configured hysteresis. Invalid or
unavailable states do not clear active alerts. The highest-priority active rule
is shown: 1 for Notice, 2 for Warning, and 3 for Critical. The first configured
rule wins ties.

Alerts sent by Project Cyder cannot be dismissed on the display. The firmware
does not report touchscreen dismissals to Home Assistant, so alerts remain
active until their rules clear.

## Roadmap

- Configure dashboard entities and used/remaining and reset presentation from
  Home Assistant.
- Add camera selection, starting with snapshots.
- Verify screen rendering and touch behavior on the CYD, then add screenshots.

Report bugs at <https://github.com/ijtan/project-cyder/issues>.

## License

Project Cyder is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
