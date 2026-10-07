# Project Cyder

Project Cyder configures dashboard sensors and priority alerts for an ESPHome
CYD display from Home Assistant.

## Requirements

- Home Assistant with HACS installed.
- CYD firmware exposing `display_alert`, `clear_alert`, `dismiss_alert`, and
  `update_dashboard` ESPHome actions. Rules that route attention also need the
  `focus_page` action.

The firmware is installed separately. This repository does not include ESPHome
YAML or install firmware. Install matching firmware before configuring dashboard
features that extend the `update_dashboard` action; ordinary entity selections
then stay in Home Assistant. Snapshot support also requires an HTTP(S) Home
Assistant internal URL that the CYD can reach on the local network.

## Current release

Version 0.2.0 adds HA-configurable dashboard pages and entities to main/daily
energy sensors, four named power metrics, Claude used/remaining display, and
Notice, Warning, and Critical threshold alerts. Version 0.2.1 fixes empty
optional entity selectors in the Dashboard and usage options form.

Select climate, light, and switch entities once; Project Cyder groups them by
Home Assistant Area, with unassigned entities collected in **Unassigned**. The
display supports up to four Areas and five selected devices per Area. A room
opens a compact device list: thermostats open target/mode controls, while lights
and switches toggle directly. The optional climate entity remains available for
the Home overview.

Claude plus up to three additional AI providers (such as Codex, Gemini, or
OpenAI) can show session and weekly usage. Providers can use sensors from any HA
integration; credentials are not stored on the ESPHome device. Configure idle-
aware rotation, page visibility and dock/rotation order, per-alert page routing,
and up to five named Sensor Monitor rows, including text-valued states. A routed
page stays visible for ten seconds after its alert clears unless the display is
touched; then the previous page resumes.

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
selected room climate/light/switch entities, an optional climate entity for the
Home overview, optional named power metrics, and up to five named entities for
the Sensor Monitor page. Room controls use Home Assistant Areas automatically;
configuration rejects more than four Areas or five selected controls in one
Area. Sensor rows support numeric and textual
states, include their HA units, and omit unselected rows. Configure Claude and
additional provider quota entities. Toggle the AI, Climate, Sensors, and Energy
pages to remove them from the dock and rotation; Home and Display Settings remain
available. Set the six page-order slots to arrange both the dock and rotation
cycle; Camera remains a header shortcut. Disabled pages are skipped and the
remaining dock tabs expand to fill the space. Automatic rotation can be turned
off or set to wait 10–120 seconds while the display is idle. Temperature and HVAC controls
are sent to the selected entity using its supported modes, bounds, step size,
and Celsius/Fahrenheit unit. Main power is converted to kW, daily energy to kWh,
and additional power metrics to W when their HA units are recognized. Choose
whether extra Claude usage shows credits used or remaining. Remaining is the
configured limit minus used credits.

For snapshots, select an optional Camera entity, enable its page, and choose a
10–120 second refresh interval. Camera is an optional sixth rotation destination
and has a small header shortcut; page-order slots determine the relative order of
the five main dock destinations. The CYD fetches Home Assistant's camera-proxy
JPEG only while the page is selected, then releases the image buffer when leaving. Configure HA's
**Internal URL** to an address reachable by the CYD. Project Cyder sends the
camera entity's rotating, short-lived proxy token to the device in RAM; it does
not save that token or a long-lived HA credential in options. A camera may need
to supply a small baseline JPEG for the CYD's decoder and memory limits. This
snapshot path is not live video, and should be hardware-tested before relying on
it.

Each additional provider card accepts optional session and weekly quota
percentage sensors. Unavailable sensor states display as `--%` and suppress the
corresponding progress bar. The compact AI page shows Claude plus up to three
configured providers at once.

In **Alert rules**, choose numeric entities, direction, threshold, hysteresis,
priority, title, and message. Comparisons are strict; an active rule clears
after its value crosses the threshold by the configured hysteresis. Invalid or
unavailable states do not clear active alerts. The highest-priority active rule
is shown: 1 for Notice, 2 for Warning, and 3 for Critical. The first configured
rule wins ties. Each rule may focus a related dashboard page while its alert is
active. Once cleared, that page stays visible for 10 seconds so there is time to
inspect it, then the previously open page returns unless the screen is touched.
Choose “Keep current page” to leave the display where it is.

Alerts sent by Project Cyder cannot be dismissed on the display. They remain
active until their rules clear because the firmware does not report touchscreen
dismissals to Home Assistant.

## Roadmap

- Expand attention-driven rotation beyond per-alert page focus.
- Prototype MJPEG only after the snapshot path passes physical-device memory and
  responsiveness tests.
- Verify screen rendering and touch behavior on the CYD, then add screenshots.

Report bugs at <https://github.com/ijtan/project-cyder/issues>.

## License

Project Cyder is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
