# Project Cydex

Project Cydex configures dashboard sensors and priority alerts for an ESPHome
CYD display from Home Assistant.

## Requirements

- Home Assistant 2026.10.0 or newer with HACS installed (v0.2.4's native camera
  authentication/view path is validated against 2026.10.0).
- CYD firmware exposing `display_alert`, `clear_alert`, `dismiss_alert`, and all
  eight bounded dashboard actions: `update_dashboard_layout`, `_controls`,
  `_sensors`, `_energy`, `_claude`, `_provider_1`, `_provider_2`, and `_provider_3`
  (each name starts with `update_dashboard`). Attention routing also needs `focus_page`.

The firmware is installed separately. This repository does not include ESPHome
YAML or install firmware. Install matching CYD firmware before using the updated
alert payload (`rule_id`, live reading, limit, and incident-clear state) or
dashboard status colors; older action schemas may reject the new fields. For
upgrades, keep Project Cydex disabled while installing the integration and matching
firmware; confirm the new firmware boots and HA discovers all eight actions before
enabling/reloading it. Version 0.2.3 deliberately refuses the legacy oversized
`update_dashboard` action. Ordinary entity selections then stay in HA. Snapshot support
also requires an HTTP(S) Home Assistant internal URL that the CYD can reach on
the local network.

## Current release

**Version 0.2.4** fixes alert priority dropdowns after reopening saved rules,
uses automatically detected local HA URLs, and adds a bounded colour camera
thumbnail endpoint. Install matching `qoi_v1` firmware before updating/enabling
camera downloads. Physical camera validation remains pending at publication.

Version 0.2.3 fixes cleared options returning after Submit and makes empty
selections authoritative. Dashboard transport now uses eight sequential actions
with at most 21 arguments each, rather than one 126-argument request. Calls are
paced 100 ms apart, rapid changes are coalesced, pending updates are cancelled
on unload/disable, and a 30-second refresh resynchronizes after a disconnect.
Failure logs contain section/error class, not payloads or camera tokens.

Alert form defaults convert saved numeric
priorities to the strings required by HA's dropdown, while stored/runtime
priorities remain integers. Camera links resolve an automatically detected local
HA URL when the explicit internal URL is empty. The camera path needs matching
`qoi_v1` firmware; the integration alone cannot correct the old decoded-image budget.

This is a targeted mitigation for an observed ESP32 API argument-allocation
panic, **not an upstream-prescribed best practice or a proven on-device fix**.
Local tests pass; physical runtime validation is still pending at publication.
Sections apply separately: a disconnect can leave a partial dashboard until the
next full refresh. Keep USB logs open for initial enable/reconnect testing.

Version 0.2.0 adds HA-configurable dashboard pages and entities to main/daily
energy sensors, four named power metrics, Claude used/remaining display, and
Notice, Warning, and Critical threshold alerts. Version 0.2.1 fixes empty
optional entity selectors in the Dashboard and usage options form. Version 0.2.2
rebrands the integration as Project Cydex, fixes current Home Assistant Area
Registry lookups, and adds live alert readings, acknowledge/snooze controls, and
optional warning bands for theme-aware sensor status colors.

Select climate, light, and switch entities once; Project Cydex groups them by
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
2. Open Project Cydex in HACS with this button:

