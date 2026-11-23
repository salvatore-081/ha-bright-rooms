// Pure formatting helpers: times, countdowns, lux and the texts that explain a room.
// The card uses only the keys under card., status., time., deadline. and lux.
// (vite.card.config.ts): keep the helpers it calls within those prefixes.

import type { Localize } from "./localize";
import type { HomeAssistant, LastAction, LightSnapshot, RoomSnapshot, RoomStatus } from "./types";

export interface FormatContext {
  language: string;
  timeZone: string;
  hour12?: boolean;
  now: Date;
  t: Localize;
}

export const formatContext = (
  hass: HomeAssistant,
  t: Localize,
  now = new Date(),
): FormatContext => {
  const fmt = hass.locale?.time_format;
  return {
    language: hass.locale?.language || hass.language || "en",
    timeZone: hass.config.time_zone,
    hour12: fmt === "12" ? true : fmt === "24" ? false : undefined,
    now,
    t,
  };
};

const safeZone = (timeZone: string): string | undefined => {
  try {
    new Intl.DateTimeFormat("en", { timeZone });
    return timeZone;
  } catch {
    return undefined;
  }
};

const dayKey = (date: Date, timeZone: string): string =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: safeZone(timeZone),
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);

/** "15:20" (or "3:20 PM"), in the time zone of Home Assistant. */
export const formatTime = (iso: string | null | undefined, ctx: FormatContext): string => {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(ctx.language, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: ctx.hour12,
    timeZone: safeZone(ctx.timeZone),
  }).format(date);
};

/** "today 15:20", "yesterday 9:05", or "12 Jan 15:20". */
export const formatDayTime = (iso: string | null | undefined, ctx: FormatContext): string => {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = formatTime(iso, ctx);
  const day = dayKey(date, ctx.timeZone);
  if (day === dayKey(ctx.now, ctx.timeZone)) return ctx.t("time.today_at", { time });
  const yesterday = new Date(ctx.now.getTime() - 86_400_000);
  if (day === dayKey(yesterday, ctx.timeZone)) return ctx.t("time.yesterday_at", { time });
  const date_ = new Intl.DateTimeFormat(ctx.language, {
    day: "numeric",
    month: "short",
    timeZone: safeZone(ctx.timeZone),
  }).format(date);
  return ctx.t("time.date_at", { date: date_, time });
};

/** "just now", "5 minutes ago", "2 hours ago"; older than 12 hours: formatDayTime. */
export const formatAgo = (iso: string | null | undefined, ctx: FormatContext): string => {
  if (!iso) return "";
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return "";
  const seconds = Math.max(0, (ctx.now.getTime() - at) / 1000);
  if (seconds < 45) return ctx.t("time.just_now");
  if (seconds >= 12 * 3600) return formatDayTime(iso, ctx);
  const rtf = new Intl.RelativeTimeFormat(ctx.language, { numeric: "auto" });
  return seconds < 3600
    ? rtf.format(-Math.max(1, Math.round(seconds / 60)), "minute")
    : rtf.format(-Math.round(seconds / 3600), "hour");
};

/** Time left as a clock: "0:45", "4:05", "1:02:03"; "0:00" once passed. */
export const formatCountdown = (ms: number): string => {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
};

/** Milliseconds from `now` to an ISO time, or null. */
export const msUntil = (iso: string | null | undefined, now: Date): number | null => {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  return Number.isNaN(at) ? null : at - now.getTime();
};

// ------------------------------------------------------------- light

/** "35 lx", "1,200 lx" in the user's language; "—" without a value. */
export const formatLux = (value: number | null | undefined, language: string): string =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : `${new Intl.NumberFormat(language, { maximumFractionDigits: 0 }).format(value)} lx`;

/** Brightness 0–255 as a percentage (1 % at least when on), or null. */
export const brightnessPct = (brightness: number | null | undefined): number | null =>
  brightness === null || brightness === undefined
    ? null
    : brightness <= 0
      ? 0
      : Math.min(100, Math.max(1, Math.round((brightness / 255) * 100)));

export const isOn = (light: LightSnapshot) => light.state === "on";

/** "Off", "On", "On · 45 %", "Unavailable". */
export const lightText = (light: LightSnapshot, t: Localize): string => {
  if (light.state === "off") return t("light.off");
  if (light.state !== "on") return t("light.unavailable");
  const pct = light.dimmable ? brightnessPct(light.brightness) : null;
  return pct === null ? t("light.on") : t("light.on_pct", { pct });
};

