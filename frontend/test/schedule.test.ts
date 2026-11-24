import { describe, expect, it } from "vitest";
import "../src/components/br-schedule-editor";
import { newBand, timeOn } from "../src/components/br-schedule-editor";
import "../src/components/br-room-tile";
import { formatContext } from "../src/format";
import { localizer } from "../src/localize";
import {
  activeBand,
  bandErrors,
  bandName,
  bandRange,
  bandSummary,
  conditionsText,
  crossesMidnight,
  daysText,
  effectiveValues,
  formatSeconds,
  normalizeBands,
  overridesText,
  roomValues,
  scheduleSaveError,
  scheduleValid,
  serializeBands,
  validateSchedule,
  zoneText,
} from "../src/schedule";
import type { BrSwitch } from "../src/components/br-switch";
import type { Band } from "../src/types";
import { NOW, hass, room } from "./fixtures";

const en = localizer("en");
const it_ = localizer("it");
const ctx = formatContext(hass("en"), en, NOW);
const ctxIt = formatContext(hass("it"), it_, NOW);
const ROOMS = [
  { id: "sub-kitchen", name: "Cucina" },
  { id: "sub-living", name: "Tavolo" },
];
const names = { roomNames: { "sub-living": "Tavolo" }, roomId: "sub-kitchen" };

const band = (over: Partial<Band> = {}): Band => ({
  id: "b",
  name: "Sera",
  start: "19:00",
  end: "23:30",
  days: [],
  light: null,
  light_room: null,
  on_delay: null,
  empty_wait: 90,
  zone_wait: null,
  zone_sensors: null,
  ...over,
});

const mount = async <T extends HTMLElement & { updateComplete: Promise<boolean> }>(el: T) => {
  document.body.appendChild(el);
  await el.updateComplete;
  return el.shadowRoot!;
};

const text = (e: Element | ShadowRoot) => e.textContent!.replace(/\s+/g, " ");

describe("band formatting", () => {
  it("formats windows, also across midnight, and none", () => {
    expect(bandRange(band(), ctxIt)).toBe("19:00–23:30");
    expect(crossesMidnight(band({ start: "22:00", end: "06:00" }))).toBe(true);
    expect(crossesMidnight(band({ start: "08:00", end: "08:00" }))).toBe(true);
    expect(bandRange(band({ start: "22:00", end: "06:00" }), ctxIt)).toBe(
      "22:00–06:00 del giorno dopo",
    );
    expect(bandRange(band({ start: "22:00", end: "06:30" }), { ...ctx, hour12: true })).toBe(
      "10:00 PM–06:30 AM next day",
    );
    expect(bandRange(band({ start: null, end: null }), ctx)).toBe("");
  });

  it("sums up the days", () => {
    expect(daysText([], it_)).toBe("Tutti i giorni");
    expect(daysText(["sun", "mon", "tue", "wed", "thu", "fri", "sat"], en)).toBe("Every day");
    expect(daysText(["fri", "mon", "tue", "wed", "thu"], it_)).toBe("Lun–Ven");
    expect(daysText(["sat", "sun"], it_)).toBe("Sab, Dom");
    expect(daysText(["mon", "wed", "thu", "fri", "sun"], en)).toBe("Mon, Wed–Fri, Sun");
  });

  it("sums up the conditions", () => {
    const cooktop = room().config.schedule![1];
    expect(conditionsText(cooktop, ctxIt, names)).toBe("Col buio (Tavolo) · Lun–Ven 17:00–23:00");
    expect(conditionsText(band({ light: "bright", start: null, end: null }), ctx, names)).toBe(
      "Bright",
    );
    // This room's own id counts as "this room"; an unknown room is named generically.
    expect(conditionsText(band({ light: "dark", light_room: "sub-kitchen" }), ctx, names)).toBe(
      "Dark · 19:00–23:30",
    );
    expect(conditionsText(band({ light: "dark", light_room: "gone" }), ctxIt, names)).toBe(
      "Col buio (altra stanza) · 19:00–23:30",
    );
    expect(conditionsText(band({ start: null, end: null }), ctx)).toBe("Always");
  });

  it("describes the overrides and the zone", () => {
    expect(formatSeconds(45)).toBe("45 s");
    expect(formatSeconds(120)).toBe("2 min");
    expect(formatSeconds(90)).toBe("1 min 30 s");
    expect(zoneText(null, it_)).toBe("");
    expect(zoneText([], it_)).toBe("zona: nessuna");
    expect(zoneText(["binary_sensor.a", "binary_sensor.b"], en)).toBe("zones: 2");
    expect(overridesText(band({ on_delay: 20, zone_wait: 300, zone_sensors: [] }), it_)).toBe(
      "accensione 20 s · attesa 1 min 30 s · attesa con zona 5 min · zona: nessuna",
    );
    expect(bandSummary(room().config.schedule![1], ctxIt, names)).toBe(
      "Col buio (Tavolo) · Lun–Ven 17:00–23:00 · accensione 20 s · zona: nessuna",
    );
    expect(bandName(band({ name: " " }), 1, it_)).toBe("Fascia 2");
  });
});

