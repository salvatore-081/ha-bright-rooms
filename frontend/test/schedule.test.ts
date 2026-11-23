import { describe, expect, it } from "vitest";
import "../src/components/br-schedule-editor";
import { formatContext } from "../src/format";
import { localizer } from "../src/localize";
import {
  activeBand,
  bandErrors,
  bandName,
  bandRange,
  crossesMidnight,
  daysText,
  effectiveWaits,
  formatSeconds,
  normalizeBands,
  overridesText,
  scheduleSaveError,
  scheduleValid,
  serializeBands,
  validateSchedule,
} from "../src/schedule";
import type { Band } from "../src/types";
import { NOW, hass, room } from "./fixtures";

const en = localizer("en");
const it_ = localizer("it");
const ctx = formatContext(hass("en"), en, NOW);
const ctxIt = formatContext(hass("it"), it_, NOW);

const band = (over: Partial<Band> = {}): Band => ({
  id: "b",
  name: "Sera",
  start: "19:00",
  end: "23:30",
  days: [],
  empty_wait: 90,
  zone_wait: null,
  ...over,
});

const mount = async <T extends HTMLElement & { updateComplete: Promise<boolean> }>(el: T) => {
  document.body.appendChild(el);
  await el.updateComplete;
  return el.shadowRoot!;
};

describe("band formatting", () => {
  it("formats ranges, also across midnight", () => {
    expect(bandRange(band(), ctxIt)).toBe("19:00–23:30");
    expect(crossesMidnight(band({ start: "22:00", end: "06:00" }))).toBe(true);
    expect(crossesMidnight(band({ start: "08:00", end: "08:00" }))).toBe(true);
    expect(bandRange(band({ start: "22:00", end: "06:00" }), ctxIt)).toBe(
      "22:00–06:00 del giorno dopo",
    );
    const ctx12 = { ...ctx, hour12: true };
    expect(bandRange(band({ start: "22:00", end: "06:30" }), ctx12)).toBe(
      "10:00 PM–06:30 AM next day",
    );
  });

  it("sums up the days", () => {
    expect(daysText([], it_)).toBe("Tutti i giorni");
    expect(daysText(["sun", "mon", "tue", "wed", "thu", "fri", "sat"], en)).toBe("Every day");
    expect(daysText(["fri", "mon", "tue", "wed", "thu"], it_)).toBe("Lun–Ven");
    expect(daysText(["sat", "sun"], it_)).toBe("Sab, Dom");
    expect(daysText(["mon", "wed", "thu", "fri", "sun"], en)).toBe("Mon, Wed–Fri, Sun");
  });

  it("describes the overrides and names bands", () => {
    expect(formatSeconds(45)).toBe("45 s");
    expect(formatSeconds(120)).toBe("2 min");
    expect(formatSeconds(90)).toBe("1 min 30 s");
    expect(overridesText(band({ zone_wait: 300 }), it_)).toBe(
      "attesa 1 min 30 s · stanze vicine 5 min",
    );
    expect(overridesText(band({ empty_wait: null, zone_wait: 0 }), en)).toBe("nearby rooms 0 s");
    expect(bandName(band({ name: " " }), 1, it_)).toBe("Fascia 2");
  });
});

describe("band validation", () => {
  it("needs valid times and at least one override", () => {
    expect(bandErrors(band())).toEqual([]);
    expect(bandErrors(band({ start: "25:00", end: "" }))).toEqual(["start", "end"]);
    expect(bandErrors(band({ empty_wait: null }))).toEqual(["no_override"]);
    expect(bandErrors(band({ empty_wait: 4000 }))).toEqual(["wait_range"]);
    expect(bandErrors(band({ empty_wait: 1.5 }))).toEqual(["wait_range"]);
    expect(bandErrors(band({ days: ["mon", "xyz"] }))).toEqual(["days"]);
  });

  it("checks the list, at most 8 bands", () => {
    expect(scheduleValid(validateSchedule([band(), band()]))).toBe(true);
    const nine = Array.from({ length: 9 }, () => band());
    expect(validateSchedule(nine).list).toBe("too_many");
    expect(validateSchedule([band(), band({ end: "x" })]).bands).toEqual({ 1: ["end"] });
  });

  it("reads the integration's save errors, with or without a band", () => {
    expect(scheduleSaveError({ name: "name_taken" })).toBeNull();
    expect(scheduleSaveError({ schedule: "schedule_invalid" })).toEqual({
      key: "schedule_invalid",
      bands: [],
    });
    // As the integration answers: the list and each wrong band.
    expect(
      scheduleSaveError({
        schedule: "schedule_invalid",
        "schedule.2": "schedule_invalid",
        "schedule.0": "schedule_invalid",
      }),
    ).toEqual({ key: "schedule_invalid", bands: [0, 2] });
    expect(scheduleSaveError({ schedule: "schedule_invalid: 1" })).toEqual({
      key: "schedule_invalid",
      bands: [1],
    });
  });

  it("normalizes loaded bands and serializes new ones without id", () => {
    const [b] = normalizeBands([{ start: "07:00:00", end: "09:00", days: ["sun", "mon"] }]);
    expect(b).toEqual({
      name: null,
      start: "07:00",
      end: "09:00",
      days: ["mon", "sun"],
      empty_wait: null,
      zone_wait: null,
    });
    expect(normalizeBands(undefined)).toEqual([]);
    expect(serializeBands([{ ...b, name: "  ", empty_wait: 60 }])).toEqual([
      { ...b, name: null, empty_wait: 60 },
    ]);
  });

  it("finds the active band and the waits in force", () => {
    expect(activeBand(room())?.band.name).toBe("Sera");
    expect(activeBand(room({ active_band: null }))).toBeNull();
    expect(effectiveWaits(room())).toEqual({ empty_wait: 90, zone_wait: 150 });
    expect(effectiveWaits(room({ effective: undefined }))).toEqual({
      empty_wait: 30,
      zone_wait: 150,
    });
  });
});

