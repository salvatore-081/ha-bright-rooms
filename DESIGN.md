# Bright Rooms – design

Home Assistant integration (domain `bright_rooms`) that switches the lights of a room with its presence
sensors and the **ambient light without the room's own lights**: it learns how many lux each light adds to
the illuminance sensor, so it can turn the lights off when daylight is enough and never mistakes its own
lamp for daylight. Built like Tidy Rooms (`../ha-tidy-rooms`, same author): config entry with rooms as
subentries, an engine, a sidebar panel (Lit, compiled by the CI), a dashboard card, WebSocket API, tests,
HACS zip release. Code, comments and README in English; UI strings in English and Italian.

This file is the contract between the backend (`custom_components/bright_rooms`, `tests/`) and the frontend
(`frontend/`). Change it when the contract changes.

## Concepts

- **Room**: a subentry (type `room`): a group of lights switched by its own presence sensors, with a unique
  name, in a Home Assistant area. Several rooms may share an area (a kitchen with the cooktop lights on the
  kitchen sensor and the table lamp on the table sensor). Subentries have no unique id; the subentry title,
  the device name ("Bright Rooms ‹name›") and the snapshot `name` are the room's name. Rooms saved without a
  name (0.1.0) are named after their area.
- **Occupied**: at least one of the room's presence sensors is `on`. Unavailable/unknown sensors are
  ignored; if all are unavailable the room's occupancy is `None` and nothing is started or stopped by it.
- **Zone**: presence sensors of nearby areas. While a zone sensor is `on`, turning off waits longer
  (people move between the kitchen and the table and come back).
- **Raw lux**: the state of the room's illuminance sensor (optional).
- **Contribution** of a light: lux it adds to the raw reading when on at full brightness. Learned, per room
  and light, stored with `homeassistant.helpers.storage.Store` (`bright_rooms.<entry_id>`), editable from the
  panel. `None` until the first valid measurement (or a value set by hand).
- **Ambient light** = max(0, raw − Σ over room lights that are on of contribution × fraction), fraction =
  brightness/255 for dimmable lights, 1 for on/off lights. Rounded to an integer.
  - After any room light changes (on/off, brightness, back from unavailable) the ambient value is **held**
    (previous value kept) for `settle_seconds` (global option, default 75): illuminance sensors report late
    (the SONOFF SNZB-06P24 every ~30 s) and some lamps ramp up.
  - It is also held while a room light is unavailable, or while a light that is on has contribution `None`.
  - No raw reading (no sensor, unavailable, not a number) → ambient `None`.
- **Dark** (hysteresis): `True` when ambient < `dark_below`, `False` when ambient > `bright_above`, otherwise
  unchanged. First value: `True` below `dark_below`, `False` above `bright_above`, in between `True` if below
  the midpoint. Ambient `None` → dark `None`, which counts as dark for turning on and never as bright.

## Room settings (subentry data)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | text | required | Name of the room, unique ignoring case (first field of the form) |
| `area` | area id | required | Where the room's device goes; may be shared by several rooms |
| `presence_sensors` | list of binary_sensor | required (≥1) | Union = occupied |
| `zone_sensors` | list of binary_sensor | `[]` | Nearby areas, extend the wait before turning off |
| `lights` | list of light | required (≥1) | Lights switched by Bright Rooms |
| `illuminance_sensor` | sensor (device_class illuminance) | none | Without it: always "dark", no brightness from light |
| `other_lights` | list of light | `[]` | Other lights the illuminance sensor sees: a measurement is discarded if one changes |
| `on_delay` | s, 0–600 | 0 | Continuous presence needed before turning on |
| `only_when_dark` | bool | true | Turn on only when dark (or no reading) |
| `dark_below` | lx | 40 | Dark under this ambient light |
| `bright_above` | lx | 80 | Bright over this (must be > `dark_below`) |
| `off_when_bright` | bool | true | Turn off when it becomes bright |
| `on_when_dark` | bool | true | Turn on when it becomes dark with people already in the room (only with `only_when_dark`) |
| `bright_minutes` | min, 0–120 | 10 | Bright for this long before turning off |
| `min_off_seconds` | s, 0–60 | 0 | Minimum time between a light's last change and turning it on (lamps that change tint when switched quickly) |
| `brightness_min` | %, 1–100 | 100 | Dimmable lights: brightness at or below `brightness_dark_lux` |
| `brightness_dark_lux` | lx | 10 | |
| `brightness_full_lux` | lx | 200 | Dimmable lights: 100 % at or above this ambient light, linear in between; no reading → 100 % |
| `empty_wait` | s, 0–3600 | 30 | Wait with the room and zone empty before dimming/turning off |
| `zone_wait` | s, 0–3600 | 150 | Maximum extra wait while a zone sensor is on |
| `dim_percent` | %, 1–100 | 30 | Dimmable lights are dimmed to this % of their brightness before turning off (100 = no dimming) |
| `dim_wait` | s, 0–600 | 10 | Time dimmed before turning off (the warning) |
| `transition` | s, 0–30 | 3 | Transition of the final turn-off of dimmable lights |

