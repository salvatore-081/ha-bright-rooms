// A fake snapshot and hass object for the tests.
import type { HassEntity } from "home-assistant-js-websocket";
import type { HomeAssistant, LightSnapshot, RoomSnapshot, Snapshot } from "../src/types";

export const NOW = new Date("2026-01-12T20:00:00+01:00");

export const light = (over: Partial<LightSnapshot> = {}): LightSnapshot => ({
  entity_id: "light.tavolo",
  name: "Tavolo",
  state: "on",
  brightness: 128,
  dimmable: true,
  contribution: 120,
  samples: 8,
  updated: "2026-01-12T18:30:00+01:00",
  ...over,
});

export const room = (over: Partial<RoomSnapshot> = {}): RoomSnapshot => ({
  id: "sub-kitchen",
  name: "Cucina",
  area_id: "cucina",
  enabled: true,
  config: {
    area: "cucina",
    presence_sensors: ["binary_sensor.cucina_presenza"],
    zone_sensors: ["binary_sensor.salone_presenza"],
    lights: ["light.tavolo", "light.cappa"],
    illuminance_sensor: "sensor.cucina_illuminamento",
    dark_below: 40,
    bright_above: 80,
    dim_percent: 30,
  },
  status: "waiting",
  occupied: false,
  zone_occupied: true,
  raw_lux: 95,
  ambient: 35,
  held: true,
  dark: true,
  deadline: "2026-01-12T20:02:05+01:00",
  last_action: { action: "turned_on", reason: "presence_dark", at: "2026-01-12T19:55:00+01:00" },
  lights: [
    light(),
    light({
      entity_id: "light.cappa",
      name: "Cappa",
      state: "off",
      brightness: null,
      dimmable: false,
      contribution: null,
      samples: 0,
      updated: null,
    }),
  ],
  sensor_entities: ["number.cucina_presenza_sensitivity", "select.cucina_presenza_range"],
  ...over,
});

export const snapshot = (over: Partial<Snapshot> = {}): Snapshot => ({
  entry_id: "entry",
  settings: {
    settle_seconds: 75,
    learn_ambient_max: 60,
    learn_min_previous: 90,
    learn_weight: 0.2,
  },
  rooms: [
    room(),
    room({
      id: "sub-living",
      name: "Salone",
      area_id: "salone",
      status: "off",
      enabled: false,
      occupied: null,
      zone_occupied: false,
      deadline: null,
      held: false,
      dark: false,
      ambient: 150,
      raw_lux: 150,
      last_action: null,
      lights: [
        light({ entity_id: "light.salone", name: "Salone", state: "off", brightness: null }),
      ],
    }),
  ],
  ...over,
});

export const hass = (language = "it"): HomeAssistant =>
  ({
    language,
    locale: { language, time_format: "24" },
    config: { time_zone: "Europe/Rome" },
    states: {} as Record<string, HassEntity>,
    areas: {},
    user: { is_admin: true },
    connection: {} as HomeAssistant["connection"],
    callWS: async () => undefined as never,
  }) as HomeAssistant;
