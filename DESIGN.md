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

Terminology (0.2.0): what earlier versions called a "room" is a **light zone**; a **room** is a Home
Assistant area. Stored keys are unchanged: the subentry type stays `room`, the WebSocket keeps `room_id` and
the `rooms` list (each item a zone), and the code keeps `RoomEngine`. In the rest of this file "room" in
keys and in the engine's text means a light zone, unless it says area.

- **Light zone** ("zona luce"): a subentry (type `room`): a group of lights switched by its own presence
  sensors, with its illuminance sensor, settings and bands, a unique name, in a Home Assistant area. Several
  zones may share an area (a kitchen with the cooktop lights on the kitchen sensor and the table lamp on the
  table sensor). Subentries have no unique id; the subentry title, the device name ("Bright Rooms ‹name›")
  and the snapshot `name` are the zone's name. Zones saved without a name (0.1.0) are named after their
  area.
- **Room**: a Home Assistant area; its light zones are grouped by their `area`. Nothing is configured on a
  room. Each room with zones has a device "Bright Rooms ‹area name›" (in that area, `via_device` the entry's
  device) with an **Automatic** switch for all its zones; the zones' devices hang from it.
- **Nearby presence (neighbours)**: presence sensors of other places that make turning off wait longer
  (people move between the cooktop and the table and come back). The effective neighbouring sensors of a
  zone are, in this order and without repeats, minus the zone's own presence sensors:
  1. **automatic** (`auto_neighbors`, default true): the presence sensors of the other zones of the same
     area;
  2. **manual** (`neighbor_zones`, default `[]`): the presence sensors of the chosen zones, of any area;
  3. `zone_sensors`: an extra list of binary sensors ("nearby presence" / "presenze vicine").

  A band's `zone_sensors` override, when not null, replaces the whole effective set (`[]` = none).
- **Occupied**: at least one of the room's presence sensors is `on`. Unavailable/unknown sensors are
  ignored; if all are unavailable the room's occupancy is `None` and nothing is started or stopped by it.
- **Zone sensors** (in keys and texts below: `zone_sensors`, `zone_wait`, `zone_occupied`): the effective
  neighbouring sensors above. While one is `on`, turning off waits longer.
- **Raw lux**: the state of the room's illuminance sensor (optional).
- **Contribution** of a light: lux it adds to the raw reading when on at full brightness. Learned, per room
  and light, stored with `homeassistant.helpers.storage.Store` (`bright_rooms.<entry_id>`), editable from the
  panel. `None` until the first valid measurement (or a value set by hand).
- **Ambient light** = max(0, raw − Σ over room lights that are on of contribution × fraction), fraction =
  brightness/255 for dimmable lights, 1 for on/off lights. Rounded to an integer.
  - After a room light changes while running (on/off or brightness) the ambient value is **held**
    (previous value kept) for `settle_seconds` (global option, default 75): illuminance sensors report late
    (the SONOFF SNZB-06P24 every ~30 s) and some lamps ramp up.
  - It is also held while a room light is unavailable, or while a light that is on has contribution `None`.
  - A light that becomes available again (an integration starting up, a dropped connection) does not start
    a hold: it only tells its state. At startup or reload the ambient light is computed at once from the
    raw reading when every room light is off, or when every light that is on has a known contribution
    (states found at startup never start a hold).
  - No raw reading (no sensor, unavailable, not a number) → ambient `None`.
- **Dark** (hysteresis): `True` when ambient < `dark_below`, `False` when ambient > `bright_above`, otherwise
  unchanged. First value: `True` below `dark_below`, `False` above `bright_above`, in between `True` if below
  the midpoint. Ambient `None` → dark `None`, never bright; two cases:
  - **no reading** (no illuminance sensor, or it is unavailable or not a number): counts as dark for turning
    on;
  - **undecided** (a reading exists but the ambient light is not known yet: held after a change with no
    earlier value, a light on with an unknown contribution, a light unavailable): a turn-on (arrival,
    `light_back`, the recheck after `min_off_seconds`) with `only_when_dark` waits for the decision, at most
    `settle_seconds` + 15 s from when it started waiting, then applies the normal rules with the decided
    value; still undecided after that, it counts as dark (like no reading). Light-conditioned bands treat
    both cases as not met.

## Light zone settings (subentry data)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | text | required | Name of the room, unique ignoring case (first field of the form) |
| `area` | area id | required | Where the room's device goes; may be shared by several rooms |
| `presence_sensors` | list of binary_sensor | required (≥1) | Union = occupied |
| `auto_neighbors` | bool | true | The other zones of the same area count as nearby presence |
| `neighbor_zones` | list of zone ids | `[]` | Zones (any area) whose presence sensors count as nearby presence |
| `zone_sensors` | list of binary_sensor | `[]` | Extra nearby presence ("presenze vicine"), extends the wait before turning off |
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
| `schedule` | list of bands | `[]` | Bands by time and/or light (below); edited in the panel, not in the ha-form schema |

