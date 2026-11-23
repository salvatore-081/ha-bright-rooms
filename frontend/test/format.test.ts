import { describe, expect, it } from "vitest";
import {
  ambientText,
  brightnessPct,
  countdownText,
  darkText,
  deadlineTemplate,
  formatAgo,
  formatContext,
  formatCountdown,
  formatLux,
  lastActionText,
  lightText,
  luxScale,
  occupancyText,
  statusIcon,
  statusLabel,
  statusTone,
} from "../src/format";
import { localizer } from "../src/localize";
import { NOW, hass, light, room } from "./fixtures";

const en = localizer("en");
const it_ = localizer("it");
const ctx = formatContext(hass("en"), en, NOW);
const ctxIt = formatContext(hass("it"), it_, NOW);

describe("countdowns", () => {
  it("formats the time left as a clock", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-5000)).toBe("0:00");
    expect(formatCountdown(400)).toBe("0:01");
    expect(formatCountdown(45_000)).toBe("0:45");
    expect(formatCountdown(245_000)).toBe("4:05");
    expect(formatCountdown(3_723_000)).toBe("1:02:03");
  });

  it("fills the template with the countdown to the deadline", () => {
    expect(countdownText("Turns off in {time}", "2026-01-12T20:02:05+01:00", NOW)).toBe(
      "Turns off in 2:05",
    );
  });

  it("names the next step by status", () => {
    expect(deadlineTemplate(room(), en)).toBe("Dims in {time}");
    expect(deadlineTemplate(room({ config: { ...room().config, dim_percent: 100 } }), en)).toBe(
      "Turns off in {time}",
    );
    const onOff = room({ lights: [light({ dimmable: false, brightness: null })] });
    expect(deadlineTemplate(onOff, en)).toBe("Turns off in {time}");
    expect(deadlineTemplate(room({ status: "dimmed" }), en)).toBe("Turns off in {time}");
    expect(deadlineTemplate(room({ status: "on" }), it_)).toBe(
      "Spente per la luce del giorno tra {time}",
    );
    expect(deadlineTemplate(room({ deadline: null }), en)).toBeNull();
  });
});

describe("times", () => {
  it("says how long ago, then the day", () => {
    expect(formatAgo("2026-01-12T19:59:40+01:00", ctx)).toBe("just now");
    expect(formatAgo("2026-01-12T19:55:00+01:00", ctx)).toBe("5 minutes ago");
    expect(formatAgo("2026-01-12T19:55:00+01:00", ctxIt)).toBe("5 minuti fa");
    expect(formatAgo("2026-01-12T17:00:00+01:00", ctx)).toBe("3 hours ago");
    expect(formatAgo("2026-01-11T21:15:00+01:00", ctxIt)).toBe("ieri 21:15");
    expect(formatAgo(null, ctx)).toBe("");
  });
});

describe("light", () => {
  it("formats lux in the user's language", () => {
    expect(formatLux(35, "en")).toBe("35 lx");
    expect(formatLux(1234.4, "en")).toBe("1,234 lx");
    expect(formatLux(1234.4, "it")).toBe("1234 lx");
    expect(formatLux(12000, "it")).toBe("12.000 lx");
    expect(formatLux(null, "en")).toBe("—");
  });

  it("turns brightness into a percentage", () => {
    expect(brightnessPct(255)).toBe(100);
    expect(brightnessPct(128)).toBe(50);
    expect(brightnessPct(1)).toBe(1);
    expect(brightnessPct(0)).toBe(0);
    expect(brightnessPct(null)).toBeNull();
  });

  it("describes a light", () => {
    expect(lightText(light(), en)).toBe("On · 50 %");
    expect(lightText(light({ dimmable: false, brightness: null }), en)).toBe("On");
    expect(lightText(light({ state: "off", brightness: null }), it_)).toBe("Spenta");
    expect(lightText(light({ state: "unavailable" }), en)).toBe("Unavailable");
  });

  it("explains the ambient light", () => {
    expect(ambientText(room(), ctx)).toBe("35 lx");
    expect(ambientText(room({ ambient: null }), ctx)).toBe("no reading");
    const noSensor = room({ config: { ...room().config, illuminance_sensor: null } });
    expect(ambientText(noSensor, ctx)).toBe("no light sensor");
    expect(darkText(room(), en)).toBe("Dark");
    expect(darkText(room({ dark: false }), it_)).toBe("Luminoso");
    expect(darkText(room({ dark: null }), en)).toBe("No reading");
  });

  it("places the ambient light and the thresholds on the bar", () => {
    expect(luxScale(60, 40, 80)).toEqual({
      max: 120,
      value: 50,
      dark: (40 / 120) * 100,
      bright: (80 / 120) * 100,
      overflow: false,
    });
    expect(luxScale(500, 40, 80)).toMatchObject({ value: 100, overflow: true });
    expect(luxScale(null, 40, 80).value).toBeNull();
    expect(luxScale(10, 100, 120).max).toBe(200);
  });
});

describe("status and reasons", () => {
  it("has an icon, a tone and a label for each status", () => {
    expect(statusIcon("on")).toBe("mdi:lightbulb-on");
    expect(statusTone("on")).toBe("light");
    expect(statusTone("disabled")).toBe("off");
    expect(statusLabel("dimmed", it_)).toBe("Abbassate, stanno per spegnersi");
  });

  it("explains the last action in words", () => {
    expect(lastActionText(room().last_action!, en)).toBe(
      "Turned on: someone came in and it was dark",
    );
    expect(
      lastActionText({ action: "skipped_on", reason: "not_dark", at: NOW.toISOString() }, it_),
    ).toBe("Non accese: c'era abbastanza luce del giorno");
    expect(
      lastActionText(
        { action: "turned_off", reason: "new_reason" as never, at: NOW.toISOString() },
        en,
      ),
    ).toBe("Turned off: new_reason");
  });

  it("describes presence in the room and nearby", () => {
    expect(occupancyText(room(), en)).toBe("Empty, someone nearby");
    expect(occupancyText(room({ occupied: true, zone_occupied: false }), en)).toBe(
      "Someone is here",
    );
    expect(occupancyText(room({ occupied: null }), it_)).toBe(
      "Sensori di presenza non disponibili",
    );
  });
});