describe("schedule editor", () => {
  const bands = () => room().config.schedule!;

  it("lists the bands with ranges, days, overrides and the active marker", async () => {
    const el = document.createElement("br-schedule-editor");
    Object.assign(el, { ctx: ctxIt, bands: bands(), activeBand: "band-evening" });
    const root = await mount(el);
    const rows = [...root.querySelectorAll(".band")];
    expect(rows).toHaveLength(2);
    const text = (e: Element) => e.textContent!.replace(/\s+/g, " ");
    expect(text(rows[0])).toContain("Sera");
    expect(text(rows[0])).toContain("19:00–23:30 · attesa 1 min 30 s");
    expect(text(rows[0])).toContain("Tutti i giorni");
    expect(rows[0].querySelector(".active-marker")?.textContent).toContain("Attiva ora");
    expect(rows[0].classList).toContain("active");
    expect(text(rows[1])).toContain("Fascia 2");
    expect(text(rows[1])).toContain("23:30–06:00 del giorno dopo");
    expect(text(rows[1])).toContain("Lun–Ven");
    expect(rows[1].querySelector(".active-marker")).toBeNull();
    expect(root.querySelector(".body")).toBeNull(); // saved bands start closed
  });

  it("adds, moves, edits and validates bands", async () => {
    const el = document.createElement("br-schedule-editor");
    Object.assign(el, { ctx, bands: bands(), activeBand: null });
    const root = await mount(el);
    const events: Band[][] = [];
    el.addEventListener("bands-changed", (ev) => {
      events.push((ev as CustomEvent).detail.bands);
      el.bands = events.at(-1)!;
    });
    (root.querySelector('[aria-label="Move Band 2 up"]') as HTMLButtonElement).click();
    expect(events.at(-1)!.map((b) => b.id)).toEqual(["band-night", "band-evening"]);

    (root.querySelector(".footer .btn") as HTMLButtonElement).click();
    await el.updateComplete;
    expect(events.at(-1)).toHaveLength(3);
    expect(events.at(-1)![2].id).toBeUndefined();
    // A new band is open; touched without an override it shows the error.
    const body = root.querySelector(".body")!;
    const day = body.querySelector(".day-toggle") as HTMLButtonElement;
    day.click();
    await el.updateComplete;
    expect(events.at(-1)![2].days).toEqual(["mon"]);
    expect(root.querySelector(".errors")!.textContent).toContain(
      "Set at least one of the two waits.",
    );
    const wait = root.querySelectorAll('.body input[type="number"]')[0] as HTMLInputElement;
    wait.value = "45";
    wait.dispatchEvent(new Event("input"));
    await el.updateComplete;
    expect(events.at(-1)![2].empty_wait).toBe(45);
    expect(root.querySelector(".errors")).toBeNull();
  });

  it("disables adding at the maximum and shows a save error on its band", async () => {
    const el = document.createElement("br-schedule-editor");
    const eight = Array.from({ length: 8 }, (_, i) => ({ ...bands()[0], id: `b${i}` }));
    Object.assign(el, {
      ctx,
      bands: eight,
      saveError: { key: "schedule_invalid", bands: [3] },
    });
    const root = await mount(el);
    expect((root.querySelector(".footer .btn") as HTMLButtonElement).disabled).toBe(true);
    const rows = root.querySelectorAll(".band");
    expect(rows[3].classList).toContain("error");
    expect(rows[3].textContent).toContain("The time bands are not valid.");
  });
});