Validation errors (keys for translations): `name_taken` (another zone has the same name, ignoring case),
`neighbor_invalid` (`neighbor_zones` must be existing zone ids other than the zone itself), `no_presence`, `no_lights`, `bright_not_above_dark`,
`brightness_lux_order` (`brightness_full_lux` must be > `brightness_dark_lux`), `light_in_other_room` (a light
can belong to one room only), `schedule_invalid` (below).

### Bands (`schedule`)

- Band = `{id, name|null, start: "HH:MM"|null, end: "HH:MM"|null, days: [...], light: "bright"|"dark"|null,
  light_room: room_id|null, on_delay: int|null, empty_wait: int|null, zone_wait: int|null,
  zone_sensors: [entity_id]|null}`.
  - Conditions (all set ones must hold): time window if `start` and `end` are both set (both or neither;
    [start, end), end ≤ start crosses midnight (end = start: the whole day), `days` refers to the day the
    window started; with no time window, `days` restricts by the current weekday; empty = every day); light
    if `light` is set: the band is active when the dark state of `light_room` (default: this room; any
    configured room of the entry) is False for "bright" / True for "dark". Dark None (unknown) → a light
    condition is not met.
  - At least one condition (time window or light) and at least one override.
  - Overrides: `on_delay` (0–600), `empty_wait`, `zone_wait` (0–3600), `zone_sensors` (list of
    binary_sensor; `[]` = no zone in this band; null = room's own list). Not null, it replaces the zone's
    whole effective set of neighbouring sensors (automatic, manual and `zone_sensors`).
  - First active band in list order wins, as now. Existing bands (time only, empty_wait/zone_wait) stay
    valid unchanged (missing keys = null).
- `id`: uuid hex, generated by the backend if missing (an existing `id` is kept; an empty or repeated one is
  replaced). Room config key `schedule`, list of at most 8 bands; rooms without the key: `[]`.
- Effective values: snapshot `effective: {on_delay, empty_wait, zone_wait, zone_sensors}`. `on_delay` is
  read when occupancy rises (the delay timer); `zone_sensors` and the waits when the corresponding wait
  starts; the zone wait watches the effective zone sensors (`zone_occupied` in the snapshot is computed on
  the zone sensors of the wait in progress, otherwise on the effective ones). The engine subscribes to all
  binary sensors that appear in any band's `zone_sensors` and follows the dark state of the rooms referenced
  by `light_room`: a change of that room's dark state re-evaluates the referencing rooms and updates their
  entities and the subscriptions at once.
- Saved through `bright_rooms/room/save` as part of `data.schedule`. Without the key the room's bands stay
  as they are; `[]` removes them. The backend normalizes each band and always writes every key:
  `start`/`end` as "HH:MM" ("HH:MM:SS" accepted) or null, `days` in week order without repeats, `name`
  trimmed (empty → null), `light` and `light_room` ("" → null; `light_room` is null when `light` is null),
  number overrides as int, `zone_sensors` without repeats.
- Validation errors as before: `{"schedule": "schedule_invalid"}` for anything wrong (not a list, more than
  8 bands), plus `"schedule.<index>": "schedule_invalid"` for each invalid band (bad or half time window,
  unknown day, unknown `light`, `light_room` not a room of the entry (null = this room, also on a new room),
  no condition, no override, a number out of range or not whole, `zone_sensors` not a list of
  `binary_sensor.*` ids, name not a string). With any error nothing is saved.
- Not part of the ha-form `schema` list (the panel has its own editor), but present in the `schema`
  command's `values` (`[]` for a new room) and in the snapshot's `config`. The subentry reconfigure flow in
  Home Assistant's UI preserves it; a room added there starts with `[]`.
- Snapshot additions per room: `active_band: id|null`, `effective: {on_delay: int, empty_wait: int,
  zone_wait: int, zone_sensors: [entity_id]}`. A band activating or deactivating (time, weekday at
  midnight, or a light change) updates `active_band` immediately (entities and subscriptions).
- Status sensor attribute `active_band`: the band's name, else a description: the time range and/or
  "bright"/"dark" (e.g. "22:00–06:00", "dark", "18:00–23:00 · dark").

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
   else changes) or when a room light is changed by someone else (nothing is touched; if the room is still
   empty with a light on, the sequence starts again from the beginning, see below). Never switches a light
   off and on again (no flicker). Disabling the room cancels it without touching the lights.

   **Empty room with a light on.** Not only at the falling edge: whenever the room is known to be empty
   (occupied `False`), enabled, and a room light is seen `on` (back from unavailable/unknown already on,
   turned on by someone else or by a wall switch, still on after a departure seen while the lights were
   unavailable, or after a turn-off that gave up), the same sequence starts (zone wait, empty wait from the
   active band, dimming, off), reason `empty` (or `zone_timeout`). It is checked on every state change the
   room follows, and does not start while a sequence or a turn-on is pending, while a turn-off is still being
   retried (an `off` goal whose attempts are not used up) or in flight (re-entry), or during the startup
   grace. A light turned on by someone else while the room is empty is therefore turned off after the waits;
   an occupancy rise never loses this: after the next departure the rule applies again.
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

