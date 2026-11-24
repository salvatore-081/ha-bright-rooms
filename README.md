# Bright Rooms

A Home Assistant integration that switches the lights of your rooms with their **presence sensors** and the **daylight**, measured without the lights' own contribution.

Most presence automations either ignore daylight or are fooled by their own lamp: the lamp raises the illuminance sensor, the automation thinks it is bright and turns the lamp off. Bright Rooms learns how many lux each light adds to the illuminance sensor, so it knows the **ambient light** with the lamps subtracted. It turns the lights on when someone comes in and it is dark, gives a warning before turning them off when nobody is left, and turns them off when the day becomes bright enough.

> **Status: early development.** The rules and the integration are covered by automated tests, but they have not yet switched lights in a real home. Feedback and issues are welcome.

## Light zones and rooms

- A **light zone** is a group of lights switched by its own presence sensors, with its illuminance sensor, settings and bands: for example the cooktop lights with the kitchen sensor, and the table lamp with the table sensor.
- A **room** is a Home Assistant area: its light zones are the zones in that area. Nothing is configured on a room; it has a device with an **Automatic** switch for all its zones.
- **Nearby presence**: while someone is detected nearby, turning off waits longer (people move between the cooktop and the table and come back). By default the other zones of the same room count as nearby presence; a zone can also list neighbouring zones of other rooms, and extra presence sensors.

In the rest of this page, "zone" means a light zone.

## How it works

