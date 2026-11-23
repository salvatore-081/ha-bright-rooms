// Shapes of the data sent by the integration (websocket_api.py, engine snapshot).
// This file is the frontend side of the contract in DESIGN.md § WebSocket API.

import type { Connection, HassEntity } from "home-assistant-js-websocket";

export type RoomStatus = "disabled" | "off" | "on" | "waiting" | "dimmed";

export type ActionKind = "turned_on" | "turned_off" | "dimmed" | "restored" | "skipped_on";

export type ActionReason =
  | "presence_dark"
  | "presence_always"
  | "became_dark"
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
  lights: LightSnapshot[];
  /** Settings of the presence sensors' devices (number, select, switch, button). */
  sensor_entities: string[];
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
  /** In area name order. */
  rooms: RoomSnapshot[];
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