Validation errors (keys for translations): `name_taken` (another room has the same name, ignoring case), `no_presence`, `no_lights`, `bright_not_above_dark`,
`brightness_lux_order` (`brightness_full_lux` must be > `brightness_dark_lux`), `light_in_other_room` (a light
can belong to one room only).

Global options of the entry: `settle_seconds` (75), `learn_ambient_max` (60 lx: measure contributions only
with little daylight), `learn_min_previous` (90 s), `learn_weight` (0.2).

## Engine (one per room, `engine.py`)

Event-driven (`async_track_state_change_event` on all involved entities, `async_call_later` for timers).
Never acts on states found at startup: only on transitions seen while running, with one exception. After a
start (restart or reload), a room found empty (occupied `False`) with lights on gets the normal turn-off
sequence (step 2), once every presence sensor has been available for 30 s (so a sensor still starting up
does not switch lights). The check is dropped if occupancy changes (an arrival or departure edge), if a room
light is changed by someone else, or if the room is occupied at the end of the grace. Nothing is ever turned
on at startup. Commands use a `Context` created by Bright Rooms; a light change with any other context is
"by someone else".

Status (`status` sensor, enum): `disabled` (switch off), `off` (lights off), `on` (lights on, nobody left),
`waiting` (nobody left, waiting before dimming), `dimmed` (dimmed, about to turn off).

1. **Turn on** – on the rising edge of occupancy (after `on_delay` of continuous presence): if enabled, every
   available room light is off, at least one is available, and (`only_when_dark` is false or dark is not
   `False`): wait until `min_off_seconds` have passed since each light's `last_changed`, check again, then
   `light.turn_on` the available lights: on/off lights without data, dimmable lights with `brightness_pct`
   from the brightness curve (computed on ambient light). Lights turned off by hand while the room is
   occupied are not turned on again before the next rising edge.
2. **Turn off when empty** – on the falling edge of occupancy, if any room light is on (also when turned on by
   hand): sequence
   1. while a zone sensor is on, wait until the zone is empty, at most `zone_wait` s;
   2. wait `empty_wait` s;
   3. if dimmable lights are on and `dim_percent` < 100: remember their brightness, dim each to
      `dim_percent` % of it (transition 2 s), status `dimmed`, wait `dim_wait` s; on/off lights are not touched;
   4. turn off the lights that are on (dimmable with `transition`).

   Cancelled when the room is occupied again (dimmed lights go back to the remembered brightness; nothing
   else changes) or when a room light is changed by someone else (nothing is touched). Never switches a light
   off and on again (no flicker). Disabling the room cancels it without touching the lights.
3. **Turn off when bright** – when dark goes from `True` to `False` and stays `False` for `bright_minutes`,
   with `off_when_bright` and lights on: turn them off (dimmable with `transition`), also with people in the
   room. Only on that transition: a light turned on by hand when it is already bright stays on.
