# Project Cyder

Project Cyder configures Home Assistant threshold alerts for ESPHome CYD
displays. Home Assistant monitors numeric entities and sends priority alerts to
the selected display through its ESPHome actions.

## Requirements

- Home Assistant with HACS installed.
- An ESPHome display exposing the `display_alert`, `clear_alert`, and
  `dismiss_alert` actions.

This integration configures alerts only. It does not install firmware or
configure dashboard pages, usage display preferences, or cameras.

## Install

1. In HACS, add `ijtan/project-cyder` as a custom repository with the
   **Integration** category.
2. Download Project Cyder and restart Home Assistant.
3. Add **Project Cyder** in **Settings > Devices & services** and select the
   ESPHome display.
4. Open the integration options and add alert rules.

Each rule selects a numeric entity, direction, threshold, hysteresis, priority,
title, and message. Threshold comparisons are strict. An active rule clears
after its value crosses the threshold by the configured hysteresis. Invalid or
unavailable states do not clear active alerts. The highest-priority active rule
is shown: 1 for Notice, 2 for Warning, and 3 for Critical. The first configured
rule wins ties.

Alerts sent by Project Cyder cannot be dismissed on the display. The firmware
does not report touchscreen dismissals to Home Assistant, so alerts remain
active until their rules clear.

## Tests

Run the unit tests with Python 3.12 or newer:

```sh
python3 -m unittest discover -s tests -v
```

Report bugs at <https://github.com/ijtan/project-cyder/issues>.
