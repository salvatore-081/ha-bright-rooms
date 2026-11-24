// Bands of a room (config key `schedule`): formatting and validation.
// A band holds in a time window, with a given measured light, or both; the
// first active band in list order overrides some room settings, and outside
// the bands the room's own values apply.

import type { FormatContext } from "./format";
import type { Localize } from "./localize";
import type { Band, BandLight, RoomSnapshot } from "./types";

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];

export const MAX_BANDS = 8;
/** Limits of the overrides, as the room's own settings (seconds). */
export const WAIT_MAX = 3600;
export const ON_DELAY_MAX = 600;
export const LIGHTS: readonly BandLight[] = ["bright", "dark"];

const CLOCK = /^([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$/;

/** Minutes since midnight of "HH:MM" (or "HH:MM:SS"), or null if not a time. */
export const clockMinutes = (value: string | null | undefined): number | null => {
  const m = value ? CLOCK.exec(value) : null;
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};

/** "HH:MM" from "HH:MM" or "HH:MM:SS"; anything else as it is. */
export const toClock = (value: string | null | undefined): string =>
  value && CLOCK.test(value) ? value.slice(0, 5) : (value ?? "");

/** A time of day formatted like the frontend ("22:00" or "10:00 PM"). */
export const formatClock = (value: string | null | undefined, ctx: FormatContext): string => {
  const minutes = clockMinutes(value);
  if (minutes === null) return value ?? "";
  const date = new Date(Date.UTC(2000, 0, 1, Math.floor(minutes / 60), minutes % 60));
  return new Intl.DateTimeFormat(ctx.language, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: ctx.hour12,
    timeZone: "UTC",
  }).format(date);
};

const none = (v: unknown) => v === null || v === undefined;

/** The band has a time window (start and end both set). */
export const hasWindow = (band: Pick<Band, "start" | "end">): boolean =>
  Boolean(band.start) && Boolean(band.end);

/** True when the window ends at or before its start, so it ends the next day. */
export const crossesMidnight = (band: Pick<Band, "start" | "end">): boolean => {
  const start = clockMinutes(band.start);
  const end = clockMinutes(band.end);
  return start !== null && end !== null && end <= start;
};

/** "07:00–09:30", "22:00–06:00 next day"; "" without a window. */
export const bandRange = (band: Pick<Band, "start" | "end">, ctx: FormatContext): string => {
  if (!hasWindow(band)) return "";
  const params = { start: formatClock(band.start, ctx), end: formatClock(band.end, ctx) };
  return ctx.t(crossesMidnight(band) ? "band.range_overnight" : "band.range", params);
};

/** "Every day", "Mon–Fri", "Sat, Sun", "Mon, Wed–Fri": runs of three or more days joined. */
export const daysText = (days: readonly string[] | null | undefined, t: Localize): string => {
  const set = new Set(days ?? []);
  const picked = DAYS.filter((d) => set.has(d));
  if (picked.length === 0 || picked.length === DAYS.length) return t("band.every_day");
  const parts: string[] = [];
  let i = 0;
  while (i < DAYS.length) {
    if (!set.has(DAYS[i])) {
      i++;
      continue;
    }
    let j = i;
    while (j + 1 < DAYS.length && set.has(DAYS[j + 1])) j++;
    const name = (d: string) => t(`day.${d}`);
    if (j - i >= 2) parts.push(`${name(DAYS[i])}–${name(DAYS[j])}`);
    else for (let k = i; k <= j; k++) parts.push(name(DAYS[k]));
    i = j + 1;
  }
  return parts.join(", ");
};

const someDays = (days: readonly string[] | null | undefined) =>
  (days?.length ?? 0) > 0 && (days?.length ?? 0) < DAYS.length;

/** "45 s", "2 min", "1 min 30 s". */
export const formatSeconds = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m} min ${rest} s` : `${m} min`;
};

export interface SummaryOptions {
  /** Names of the rooms, by id (for a light measured in another room). */
  roomNames?: Record<string, string>;
  /** The room the band belongs to: its own id as light_room counts as "this room". */
  roomId?: string;
}

/** "Dark", "Dark (Table)", "Bright"; "" without a light condition. */
export const lightText = (band: Band, t: Localize, opts: SummaryOptions = {}): string => {
  if (!band.light) return "";
  const text = t(`band.light_${band.light}`);
  if (!band.light_room || band.light_room === opts.roomId) return text;
  const room = opts.roomNames?.[band.light_room] ?? t("band.other_room");
  return `${text} (${room})`;
};

/** "Dark (Table) · Mon–Fri 17:00–23:00": when the band holds. */
export const conditionsText = (band: Band, ctx: FormatContext, opts: SummaryOptions = {}) => {
  const { t } = ctx;
  const time = [someDays(band.days) ? daysText(band.days, t) : "", bandRange(band, ctx)]
    .filter(Boolean)
    .join(" ");
  return [lightText(band, t, opts), time].filter(Boolean).join(" · ") || t("band.always");
};

/** "zone: none", "zones: 2"; "" when the room's own zone applies. */
export const zoneText = (zones: readonly string[] | null | undefined, t: Localize): string =>
  zones === null || zones === undefined
    ? ""
    : zones.length === 0
      ? t("band.zone_none")
      : t("band.zone_count", { n: zones.length });

/** "on after 20 s · wait 90 s · zone wait 5 min · zone: none": what the band changes. */
export const overridesText = (band: Band, t: Localize): string =>
  [
    none(band.on_delay) ? "" : t("band.on_delay", { wait: formatSeconds(band.on_delay!) }),
    none(band.empty_wait) ? "" : t("band.empty_wait", { wait: formatSeconds(band.empty_wait!) }),
    none(band.zone_wait) ? "" : t("band.zone_wait", { wait: formatSeconds(band.zone_wait!) }),
    zoneText(band.zone_sensors, t),
  ]
    .filter(Boolean)
    .join(" · ");

/** The whole summary line: conditions, then overrides. */
export const bandSummary = (band: Band, ctx: FormatContext, opts: SummaryOptions = {}) =>
  [conditionsText(band, ctx, opts), overridesText(band, ctx.t)].filter(Boolean).join(" · ");

/** The band's name, or "Band 2" by its position. */
export const bandName = (band: Band, index: number, t: Localize): string =>
  band.name?.trim() || t("band.n", { n: index + 1 });

const inRange = (v: number | null | undefined, max: number) =>
  none(v) || (Number.isInteger(v) && v! >= 0 && v! <= max);

/** Error keys of one band (strings band_error.<key>); empty when valid. */
export const bandErrors = (band: Band): string[] => {
  const errors: string[] = [];
  const startSet = Boolean(band.start);
  const endSet = Boolean(band.end);
  if (startSet !== endSet) errors.push("time_pair");
  if (startSet && clockMinutes(band.start) === null) errors.push("start");
  if (endSet && clockMinutes(band.end) === null) errors.push("end");
  if (band.light !== null && band.light !== undefined && !LIGHTS.includes(band.light))
    errors.push("light");
  if (!startSet && !endSet && !band.light) errors.push("no_condition");
  if (band.days?.some((d) => !(DAYS as readonly string[]).includes(d))) errors.push("days");
  if (!inRange(band.on_delay, ON_DELAY_MAX)) errors.push("on_delay_range");
  if (!inRange(band.empty_wait, WAIT_MAX) || !inRange(band.zone_wait, WAIT_MAX))
    errors.push("wait_range");
  if (
    none(band.on_delay) &&
    none(band.empty_wait) &&
    none(band.zone_wait) &&
    none(band.zone_sensors)
  )
    errors.push("no_override");
  return errors;
};

export interface ScheduleCheck {
  /** Errors by band index. */
  bands: Record<number, string[]>;
  /** Error of the whole list (too many bands). */
  list?: string;
}

export const validateSchedule = (bands: Band[]): ScheduleCheck => {
  const check: ScheduleCheck = { bands: {} };
  bands.forEach((band, i) => {
    const errors = bandErrors(band);
    if (errors.length) check.bands[i] = errors;
  });
  if (bands.length > MAX_BANDS) check.list = "too_many";
  return check;
};

export const scheduleValid = (check: ScheduleCheck): boolean =>
  !check.list && Object.keys(check.bands).length === 0;

export interface ScheduleSaveError {
  /** The error key (schedule_invalid, or another the integration sends). */
  key: string;
  /** The bands it points at; empty: the list as a whole. */
  bands: number[];
}

/**
 * The integration's save errors about the bands: `schedule` for the list and
 * `schedule.<i>` for each wrong band (a band number in the text of the
 * `schedule` error is understood too). Null when the bands are fine.
 */
export const scheduleSaveError = (errors: Record<string, string>): ScheduleSaveError | null => {
  let key: string | null = null;
  const bands = new Set<number>();
  for (const [field, value] of Object.entries(errors)) {
    const byField = /^schedule\.(\d+)/.exec(field);
    if (field !== "schedule" && !byField) continue;
    key ??= value.split(/[\s:]/)[0] || "schedule_invalid";
    if (byField) bands.add(Number(byField[1]));
    else {
      const byText = /\d+/.exec(value);
      if (byText) bands.add(Number(byText[0]));
    }
  }
  return key === null ? null : { key, bands: [...bands].sort((a, b) => a - b) };
};

const numberOrNull = (v: unknown): number | null =>
  typeof v === "number" && !Number.isNaN(v) ? v : null;

/** The bands of a room's values, in a shape the editor can work with. */
export const normalizeBands = (value: unknown): Band[] =>
  Array.isArray(value)
    ? value.map((raw: Partial<Band>) => ({
        ...(raw.id ? { id: raw.id } : {}),
        name: raw.name ?? null,
        start: raw.start ? toClock(raw.start) : null,
        end: raw.end ? toClock(raw.end) : null,
        days: DAYS.filter((d) => (raw.days ?? []).includes(d)),
        light: raw.light === "bright" || raw.light === "dark" ? raw.light : null,
        light_room: raw.light_room ?? null,
        on_delay: numberOrNull(raw.on_delay),
        empty_wait: numberOrNull(raw.empty_wait),
        zone_wait: numberOrNull(raw.zone_wait),
        zone_sensors: Array.isArray(raw.zone_sensors) ? [...raw.zone_sensors] : null,
      }))
    : [];

/** The bands as saved: empty names and times as null; new bands without an id. */
export const serializeBands = (bands: Band[]): Band[] =>
  bands.map((b) => ({
    ...(b.id ? { id: b.id } : {}),
    name: b.name?.trim() || null,
    start: b.start || null,
    end: b.end || null,
    days: [...b.days],
    light: b.light ?? null,
    light_room: b.light ? (b.light_room ?? null) : null,
    on_delay: b.on_delay ?? null,
    empty_wait: b.empty_wait ?? null,
    zone_wait: b.zone_wait ?? null,
    zone_sensors: b.zone_sensors ? [...b.zone_sensors] : null,
  }));

/** The room's own values of what a band can override. */
export const roomValues = (config: Record<string, unknown>) => ({
  on_delay: Number(config.on_delay ?? 0),
  empty_wait: Number(config.empty_wait ?? 30),
  zone_wait: Number(config.zone_wait ?? 150),
  zone_sensors: Array.isArray(config.zone_sensors) ? (config.zone_sensors as string[]) : [],
});

/** The values in force for a room: the snapshot's, or the room's own. */
export const effectiveValues = (room: RoomSnapshot) => ({
  ...roomValues(room.config),
  ...(room.effective ?? {}),
});

/** The active band of a room with its position, if any. */
export const activeBand = (room: RoomSnapshot): { band: Band; index: number } | null => {
  if (!room.active_band) return null;
  const bands = room.config.schedule ?? [];
  const index = bands.findIndex((b) => b.id === room.active_band);
  return index < 0 ? null : { band: bands[index], index };
};