4. **Learn contributions** – on every on↔off change of a room light (any source), if the previous state lasted
   ≥ `learn_min_previous` s: read raw lux now ("before"), and again after `settle_seconds` ("after").
   **Groups**: room lights that switch in the same direction within 2 s of the first change, or with the same
   context (Bright Rooms switches all lights in one or two calls), are one measurement with a joint jump; each
   member must also satisfy the previous-state rule. A single light is a group of one. Valid only if: both
   readings are numbers; the ambient light without the group (before when turning on, after when turning off)
   is ≤ `learn_ambient_max`; no member changed again (state or brightness) during the measurement; no room
   light outside the group and no `other_lights` changed from 30 s before the first change to the end; the
   jump as measured is ≥ 5 lx. With fraction f_i (brightness/255 while on, 1 for on/off lights):
   - every contribution known: expected = Σ c_i·f_i, factor = jump/expected, valid if 1/3 ≤ factor ≤ 3; each
     c_i ← c_i·(1 − weight) + c_i·factor·weight (for one light: the jump normalized, between value/3 and
     value×3);
   - exactly one unknown: c_u = (jump − Σ known c_i·f_i)/f_u, valid if ≥ 5 lx; the known ones are unchanged;
   - more than one unknown: discarded.

   Values are rounded. Store `samples` (count, only for the values updated) and `updated` (ISO time). A new
   change of a member cancels the measurement in progress; a light switching in the other direction, or
   outside the 2 s without the same context, spoils it.

5. **Turn on when it becomes dark** – when dark goes from `False` to `True` (not from `None`), with
   `on_when_dark` and `only_when_dark`, the room enabled and occupied, no turn-on already pending and every
   available room light off (at least one available): turn on as in step 1, without `on_delay` (the room is
   already occupied) but with the same `min_off_seconds` wait and recheck and the same brightness curve.
   Reason `became_dark`; a skip at the recheck is not recorded. Only on that transition: lights turned off by
   hand once it is already dark stay off. Without `only_when_dark` the option is ignored (the lights were
   turned on at arrival). Rooms saved without the key take the default (true).

6. **Goals and unreliable lights** (lights that drop their connection, commands that raise). Every turn-on
   (`presence_dark`, `presence_always`, `became_dark`, `light_back`) sets the room's goal `on`, every final
   turn-off (`empty`, `zone_timeout`, `bright`) the goal `off`.
   - **Reached** when every room light is available and in the goal state: the goal is cleared.
   - **Cleared** also when someone else changes a room light (their choice wins), when the room is disabled,
     or when its reason stops holding: `on` when the room is no longer occupied, or with `only_when_dark`
     when dark becomes `False`; `off` (empty) when the room is occupied again; `off` (`bright`) when dark
     becomes `True` again.
   - **Retries**: 10 s after each command the available lights not yet in the goal state get it again, up to
     3 attempts in all, while the goal holds. A command that raises records `failed` (with the reason of the
     attempted action and a `detail`, the error's message); a goal still not reached after the last attempt
     records `failed` with detail `no response` (if nothing was recorded yet) and logs one warning, and the
     goal is kept. When the goal is reached after a failure, the normal action is recorded with the original
     reason.
   - **Lights coming back** (unavailable/unknown → available): with a goal it does not match, the light gets
     the goal (turn-on after `min_off_seconds` from its last change, brightness from the curve), recorded as
     `turned_on`/`turned_off` with reason `light_back`. Without a goal, if the room is occupied and enabled,
     dark is not `False` (with `only_when_dark`), every available light is off, nothing is pending and no
     room light was turned off by someone else since the last arrival seen while running (at start: none
     seen, so this does not apply), the lights are turned on as at arrival, reason `light_back` (an arrival
     that happened while the light was unavailable).
   - **Arrival with every light unavailable** sets the `on` goal (when dark allows it), completed when a
     light comes back.
   - **Ours or someone else's**: while a goal is set, a light change to the goal state counts as Bright
     Rooms' own (a command that raised but took effect, a late report). A light that becomes available again
     is never an on/off transition for learning.

Every action records `last_action` = `{action, reason, at, detail}` with `action` in `turned_on`,
`turned_off`, `dimmed`, `restored`, `skipped_on`, `failed` and `reason` a key: `presence_dark`,
`presence_always`, `became_dark`, `light_back`, `bright`, `empty`, `zone_timeout`, `presence_back`,
`changed_by_someone_else`, `not_dark`, `lights_already_on`, `disabled`. `detail` is null except for `failed`.
`skipped_on` is recorded when presence arrives but the lights are not turned on (`not_dark`).
`deadline`: ISO time of the next timed step (end of the wait, of the dimming, of the bright timer), or null.

### Details fixed by the implementation

- **Edges of occupancy**: only `False → True` is an arrival and `True → False` a departure; changes to or
  from `None` (all presence sensors unavailable) start and stop nothing, except that a pending turn-on is
  dropped.
- **Pending turn-on** (`on_delay`, `min_off_seconds`): dropped when presence ends; when a room light is
  changed by someone else meanwhile, it is dropped and recorded as `skipped_on` / `changed_by_someone_else`.
  A turn-off sequence cancelled by someone else records no action (the last one stays).
  `skipped_on` reasons: `not_dark`, `lights_already_on`, `disabled`, `changed_by_someone_else`.
- **Zone**: a zone sensor turning on during the empty wait goes back to the zone wait, within the same
  `zone_wait` limit counted from the first zone wait; after the limit the zone is ignored.
- **Dimming** is skipped when `dim_wait` is 0 (the lights go straight off).
- **Ours or someone else's**: a change with one of Bright Rooms' contexts is ours; so is a change without it
  that matches the state Bright Rooms asked for (on/off) within the command's transition + 5 s (lights that
  report late, after Home Assistant has dropped the context). Becoming unavailable or available again is
  nobody's change.
