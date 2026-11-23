// Time bands of a room (config key `schedule`): formatting and validation.
// The first active band in list order sets the waits before turning off;
// outside the bands the room's own values apply.

import type { FormatContext } from "./format";
import type { Localize } from "./localize";
import type { Band, RoomSnapshot } from "./types";

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];

export const MAX_BANDS = 8;
/** Limits of the waits, as the room's own empty_wait and zone_wait. */
export const WAIT_MAX = 3600;

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

/** True when the band ends at or before its start, so it ends the next day. */
export const crossesMidnight = (band: Pick<Band, "start" | "end">): boolean => {
  const start = clockMinutes(band.start);
  const end = clockMinutes(band.end);
  return start !== null && end !== null && end <= start;
};

/** "07:00–09:30", or "22:00–06:00 next day" for a band that crosses midnight. */
export const bandRange = (band: Pick<Band, "start" | "end">, ctx: FormatContext): string => {
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

/** "45 s", "2 min", "1 min 30 s". */
export const formatSeconds = (seconds: number): string => {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return rest ? `${m} min ${rest} s` : `${m} min`;
};

/** "wait 90 s · nearby rooms 5 min": the band's overrides. */
export const overridesText = (band: Band, t: Localize): string =>
  [
    band.empty_wait !== null && band.empty_wait !== undefined
      ? t("band.empty_wait", { wait: formatSeconds(band.empty_wait) })
      : "",
    band.zone_wait !== null && band.zone_wait !== undefined
      ? t("band.zone_wait", { wait: formatSeconds(band.zone_wait) })
      : "",
  ]
    .filter(Boolean)
    .join(" · ");

/** The band's name, or "Band 2" by its position. */
export const bandName = (band: Band, index: number, t: Localize): string =>
  band.name?.trim() || t("band.n", { n: index + 1 });

const validWait = (v: number | null | undefined) =>
  v === null || v === undefined || (Number.isInteger(v) && v >= 0 && v <= WAIT_MAX);

/** Error keys of one band (strings band_error.<key>); empty when valid. */
export const bandErrors = (band: Band): string[] => {
  const errors: string[] = [];
  if (clockMinutes(band.start) === null) errors.push("start");
  if (clockMinutes(band.end) === null) errors.push("end");
  if (!validWait(band.empty_wait) || !validWait(band.zone_wait)) errors.push("wait_range");
  const none = (v: number | null | undefined) => v === null || v === undefined;
  if (none(band.empty_wait) && none(band.zone_wait)) errors.push("no_override");
  if (band.days?.some((d) => !(DAYS as readonly string[]).includes(d))) errors.push("days");
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

/** The bands of a room's values, in a shape the editor can work with. */
export const normalizeBands = (value: unknown): Band[] =>
  Array.isArray(value)
    ? value.map((b: Partial<Band>) => ({
        ...(b.id ? { id: b.id } : {}),
        name: b.name ?? null,
        start: toClock(b.start),
        end: toClock(b.end),
        days: DAYS.filter((d) => (b.days ?? []).includes(d)),
        empty_wait: b.empty_wait ?? null,
        zone_wait: b.zone_wait ?? null,
      }))
    : [];

/** The bands as saved: empty names as null; new bands without an id. */
export const serializeBands = (bands: Band[]): Band[] =>
  bands.map((b) => ({
    ...(b.id ? { id: b.id } : {}),
    name: b.name?.trim() || null,
    start: b.start,
    end: b.end,
    days: [...b.days],
    empty_wait: b.empty_wait ?? null,
    zone_wait: b.zone_wait ?? null,
  }));

/** The waits in force for a room: the snapshot's, or the room's own values. */
export const effectiveWaits = (room: RoomSnapshot) => ({
  empty_wait: room.effective?.empty_wait ?? room.config.empty_wait ?? 30,
  zone_wait: room.effective?.zone_wait ?? room.config.zone_wait ?? 150,
});

/** The active band of a room with its position, if any. */
export const activeBand = (room: RoomSnapshot): { band: Band; index: number } | null => {
  if (!room.active_band) return null;
  const bands = room.config.schedule ?? [];
  const index = bands.findIndex((b) => b.id === room.active_band);
  return index < 0 ? null : { band: bands[index], index };
};