describe("band validation", () => {
  it("needs a condition: a whole window or a light", () => {
    expect(bandErrors(band())).toEqual([]);
    expect(bandErrors(band({ start: null, end: null, light: "dark" }))).toEqual([]);
    expect(bandErrors(band({ start: null, end: null }))).toEqual(["no_condition"]);
    expect(bandErrors(band({ start: null, end: null, days: ["sat"] }))).toEqual(["no_condition"]);
    expect(bandErrors(band({ end: null, light: "dark" }))).toEqual(["time_pair"]);
    expect(bandErrors(band({ start: "", light: "bright" }))).toEqual(["time_pair"]);
    expect(bandErrors(band({ start: "25:00" }))).toEqual(["start"]);
    expect(bandErrors(band({ light: "dim" as never }))).toEqual(["light"]);
    expect(bandErrors(band({ days: ["mon", "xyz"] }))).toEqual(["days"]);
  });

  it("needs an override within its range", () => {
    expect(bandErrors(band({ empty_wait: null }))).toEqual(["no_override"]);
    expect(bandErrors(band({ empty_wait: null, zone_sensors: [] }))).toEqual([]);
    expect(bandErrors(band({ empty_wait: null, on_delay: 0 }))).toEqual([]);
    expect(bandErrors(band({ on_delay: 601 }))).toEqual(["on_delay_range"]);
    expect(bandErrors(band({ empty_wait: 4000 }))).toEqual(["wait_range"]);
    expect(bandErrors(band({ zone_wait: 1.5 }))).toEqual(["wait_range"]);
  });

  it("checks the list, at most 8 bands", () => {
    expect(scheduleValid(validateSchedule([band(), band()]))).toBe(true);
    expect(validateSchedule(Array.from({ length: 9 }, () => band())).list).toBe("too_many");
    expect(validateSchedule([band(), band({ end: "x" })]).bands).toEqual({ 1: ["end"] });
  });

  it("reads the integration's save errors, with or without a band", () => {
    expect(scheduleSaveError({ name: "name_taken" })).toBeNull();
    expect(scheduleSaveError({ schedule: "schedule_invalid" })).toEqual({
      key: "schedule_invalid",
      bands: [],
    });
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

  it("loads old time-only bands and saves new ones without id", () => {
    const [old] = normalizeBands([
      { id: "x", start: "07:00:00", end: "09:00", days: ["sun", "mon"], empty_wait: 60 },
    ]);
    expect(old).toEqual({
      id: "x",
      name: null,
      start: "07:00",
      end: "09:00",
      days: ["mon", "sun"],
      light: null,
      light_room: null,
      on_delay: null,
      empty_wait: 60,
      zone_wait: null,
      zone_sensors: null,
    });
    expect(normalizeBands(undefined)).toEqual([]);
    const fresh = {
      ...newBand(),
      name: "  ",
      start: "",
      end: "",
      light_room: "r",
      zone_sensors: [],
    };
    expect(serializeBands([fresh])).toEqual([{ ...newBand(), light_room: "r", zone_sensors: [] }]);
    expect(serializeBands([{ ...fresh, light: null }])[0].light_room).toBeNull();
  });

  it("finds the active band and the values in force", () => {
    expect(activeBand(room())?.band.name).toBe("Sera");
    expect(activeBand(room({ active_band: null }))).toBeNull();
    expect(effectiveValues(room())).toMatchObject({ on_delay: 0, empty_wait: 90 });
    expect(effectiveValues(room({ effective: undefined }))).toEqual({
      on_delay: 0,
      empty_wait: 30,
      zone_wait: 150,
      zone_sensors: ["binary_sensor.salone_presenza"],
    });
    expect(roomValues({ on_delay: 5 })).toEqual({
      on_delay: 5,
      empty_wait: 30,
      zone_wait: 150,
      zone_sensors: [],
    });
  });
});

describe("band editor", () => {
  const bands = () => room().config.schedule!;
  const editor = async (over: Record<string, unknown> = {}) => {
    const el = document.createElement("br-schedule-editor");
    Object.assign(el, {
      ctx: ctxIt,
      bands: bands(),
      activeBand: "band-evening",
      rooms: ROOMS,
      roomId: "sub-kitchen",
      ...over,
    });
    const root = await mount(el);
    const events: Band[][] = [];
    el.addEventListener("bands-changed", (ev) => {
      events.push((ev as CustomEvent).detail.bands);
      el.bands = events.at(-1)!;
    });
    return { el, root, events };
  };

  it("lists the bands with their summary and the active marker", async () => {
    const { root } = await editor();
    const rows = [...root.querySelectorAll(".band")];
    expect(rows).toHaveLength(2);
    expect(text(rows[0])).toContain("Sera");
    expect(text(rows[0])).toContain("19:00–23:30 · attesa 1 min 30 s");
    expect(rows[0].querySelector(".active-marker")?.textContent).toContain("Attiva ora");
    expect(text(rows[1])).toContain("Fascia 2");
    expect(text(rows[1])).toContain(
      "Col buio (Tavolo) · Lun–Ven 17:00–23:00 · accensione 20 s · zona: nessuna",
    );
    expect(rows[1].querySelector(".active-marker")).toBeNull();
    expect(root.querySelector(".body")).toBeNull(); // saved bands start closed
  });

  it("edits the light condition and the room it is measured in", async () => {
    const { root, events } = await editor();
    (root.querySelectorAll(".band .toggle")[1] as HTMLButtonElement).click();
    await (root.host as HTMLElement & { updateComplete: Promise<boolean> }).updateComplete;
    const light = root.querySelector(".light-select") as HTMLSelectElement;
    expect(light.value).toBe("dark");
    expect([...light.options].map((o) => o.textContent!.trim())).toEqual([
      "Qualsiasi luce",
      "Con luce (chiaro)",
      "Col buio",
    ]);
    const roomSelect = root.querySelector(".room-select") as HTMLSelectElement;
    // This room is "questa stanza", not listed again.
    expect([...roomSelect.options].map((o) => o.textContent!.trim())).toEqual([
      "questa stanza",
      "Tavolo",
    ]);
    expect(roomSelect.value).toBe("sub-living");
    roomSelect.value = "";
    roomSelect.dispatchEvent(new Event("change"));
    expect(events.at(-1)![1].light_room).toBeNull();
    // The time window and days are shown, with the zone switch on and empty.
    expect(root.querySelectorAll('input[type="time"]')).toHaveLength(2);
    expect(text(root.querySelector(".zones")!)).toContain("in questa fascia niente zona");
    light.value = "";
    light.dispatchEvent(new Event("change"));
    expect(events.at(-1)![1]).toMatchObject({ light: null, light_room: null });
  });

  it("adds a band and shows what is missing", async () => {
    const { el, root, events } = await editor({ ctx, activeBand: null });
    (root.querySelector(".footer .btn") as HTMLButtonElement).click();
    await el.updateComplete;
    const added = events.at(-1)![2];
    expect(added.id).toBeUndefined();
    expect(timeOn(added)).toBe(false);
    const body = root.querySelector(".body")!;
    expect(body.querySelectorAll('input[type="time"]')).toHaveLength(0);
    // Turn on the time window: it gets a default.
    const timeSwitch = body.querySelector(".time br-switch") as BrSwitch;
    await timeSwitch.updateComplete;
    (timeSwitch.shadowRoot!.querySelector("button") as HTMLButtonElement).click();
    await el.updateComplete;
    expect(events.at(-1)![2]).toMatchObject({ start: "17:00", end: "23:00" });
    expect(text(root.querySelector(".errors")!)).toContain("Change at least one setting.");
    const onDelay = root.querySelector('.body input[data-key="on_delay"]') as HTMLInputElement;
    expect(onDelay.placeholder).toBe("room: 0");
    onDelay.value = "120";
    onDelay.dispatchEvent(new Event("input"));
    await el.updateComplete;
    expect(events.at(-1)![2].on_delay).toBe(120);
    expect(root.querySelector(".errors")).toBeNull();
  });

  it("turns the zone override on with a picker fallback", async () => {
    const { el, root, events } = await editor({ ctx, bands: [band()] });
    (root.querySelector(".band .toggle") as HTMLButtonElement).click();
    await el.updateComplete;
    const zoneSwitch = root.querySelector(".zones br-switch") as BrSwitch;
    await zoneSwitch.updateComplete;
    (zoneSwitch.shadowRoot!.querySelector("button") as HTMLButtonElement).click();
    await el.updateComplete;
    expect(events.at(-1)![0].zone_sensors).toEqual([]);
    const input = root.querySelector(".zone-text") as HTMLInputElement;
    input.value = "binary_sensor.a, binary_sensor.b";
    input.dispatchEvent(new Event("change"));
    expect(events.at(-1)![0].zone_sensors).toEqual(["binary_sensor.a", "binary_sensor.b"]);
  });

  it("disables adding at the maximum and shows a save error on its band", async () => {
    const eight = Array.from({ length: 8 }, (_, i) => ({ ...bands()[0], id: `b${i}` }));
    const { root } = await editor({
      ctx,
      bands: eight,
      saveError: { key: "schedule_invalid", bands: [3] },
    });
    expect((root.querySelector(".footer .btn") as HTMLButtonElement).disabled).toBe(true);
    const rows = root.querySelectorAll(".band");
    expect(rows[3].classList).toContain("error");
    expect(rows[3].textContent).toContain("The bands are not valid.");
  });
});

describe("tile with an active band", () => {
  it("shows the band and what it changes", async () => {
    const el = document.createElement("br-room-tile");
    Object.assign(el, {
      room: room({
        active_band: "band-cooktop",
        effective: { on_delay: 20, empty_wait: 30, zone_wait: 150, zone_sensors: [] },
      }),
      ctx: ctxIt,
    });
    const root = await mount(el);
    expect(text(root)).toContain(
      "Fascia: Fascia 2 · accensione 20 s · attesa 30 s · zona: nessuna",
    );
  });
});