export const lightsOn = (room: RoomSnapshot) => room.lights.filter(isOn).length;

/** The ambient light as text: "35 lx", or why there is none. */
export const ambientText = (room: RoomSnapshot, ctx: FormatContext): string => {
  if (!room.config.illuminance_sensor) return ctx.t("lux.no_sensor");
  if (room.ambient === null) return ctx.t("lux.no_reading");
  return formatLux(room.ambient, ctx.language);
};

/** "Dark", "Bright", or "No reading" (which counts as dark). */
export const darkText = (room: RoomSnapshot, t: Localize): string =>
  room.dark === null ? t("lux.dark_unknown") : t(room.dark ? "lux.dark" : "lux.bright");

export interface LuxScale {
  /** Upper end of the bar, in lux. */
  max: number;
  /** Positions on the bar, 0–100; value null without a reading. */
  value: number | null;
  dark: number;
  bright: number;
  /** The value is past the end of the bar. */
  overflow: boolean;
}

/** Where the ambient light and the two thresholds fall on a bar from 0 to 1.5 × bright. */
export const luxScale = (
  ambient: number | null,
  darkBelow: number,
  brightAbove: number,
): LuxScale => {
  const max = Math.max(1, Math.round(Math.max(brightAbove * 1.5, darkBelow * 2)));
  const pos = (v: number) => Math.min(100, Math.max(0, (v / max) * 100));
  return {
    max,
    value: ambient === null ? null : pos(ambient),
    dark: pos(darkBelow),
    bright: pos(brightAbove),
    overflow: ambient !== null && ambient > max,
  };
};

// ------------------------------------------------------------- status

export type Tone = "light" | "active" | "warning" | "idle" | "off" | "error";

const STATUS_ICONS: Record<RoomStatus, string> = {
  disabled: "mdi:pause-circle-outline",
  off: "mdi:lightbulb-outline",
  on: "mdi:lightbulb-on",
  waiting: "mdi:timer-sand",
  dimmed: "mdi:lightbulb-on-30",
};

const STATUS_TONES: Record<RoomStatus, Tone> = {
  disabled: "off",
  off: "idle",
  on: "light",
  waiting: "active",
  dimmed: "warning",
};

export const statusIcon = (status: RoomStatus): string =>
  STATUS_ICONS[status] ?? "mdi:help-circle-outline";

export const statusTone = (status: RoomStatus): Tone => STATUS_TONES[status] ?? "idle";

export const statusLabel = (status: RoomStatus, t: Localize): string => t(`status.${status}`);

/** "Occupied", "Empty", "Empty, someone nearby", "Presence sensors unavailable". */
export const occupancyText = (room: RoomSnapshot, t: Localize): string => {
  if (room.occupied === null) return t("occupancy.unavailable");
  if (room.occupied)
    return room.zone_occupied ? t("occupancy.occupied_zone") : t("occupancy.occupied");
  return room.zone_occupied ? t("occupancy.zone") : t("occupancy.empty");
};

/**
 * The label of the countdown to `deadline`, with a `{time}` placeholder left
 * for the countdown; null without a deadline.
 */
export const deadlineTemplate = (room: RoomSnapshot, t: Localize): string | null => {
  if (!room.deadline) return null;
  switch (room.status) {
    case "waiting": {
      const dims =
        (room.config.dim_percent ?? 30) < 100 && room.lights.some((l) => l.dimmable && isOn(l));
      return t(dims ? "deadline.dims" : "deadline.off");
    }
    case "dimmed":
      return t("deadline.off");
    case "on":
      return t("deadline.bright");
    default:
      return t("deadline.next");
  }
};

/** Fill a template's `{time}` with the countdown to `deadline`. */
export const countdownText = (template: string, deadline: string, now: Date): string =>
  template.replaceAll("{time}", formatCountdown(msUntil(deadline, now) ?? 0));

/** "Turned on: someone came in and it was dark". */
export const lastActionText = (last: LastAction, t: Localize): string => {
  const action = t(`action.${last.action}`);
  const key = `reason.${last.reason}`;
  const reason = t(key);
  return reason === key ? `${action}: ${last.reason}` : `${action}: ${reason}`;
};

export const LAST_ACTION_ICONS: Record<string, string> = {
  turned_on: "mdi:lightbulb-on-outline",
  turned_off: "mdi:lightbulb-off-outline",
  dimmed: "mdi:lightbulb-on-30",
  restored: "mdi:lightbulb-on-outline",
  skipped_on: "mdi:weather-sunny",
};