- **Learning**: "the previous state lasted" is measured from the old state's `last_updated` (a brightness
  change counts as a change), and a member must not have changed in the 30 s before its own change. The 5 lx
  minimum applies to the jump as measured, before normalizing by the brightness fraction (a 2 lx jump at
  10 % is noise, not 20 lx). The ambient light for the validity check uses the contributions of the room
  lights outside the group; if one of them is on and unknown, the measurement is discarded. A known value of
  0 makes the expected jump 0: the measurement is discarded (set it to null to learn it again).
- **Store** `bright_rooms.<entry_id>`: `{rooms: {<subentry_id>: {enabled, contributions: {<light>:
  {value, samples, updated}}}}}`; the Automatic switch is saved there too. Rooms and lights no longer
  configured are dropped at load.
- **Status sensor attributes**: `last_action` is the action key; `reason`, `at` and `detail` come from the
  same record.

## Entities (one device per room, in the room's area, `via_device` the entry's device)

- `switch` **Automatic** (`automatic`): room enabled; restored after a restart (default on).
- `sensor` **Ambient light** (`ambient_light`): lx, device_class illuminance, state_class measurement;
  attributes `raw` and `held` (bool).
- `binary_sensor` **Dark** (`dark`): `on` when dark; unknown when `None`.
- `sensor` **Status** (`status`): enum (above); attributes `last_action`, `reason`, `at`, `deadline`.
- `sensor` **Contribution** per light (`contribution_<light object id>`, diagnostic, lx, state_class
  measurement, `None` until learned); attributes `samples`, `updated`.

## WebSocket API

Writes and `schema` are admin only. `rooms` and `subscribe` are open to every user, because the dashboard
card uses them. Errors the frontend tells apart: `unauthorized`, `unknown_command` (not installed),
`not_found` (not set up), `not_loaded`; field errors of a save are keys of `error.<key>` (`invalid`, the
validation errors above, or `base` for the whole form).

Types are in `frontend/src/types.ts`; snake_case keys as below.