[![Open Project Cydex in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ijtan&repository=project-cyder&category=integration)

   This link opens the custom repository in HACS, so you do not need to add it
   manually first. If adding it manually, use `ijtan/project-cyder` and the
   **Integration** category.
3. Download Project Cydex in HACS and restart Home Assistant.
4. Install CYD firmware exposing the required actions.

After installation, use this button to start setup in Home Assistant:

[![Add Project Cydex to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=cyd_ha_monitor)

You can also add **Project Cydex** from **Settings > Devices & services**.
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

Clear an optional source with **×**, then **Submit** to remove it. Saved selections
are suggestions, not defaults that can restore removed entities. Each dashboard
snapshot is authoritative: unassigned sources send placeholders/disabled rows,
not old readings or firmware-selected sensors. Removing the main power source
clears its reading and hides the graph; a separately assigned daily-energy source
continues to display. Matching extension-owned firmware also starts unassigned
and contains no native HA sensor fallback subscriptions.

For snapshots, select an optional Camera entity, enable its page, and choose a
10–120 second refresh interval. Camera is an optional sixth rotation destination
and has a small header shortcut; page-order slots determine the relative order of
the five main dock destinations. The CYD fetches a bounded HA-generated colour
thumbnail only while the page is selected, then releases the image buffer when leaving.
Cydex uses HA's automatically detected internal URL when no explicit
**Internal URL** is set; it never falls back to an external/cloud URL.
An explicit internal URL, if set, must be reachable by the CYD. Project Cydex sends the
camera entity's rotating, short-lived proxy token to the device in RAM; it does
not save that token or a long-lived HA credential in options. HA decodes the source
snapshot (including baseline/progressive JPEG or PNG), preserves its aspect ratio,
and sends a letterboxed **128×72 QOI** thumbnail. This uses 18,432 bytes of
decoded RGB565 pixels and a 2,048-byte streaming receive buffer on matching
firmware, without a full compressed JPEG buffer. The endpoint inherits HA camera
authentication and allows only cameras selected by enabled Cydex entries.
Only one acquisition runs at a time; requests return a cached thumbnail or
immediate 503 while a background acquisition runs. Acquisitions are throttled to
at least ten seconds apart per camera, cached frames expire after sixty seconds, and
caches/tasks are dropped when no entry selects them. Sources are bounded to
4 MiB/12 million pixels; responses to the CYD are at most 36,886 bytes, decoded
incrementally. Slow/offline cameras may still fail. This
snapshot path is not live video, and should be hardware-tested before relying on
it.

**Known camera limit on firmware `918c9f0c`:** its 256×144 RGB565 frame needs up to
72 KiB of decoded-image RAM, exceeding observed free heap before decoder overhead.
Use corrected `qoi_v1` firmware before installing v0.2.4 and attempting downloads.
Matching firmware rejects old direct-JPEG links, preallocates the thumbnail only
with at least 48 KiB free/24 KiB largest block (larger allowances for HTTPS),
closes stalled downloads, and performs only two faster ten-second retries before
returning to the configured refresh interval. Labels describe receipt time, not
the camera's capture time: a served frame may already be up to sixty seconds old.

Each additional provider card accepts optional session and weekly quota
percentage sensors. Unavailable sensor states display as `--%` and suppress the
corresponding progress bar. The compact AI page shows Claude plus up to three
configured providers at once.

In **Alert rules**, choose numeric entities, direction, limit, optional warning
threshold, hysteresis, priority, title, and message. Thresholds use the sensor's
own units. Comparisons are strict; an active rule clears after its value crosses
the limit by the configured hysteresis. Invalid or unavailable states do not
clear active alerts. The optional warning threshold colors a matching sensor row
amber as it approaches the limit; breached rows stay red even after the alert is
acknowledged. Colors adapt to the selected display theme. The highest-priority
active rule is shown: 1 for Notice, 2 for Warning, and 3 for Critical. The first
configured rule wins ties. Each rule may focus a related dashboard page while
its alert is active. Once cleared, that page stays visible for 10 seconds so
there is time to inspect it, then the previously open page returns unless the
screen is touched. Choose “Keep current page” to leave the display where it is.

On the alert, **Ack until clear** hides that incident until its rule recovers;
its sensor row remains red while breached. **Snooze 15 min** hides it temporarily
and shows it again if it is still active. A different, higher-priority alert can
still appear while an incident is acknowledged or snoozed.

## Roadmap

- Expand attention-driven rotation beyond per-alert page focus.
- Prototype MJPEG only after the snapshot path passes physical-device memory and
  responsiveness tests.
- Verify screen rendering and touch behavior on the CYD, then add screenshots.

Report bugs at <https://github.com/ijtan/project-cyder/issues>.

## License

Project Cydex is licensed under GPL-3.0-only. See [LICENSE](LICENSE).