- **Turning on**: when someone comes in (after an optional delay of continuous presence) and the zone is dark, Bright Rooms turns on the zone's lights if all of them are off. Dimmable lights get a brightness that follows the ambient light: lower in the dark (for example at night), full when there is some daylight. Lamps that change tint when switched quickly can be given a minimum time between changes.
- **Turning off when the zone empties**: Bright Rooms waits a little (longer while someone is detected in nearby, such as at the table next to the cooktop), then dims the dimmable lights as a warning, then turns everything off. If someone comes back while the lights are dimmed, they go back to their brightness: nothing is ever switched off and on again. If someone changes a light in the meantime, Bright Rooms leaves it as it is and, if the zone is still empty, starts waiting again.
- **A light on in an empty zone is turned off**: a light switched on with nobody detected (from a wall switch, by hand, by another automation, or a light that comes back from a connection drop already on) is turned off after the same waits, dimming included. To keep a light on in an empty zone, turn off the zone's (or the room's) *Automatic* switch.
- **Turning on when it becomes dark**: if someone sat down while it was bright and is still there at dusk, the lights turn on when it becomes dark, as if they had just come in (when all the zone's lights are off). Only on that transition: lights turned off by hand once it is dark stay off.
- **Turning off when it becomes bright**: when the ambient light goes from dark to bright and stays bright for some minutes, the lights go off, also with people in the zone. Only on that transition: a light turned on by hand when it is already bright stays on.
- **Lights that drop out**: if a command fails or a light does not follow, Bright Rooms tries again (three times, 10 s apart) and shows *Command failed* until it works. A light that comes back after being unavailable gets what the zone wanted (on with someone in the dark, off in an empty zone); if someone came in while the lights were unavailable, they turn on when the lights come back.
- **Back in a moment**: if someone comes back while the lights are going off, or within 10 seconds after, the lights the zone just turned off come back on as they were.
- **Bands**: each zone can have up to 8 bands that change some of its settings while they apply: the presence needed before turning on, the wait with the zone empty, the extra wait for nearby presence and which nearby sensors count. A band applies in a time window (for example *dinner, 20:00–23:00*, or *night, 23:00–07:00 on weekdays*), when this zone or another zone is bright or dark (for example *bright: wait 2 minutes of presence before turning on*), or both. The first band that matches wins; outside the bands the zone's own values apply. Bands are edited in the panel.
- **Your choices win**: a light turned off by hand while the zone is occupied is not turned on again until the next time someone comes in. Lights changed by other automations or by hand count as "someone else".
- **Other lights**: the illuminance sensor may also see lights that are not the zone's own: by default the lights of the other zones of the same room, plus any you add (lights of other rooms, or not managed by Bright Rooms). They only matter for learning: a measurement during which one of them changes is discarded.
- **Learning the lamps**: every time a light is switched on or off (by Bright Rooms or by anyone), with little daylight and nothing else changing, Bright Rooms compares the illuminance before and after and updates that light's **contribution** (lux at full brightness). Lights switched together count as one measurement: if their values are known they are scaled together; if only one is unknown, it gets the part the others do not explain. Measurements that look wrong are discarded. Values can also be set by hand.
- **Ambient light** = sensor reading − the contributions of the zone's lights that are on (scaled by their brightness). Illuminance sensors report late, so after a light changes the ambient light is held for a settling time; it is also held while a light is unavailable or not learned yet.
- **Dark and bright** use two thresholds (hysteresis), so a cloud does not switch the lights on and off. Without an illuminance sensor (or while it is unavailable) a zone counts as dark. When the sensor has a reading but the ambient light is not known yet (for example right after a lamp changed, before the sensor catches up), turning on waits for it, up to the settling time plus 15 seconds.
- **After a restart** Bright Rooms never turns lights on because of the states it finds. A zone found empty with its lights on gets the usual turn-off (wait, dimming, off) once the presence sensors have been available for 30 seconds, unless someone comes in or changes a light first.

## Requirements

- Home Assistant 2026.10 or later.
- Presence sensors (mmWave sensors work best: they see people sitting still).
- Optional but recommended: an illuminance sensor for each zone, placed where its lamps reach it.

## Panel

Bright Rooms adds a **Bright Rooms** panel to the sidebar (administrators only), in English and Italian:

- **Overview**: the rooms with their light zones; a tile per zone with its status, presence, ambient light with the dark and bright thresholds, the lights and their brightness, a countdown to the next step and the last action with its reason.
- **Light zones**: add, edit and delete light zones, grouped by room. A zone page shows its live status, its settings and bands, the **contributions** of its lights (edit a value, or measure it again) and the **settings of its presence sensors** (sensitivity, absence delay, ranges, calibration: the sensors' own controls, shown in place).
- **Settings**: settling time and how contributions are learned.

## Card

The **Bright Rooms card** (`custom:bright-rooms-card`) shows the light zones in compact form on any dashboard, with a visual editor. It needs no resource to be added by hand.

```yaml
type: custom:bright-rooms-card
title: Lights            # optional
rooms: [01J..., 01J...]  # optional: which light zones (all by default)
```

## Installation

### Marketplace (HACS)

1. Open the Marketplace, menu (⋮) → **Custom repositories**.
2. Add `https://github.com/salvatore-081/ha-bright-rooms` as an **Integration**.
3. Install **Bright Rooms** and restart Home Assistant.

Install a release: the panel and the card are built when a release is published and ship only in its zip (`bright_rooms.zip`). Installed from a commit, the integration works without them.

### Manual

Download `bright_rooms.zip` from the latest release, unpack it into `config/custom_components/bright_rooms` and restart Home Assistant.

## Configuration

1. **Settings → Devices & services → Add integration → Bright Rooms**.
2. In the **Bright Rooms** panel, add a light zone for each group of lights: a name, its room (area), presence sensors, lights, illuminance sensor, and optionally neighbouring zones of other rooms, extra nearby presence sensors and other lights the illuminance sensor sees (a lamp in the next room through an open door; the lights of the other zones of the same room count by default).
3. Let Bright Rooms learn the contributions over a few evenings. In a zone with several lights, switch each one on and off by itself once with the zone dark (two unknown lights switched together cannot be told apart); or type the values in the zone page.

Light zones and settings can also be managed from the integration page (**Add light zone**, **Configure**): both edit the same configuration.

Main zone settings:

| Setting | Default | Meaning |
|---|---|---|
| Presence before turning on | 0 s | Continuous presence needed before the lights turn on |
| Turn on only when dark | on | Otherwise the lights turn on whenever someone comes in |
| Dark below / bright above | 40 / 80 lx | Ambient light thresholds, with hysteresis in between |
| Other zones of the same room count as nearby presence | on | Their presence makes turning off wait longer |
| The lights of the other zones of this room | on | Count as other lights for learning |
| Turn on when it becomes dark | on | Only on the bright → dark transition, with someone already in the zone |
| Turn off when it becomes bright | on, after 10 min | Only on the dark → bright transition |
| Brightness in the dark | 100 % | Dimmable lights at or below 10 lx; 100 % from 200 lx, linear in between |
| Wait with the zone empty | 30 s | Before dimming or turning off |
| Longest extra wait for nearby presence | 150 s | While a nearby presence sensor detects someone |
| Dim to / dimmed for | 30 % / 10 s | The warning before turning off (100 % = no warning) |
| Transition when turning off | 3 s | Dimmable lights |

## Entities

For each room (area with light zones; device "Bright Rooms ‹area name›"):

| Entity | Description |
|---|---|
| `switch.…_automatic` | Bright Rooms on or off in every zone of the room; on when any zone is on |

For each light zone (device "Bright Rooms ‹zone name›", in its room's area, under the room's device):

| Entity | Description |
|---|---|
| `switch.…_automatic` | Bright Rooms on or off in the zone; turning it off stops what is in progress and leaves the lights as they are |
| `sensor.…_ambient_light` | Ambient light without the zone's own lights (lx); attributes: `raw` (sensor reading), `held` |
| `binary_sensor.…_dark` | On when dark; unknown without a reading |
| `sensor.…_status` | `disabled`, `off`, `on`, `waiting` (to turn off), `dimmed`; attributes: last action (including `failed`), reason, when, detail of a failure, active band, next step |
| `sensor.…_contribution_‹light›` | Learned contribution of each light (lx, diagnostic); attributes: number of measurements, last update |

## Development

Backend:

```bash
uv venv --python 3.14
uv pip install "pytest-homeassistant-custom-component==0.13.375"
uv run --no-project pytest -q
```

The ambient light, the darkness hysteresis, the brightness curve and the checks of a measurement live in `ambient.py` as pure functions, without Home Assistant, and are tested on their own. `engine.py` runs one engine per light zone on state changes and timers.

Frontend (Lit and TypeScript, built with Vite into `custom_components/bright_rooms/frontend/`):

```bash
cd frontend
npm ci --ignore-scripts
npm run lint && npm run typecheck && npm test
npm run build
```

The panel talks to the integration through its WebSocket API (`websocket_api.py`, commands `bright_rooms/*`; the contract is in `DESIGN.md`); the forms are the integration's own schemas, shown with Home Assistant's `ha-form`.

## Acknowledgements

The panel and its release follow the model of [RoomMind](https://github.com/snazzybean/roommind) (MIT, Copyright (c) 2026 SnazzyBean), as in [Tidy Rooms](https://github.com/salvatore-081/ha-tidy-rooms): a sidebar panel and a dashboard card registered by the integration itself, a Lit frontend bundled with Vite and shipped in the release zip built by CI. Two small pieces are adapted from its code: loading Home Assistant's `ha-form` in a panel opened directly (`frontend/src/load-ha-elements.ts`; RoomMind credits the technique to alarmo and scheduler-card) and the filter that keeps only the card's strings in its bundle (`frontend/vite.card.config.ts`).

## License

MIT