7. **Someone back right after an empty turn-off** (re-entry). When the empty sequence turns lights off
   (reason `empty` or `zone_timeout`), Bright Rooms remembers which lights it switched off and their
   brightness before the dimming. If the room becomes occupied again while that command is in flight (the
   lights have not all reported off; at most 10 + 3×10 s), the arrival is decided when they report off; if
   it becomes occupied within `REENTRY_SECONDS` (10 s) after they all reported off, it is decided at once.
   Either way those lights are turned back on (after `min_off_seconds` from their last change; dimmable
   lights to their brightness before the dimming, on/off lights plainly), whatever the daylight (they were
   on), recorded as `turned_on` / `presence_back`, with the usual goal and retries; the normal arrival
   (step 1) is skipped. Not after the `bright` turn-off, not if someone else changed a room light in between,
   not if the room is disabled, and not if the room empties again before the lights report off. While in
   flight, those lights reporting off count as Bright Rooms' own change.

Every action records `last_action` = `{action, reason, at, detail}` with `action` in `turned_on`,
`turned_off`, `dimmed`, `restored`, `skipped_on`, `failed` and `reason` a key: `presence_dark`,
`presence_always`, `became_dark`, `light_back`, `bright`, `empty`, `zone_timeout`, `presence_back`,
`changed_by_someone_else`, `not_dark`, `lights_already_on`, `disabled`. `detail` is null except for `failed`.
`skipped_on` is recorded when presence arrives but the lights are not turned on (`not_dark`).
`deadline`: ISO time of the next timed step (end of the wait, of the dimming, of the bright timer), or null.

### Details fixed by the implementation

- **Edges of occupancy**: only `False → True` is an arrival and `True → False` a departure; changes to or
  from `None` (all presence sensors unavailable) are not edges and drop a pending turn-on. A room that
  becomes known empty (`None → False`) with a light on gets the empty sequence (step 2, empty room with a
  light on).
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
  same record; `active_band` (see Bands).

## Entities

One device per light zone ("Bright Rooms ‹zone name›", in the zone's area, `via_device` its room's device);
one device per room (area) with zones ("Bright Rooms ‹area name›", in the area, `via_device` the entry's
device). Zone entities keep their unique ids (`<subentry_id>_<key>`), so their entity ids do not change.

- Room device: `switch` **Automatic** (`area_automatic`, unique id `<entry_id>_area_<area_id>_automatic`):
  on when any zone of the area is enabled; turning it on or off sets every zone of the area. A room left
  without zones loses its device.
- `switch` **Automatic** (`automatic`): zone enabled; restored after a restart (default on).
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
               rooms: RoomSnapshot[],    // light zones, in name order
               areas: [{area_id, name, zone_ids: [subentry_id], enabled: bool}] }
                                         // rooms (areas) by name; zones within by name;
                                         // enabled: any zone of the area enabled
  RoomSnapshot = {
    id: subentry_id, name: str, area_id: str, enabled: bool, config: {room settings},
    status: "disabled"|"off"|"on"|"waiting"|"dimmed",
    occupied: bool|null, zone_occupied: bool, raw_lux: number|null, ambient: number|null,
    held: bool, dark: bool|null, deadline: iso|null,
    last_action: {action, reason, at, detail: str|null}|null,
    goal: "on"|"off"|null,         // what Bright Rooms is still trying to reach
    active_band: str|null,         // id of the active band
    effective: {on_delay: int, empty_wait: int, zone_wait: int, zone_sensors: [entity_id]},
                                   // values that apply now (band or room)
    lights: [{entity_id, name, state, brightness: 0-255|null, dimmable: bool,
              contribution: number|null, samples: int, updated: iso|null}],
    sensor_entities: [entity_id],  // settings of the presence sensors: entities of the presence sensors'
                                   // devices with entity_category "config" and domain number, select,
                                   // switch or button (sensitivity, absence delay, ranges, calibration)
    neighbors: {auto: [entity_id], manual_zones: [subentry_id], sensors: [entity_id],
                effective: [entity_id]}   // nearby presence by origin (bands not applied)
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
  `data.schedule` as in Bands (left out: unchanged); its errors come in the same `errors` object.
- `bright_rooms/room/delete` `{room_id}`; `bright_rooms/room/set_enabled` `{room_id, enabled}`.
  Deleting a zone removes it from the other zones' `neighbor_zones`, and bands whose `light_room` was that
  zone fall back to null (the zone's own light). This cleanup happens when the entry reloads, so it also
  applies to zones deleted from Home Assistant's integration page.
- `bright_rooms/area/set_enabled` `{area_id, enabled}` (admin): every zone of the area; `not_found` if the
  area has no zones.
- `schema`: the room form has `auto_neighbors` (boolean) and `neighbor_zones` (select, multiple, options
  `{value: zone id, label: zone name}` of the other zones, by name) after `presence_sensors`, then
  `zone_sensors`.
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
`frontend/package.json`, builds, uploads the zip). Version 0.2.0. `manifest.json`: `single_config_entry`
true, `integration_type` "service", `iot_class` "calculated", `dependencies` ["light"],
`after_dependencies` ["frontend", "http", "websocket_api"]. Brand icon in `custom_components/bright_rooms/brand`.