- `bright_rooms/rooms` → `Snapshot`; `bright_rooms/subscribe` → `Snapshot` at subscription and on every
  change (debounced ~0.5 s).

  ```
  Snapshot = { entry_id: str, settings: {settle_seconds, learn_ambient_max, learn_min_previous, learn_weight},
               rooms: RoomSnapshot[] }   // rooms in name order
  RoomSnapshot = {
    id: subentry_id, name: str, area_id: str, enabled: bool, config: {room settings},
    status: "disabled"|"off"|"on"|"waiting"|"dimmed",
    occupied: bool|null, zone_occupied: bool, raw_lux: number|null, ambient: number|null,
    held: bool, dark: bool|null, deadline: iso|null,
    last_action: {action, reason, at, detail: str|null}|null,
    goal: "on"|"off"|null,         // what Bright Rooms is still trying to reach
    lights: [{entity_id, name, state, brightness: 0-255|null, dimmable: bool,
              contribution: number|null, samples: int, updated: iso|null}],
    sensor_entities: [entity_id]   // settings of the presence sensors: entities of the presence sensors'
                                   // devices with entity_category "config" and domain number, select,
                                   // switch or button (sensitivity, absence delay, ranges, calibration)
  }
  ```
- `bright_rooms/schema` `{room_id?}` → one result `{schema: FormField[], values: {}, settings_schema:
  FormField[], settings: {}}`: the room form (serialized with `probatio.to_field_list` like Tidy Rooms) and
  the global settings form. Without sections the panel groups the room fields by name (name and area; presence;
  lights; daylight; brightness; turning off; unknown fields last). Sections (`expandable`) are allowed: the
  panel then draws the schema as it is, titles from the `section.<name>` strings (`area`, `presence`,
  `lights`, `daylight`, `brightness`, `off`), and nests the flat field errors under the section name.
- `bright_rooms/room/save` `{room_id?: str, data: {}}` → `{room_id}` or `{errors: {field: key}}`.
  Room settings left out of `data` take their default; optional fields sent as null or "" are removed.
- `bright_rooms/room/delete` `{room_id}`; `bright_rooms/room/set_enabled` `{room_id, enabled}`.
- `bright_rooms/contribution/set` `{room_id, entity_id, value: number|null}` (null = forget, learn again).
- `bright_rooms/settings/save` `{data}` → `{}` or `{errors}`. Settings left out keep their current value.
- `rooms` and `subscribe` answer `not_found` when Bright Rooms is not set up and `not_loaded` when its entry is
  not loaded (no silent subscription). A subscription survives a reload of the entry (a room or the settings
  saved): the new engine sends a snapshot when it starts.

## Panel (sidebar "Bright Rooms", `mdi:lightbulb-auto`, admin only, URL `/bright-rooms`)

- **Overview**: a tile per room: status with icon and colour, occupied/zone, ambient light with the dark and
  bright thresholds drawn on a small bar (and raw lux, "held" when held), dark yes/no, lights with state and
  brightness, countdown to `deadline`, last action with its reason in words and time, the Automatic switch.
- **Rooms**: list, add, edit (ha-form from `bright_rooms/schema`), delete. A room page shows the live status,
  the form, the **contributions** (value, samples, last update; edit the value, "measure again" = set null)
  and the **presence sensor settings** (`sensor_entities`, rendered with the frontend's own entities card,
  e.g. `loadCardHelpers().createCardElement({type: "entities", entities})`, so number/select/button work
  natively without copying them into Bright Rooms).
- **Settings**: the global options.

## Card (`custom:bright-rooms-card`)

Compact list of rooms (all, or `rooms: [ids]`): name, status icon, ambient light, lights on, countdown; tap
opens the panel room page. Visual editor (title, rooms).

## Packaging

As Tidy Rooms: `hacs.json` with `zip_release` and `filename: bright_rooms.zip`, minimum Home Assistant
`2026.10.0`; workflows Tests (pytest with `pytest-homeassistant-custom-component`, frontend lint, typecheck,
vitest, build), Validate (HACS action, hassfest), Release (checks the tag against `manifest.json` and
`frontend/package.json`, builds, uploads the zip). Version 0.1.3. `manifest.json`: `single_config_entry`
true, `integration_type` "service", `iot_class` "calculated", `dependencies` ["light"],
`after_dependencies` ["frontend", "http", "websocket_api"]. Brand icon in `custom_components/bright_rooms/brand`.
