// Shapes of the data sent by the integration (websocket_api.py, engine snapshot).
// This file is the frontend side of the contract in DESIGN.md § WebSocket API.

import type { Connection, HassEntity } from "home-assistant-js-websocket";

export type RoomStatus = "disabled" | "off" | "on" | "waiting" | "dimmed";

export type ActionKind =
  "turned_on" | "turned_off" | "dimmed" | "restored" | "skipped_on" | "failed";

export type ActionReason =
  | "presence_dark"
  | "presence_always"
  | "became_dark"
  | "light_back"
  | "bright"
  | "empty"
  | "zone_timeout"
  | "presence_back"
  | "changed_by_someone_else"
  | "not_dark"
  | "lights_already_on"
  | "disabled";

export interface LastAction {
  action: ActionKind;
  reason: ActionReason;
  /** ISO time. */
  at: string;
  /** Why a command failed (action "failed"), e.g. the integration's error. */
  detail?: string | null;
}

export type BandLight = "bright" | "dark";

/**
 * A band of a room: overrides of the room's settings while its conditions
 * hold (a time window, the days, the measured light). The first active one wins.
 */
export interface Band {
  /** Missing on a band not saved yet (the integration generates it). */
  id?: string;
  name: string | null;
  /** "HH:MM", both or neither; a window whose end is at or before its start crosses midnight. */
  start: string | null;
  end: string | null;
  /** "mon"…"sun"; empty: every day. */
  days: string[];
  /** Holds when the dark state of `light_room` is False ("bright") or True ("dark"). */
  light: BandLight | null;
  /** The room whose light counts; null: this room. */
  light_room: string | null;
  /** Overrides; null: the room's own value. At least one is set. */
  on_delay: number | null;
  empty_wait: number | null;
  zone_wait: number | null;
  /** Nearby presence sensors in this band; [] no zone; null the room's own. */
  zone_sensors: string[] | null;
}

/** The settings of a room (subentry data), as in DESIGN.md § Room settings. */
export interface RoomConfig {
  /** The room's name; several rooms may share an area. */
  name: string;
  area: string;
  presence_sensors: string[];
  zone_sensors?: string[];
  lights: string[];
  illuminance_sensor?: string | null;
  other_lights?: string[];
  on_delay?: number;
  only_when_dark?: boolean;
  dark_below: number;
  bright_above: number;
  off_when_bright?: boolean;
  on_when_dark?: boolean;
  bright_minutes?: number;
  min_off_seconds?: number;
  brightness_min?: number;
  brightness_dark_lux?: number;
  brightness_full_lux?: number;
  empty_wait?: number;
  zone_wait?: number;
  dim_percent?: number;
  dim_wait?: number;
  transition?: number;
  /** Presence sensors of the other zones in the same area count as nearby presence. */
  auto_neighbors?: boolean;
  /** Zones (of any area) whose presence sensors count as nearby presence. */
  neighbor_zones?: string[];
  /** The lights of the other zones in the same area count as other lights. */
  auto_other_lights?: boolean;
  /** Time bands, at most 8; the first active one wins. */
  schedule?: Band[];
  [key: string]: unknown;
}

export interface LightSnapshot {
  entity_id: string;
  name: string;
  /** The light's state: "on", "off", "unavailable", "unknown". */
  state: string;
  /** 0–255, null when off or not dimmable. */
  brightness: number | null;
  dimmable: boolean;
  /** Lux added at full brightness; null until learned. */
  contribution: number | null;
  samples: number;
  updated: string | null;
}

export interface RoomSnapshot {
  /** The subentry id. */
  id: string;
  name: string;
  area_id: string;
  enabled: boolean;
  config: RoomConfig;
  status: RoomStatus;
  /** null: every presence sensor is unavailable. */
  occupied: boolean | null;
  zone_occupied: boolean;
  raw_lux: number | null;
  ambient: number | null;
  held: boolean;
  dark: boolean | null;
  /** ISO time of the next timed step. */
  deadline: string | null;
  last_action: LastAction | null;
  /** What Bright Rooms is still trying to reach (retries, lights coming back). */
  goal?: "on" | "off" | null;
  /** Where the nearby presence comes from, and the sensors in force. */
  neighbors?: Neighbors;
  /** Other lights the sensor sees (a change discards a measurement). */
  other_lights?: OtherLights;
  /** The id of the time band in force, if any. */
  active_band?: string | null;
  /** The values in force (the active band's, or the room's). */
  effective?: {
    on_delay: number;
    empty_wait: number;
    zone_wait: number;
    zone_sensors: string[];
  };
  lights: LightSnapshot[];
  /** Settings of the presence sensors' devices (number, select, switch, button). */
  sensor_entities: string[];
}

/** Nearby presence of a zone (entity ids, zone ids). */
export interface Neighbors {
  /** Presence sensors of the other zones of the same area (auto_neighbors). */
  auto: string[];
  /** Zones chosen by hand (neighbor_zones). */
  manual_zones: string[];
  /** Extra sensors (zone_sensors). */
  sensors: string[];
  /** The sensors in force now (an active band may replace them). */
  effective: string[];
}

export interface OtherLights {
  /** Lights of the other zones of the same area (auto_other_lights). */
  auto: string[];
  /** Lights chosen by hand (other_lights). */
  manual: string[];
  /** Both, without the zone's own lights. */
  effective: string[];
}

/** A room: a Home Assistant area and its light zones. */
export interface AreaSnapshot {
  area_id: string;
  name: string;
  /** In name order. */
  zone_ids: string[];
  /** The room's Automatic switch, as the integration reports it. */
  enabled: boolean;
}

export interface GlobalSettings {
  settle_seconds: number;
  learn_ambient_max: number;
  learn_min_previous: number;
  learn_weight: number;
}

export interface Snapshot {
  entry_id: string;
  settings: GlobalSettings;
  /** The light zones (named "rooms" in the contract), in name order. */
  rooms: RoomSnapshot[];
  /** The rooms (areas) grouping the zones, in name order. */
  areas?: AreaSnapshot[];
}

/** A field of ha-form, as serialized by the integration (probatio.to_field_list). */
export interface FormField {
  name: string;
  type?: string;
  required?: boolean;
  optional?: boolean;
  selector?: Record<string, unknown>;
  /** Fields of a section (type "expandable"). */
  schema?: FormField[];
  [key: string]: unknown;
}

/** Answer of bright_rooms/schema: the room form and the global settings form. */
export interface SchemaResponse {
  schema: FormField[];
  values: Record<string, unknown>;
  settings_schema: FormField[];
  settings: Record<string, unknown>;
}

export interface SaveResult {
  errors?: Record<string, string>;
  room_id?: string;
}

/** The parts of the frontend's `hass` object that Bright Rooms uses. */
export interface HomeAssistant {
  connection: Connection;
  language: string;
  locale?: { language: string; time_format?: string };
  config: { time_zone: string };
  states: Record<string, HassEntity>;
  areas?: Record<string, { area_id: string; name: string; icon?: string | null }>;
  user?: { is_admin: boolean };
  callWS<T>(msg: Record<string, unknown>): Promise<T>;
}
