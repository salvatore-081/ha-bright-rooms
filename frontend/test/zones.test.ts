import { afterEach, describe, expect, it, vi } from "vitest";
import type { HassEntity } from "home-assistant-js-websocket";
import "../src/panel/bright-rooms-panel";
import "../src/panel/br-room-editor";
import "../src/card/bright-rooms-card";
import type { BrSwitch } from "../src/components/br-switch";
import { cardChoices, visibleGroups, visibleRooms } from "../src/card/bright-rooms-card";
import { formatContext } from "../src/format";
import { NEIGHBOR_FIELDS, withoutFields, zoneFormGroups } from "../src/form";
import { localizer } from "../src/localize";
import type { FormField, HomeAssistant, Snapshot } from "../src/types";
import { areaSummary, entityName, groupByArea, zoneLabel, zoneLabels, zoneLit } from "../src/zones";
import { NOW, hass, light, room, snapshot } from "./fixtures";

const en = localizer("en");
const it_ = localizer("it");
const ctxIt = formatContext(hass("it"), it_, NOW);

/** Cucina with two zones (Piano cottura, Tavolo) and Salone with one. */
const house = (): Snapshot => {
  const base = snapshot();
  const cooktop = room({
    id: "sub-cooktop",
    name: "Piano cottura",
    area_id: "cucina",
    status: "on",
    lights: [light({ entity_id: "light.cappa", name: "Cappa" })],
  });
  const table = room({ id: "sub-table", name: "Tavolo", area_id: "cucina", status: "off" });
  return {
    ...base,
    rooms: [cooktop, base.rooms[1], table],
    areas: [
      {
        area_id: "cucina",
        name: "Cucina",
        zone_ids: ["sub-cooktop", "sub-table"],
        enabled: true,
      },
      { area_id: "salone", name: "Salone", zone_ids: ["sub-living"], enabled: false },
    ],
  };
};

const mount = async <T extends HTMLElement & { updateComplete: Promise<boolean> }>(el: T) => {
  document.body.appendChild(el);
  await el.updateComplete;
  return el.shadowRoot!;
};

const text = (e: Element | ShadowRoot) => e.textContent!.replace(/\s+/g, " ");

afterEach(() => {
  document.body.innerHTML = "";
});

describe("rooms and zones", () => {
  it("groups the zones by room, in the order of areas", () => {
    const groups = groupByArea(house());
    expect(groups.map((g) => [g.area.name, g.zones.map((z) => z.name)])).toEqual([
      ["Cucina", ["Piano cottura", "Tavolo"]],
      ["Salone", ["Salone"]],
    ]);
  });

  it("makes rooms from the zones' areas without `areas`, and keeps stray zones", () => {
    const snap = { ...house(), areas: undefined };
    const groups = groupByArea(snap, { cucina: "Cucina", salone: "Salone" });
    expect(groups.map((g) => [g.area.name, g.zones.length, g.area.enabled])).toEqual([
      ["Cucina", 2, true],
      ["Salone", 1, false],
    ]);
    const stray = { ...house(), areas: [house().areas![0]] };
    expect(groupByArea(stray).map((g) => g.area.area_id)).toEqual(["cucina", "salone"]);
  });

  it("names zones as Room · Zone and sums up a room", () => {
    const snap = house();
    expect(zoneLabel(snap, "sub-table")).toBe("Cucina · Tavolo");
    expect(zoneLabel(snap, "sub-living")).toBe("Salone");
    expect(zoneLabel(snap, "gone")).toBe("gone");
    expect(zoneLabels(snap)["sub-cooktop"]).toBe("Cucina · Piano cottura");
    const [kitchen, living] = groupByArea(snap);
    expect(zoneLit(kitchen.zones[0])).toBe(true);
    expect(areaSummary(kitchen, it_)).toBe("1 zone accese su 2");
    expect(areaSummary(living, en)).toBe("lights off");
  });

  it("uses friendly names of entities", () => {
    const h = hass("it");
    h.states = {
      "binary_sensor.a": {
        attributes: { friendly_name: "Presenza tavolo" },
      } as unknown as HassEntity,
    };
    expect(entityName(h, "binary_sensor.a")).toBe("Presenza tavolo");
    expect(entityName(h, "binary_sensor.b")).toBe("binary_sensor.b");
  });

  it("keeps the neighbour fields out of ha-form and always has their group", () => {
    const schema: FormField[] = [
      { name: "presence_sensors" },
      { name: "auto_neighbors" },
      { name: "neighbor_zones" },
      { name: "zone_sensors" },
      { name: "x", type: "expandable", schema: [{ name: "neighbor_zones" }, { name: "y" }] },
    ];
    expect(withoutFields(schema, NEIGHBOR_FIELDS).map((f) => f.name)).toEqual([
      "presence_sensors",
      "zone_sensors",
      "x",
    ]);
    expect(withoutFields(schema, NEIGHBOR_FIELDS)[2].schema).toEqual([{ name: "y" }]);
    const groups = zoneFormGroups([{ name: "presence_sensors" }, { name: "zone_sensors" }]);
    expect(groups.map((g) => [g.key, g.schema.map((f) => f.name)])).toEqual([
      ["presence", ["presence_sensors"]],
      ["neighbors", ["zone_sensors"]],
    ]);
    expect(
      zoneFormGroups([{ name: "presence_sensors" }, { name: "lights" }]).map((g) => g.key),
    ).toEqual(["presence", "neighbors", "lights"]);
  });

  it("keeps the other zones' lights switch out of ha-form", () => {
    const groups = zoneFormGroups([
      { name: "illuminance_sensor" },
      { name: "auto_other_lights" },
      { name: "other_lights" },
    ]);
    expect(groups.map((g) => [g.key, g.schema.map((f) => f.name)])).toEqual([
      ["daylight", ["illuminance_sensor", "other_lights"]],
      ["neighbors", []],
    ]);
  });
});

describe("overview", () => {
  it("shows each room with its zones and switches a whole room", async () => {
    const calls: Record<string, unknown>[] = [];
    const h = hass("it") as HomeAssistant;
    h.callWS = (async (msg: Record<string, unknown>) => {
      calls.push(msg);
      return null;
    }) as HomeAssistant["callWS"];
    h.connection = {
      subscribeMessage: async (cb: (s: Snapshot) => void) => {
        cb(house());
        return () => undefined;
      },
    } as unknown as HomeAssistant["connection"];
    const panel = document.createElement("bright-rooms-panel");
    Object.assign(panel, { hass: h, route: { prefix: "/bright-rooms", path: "" } });
    const root = await mount(panel);
    await vi.waitFor(() => expect(root.querySelector("br-view-overview")).not.toBeNull());
    const overview = root.querySelector("br-view-overview")!;
    await overview.updateComplete;
    const areas = [...overview.shadowRoot!.querySelectorAll("section.area")];
    expect(areas.map((a) => a.querySelector("h2")!.textContent)).toEqual(["Cucina", "Salone"]);
    expect(text(areas[0])).toContain("1 zone accese su 2");
    expect(areas[0].querySelectorAll("br-room-tile")).toHaveLength(2);
    const sw = areas[1].querySelector("br-switch") as BrSwitch;
    await sw.updateComplete;
    expect(sw.checked).toBe(false);
    (sw.shadowRoot!.querySelector("button") as HTMLButtonElement).click();
    await vi.waitFor(() =>
      expect(calls).toContainEqual({
        type: "bright_rooms/area/set_enabled",
        area_id: "salone",
        enabled: true,
      }),
    );
  });
});

describe("zone editor: nearby presence", () => {
  const editor = async (values: Record<string, unknown>) => {
    const h = hass("it");
    h.states = {
      "binary_sensor.cottura": {
        attributes: { friendly_name: "Presenza cottura" },
      } as unknown as HassEntity,
    };
    h.callWS = (async () => ({
      schema: [{ name: "area" }, { name: "presence_sensors" }, { name: "zone_sensors" }],
      values,
      settings_schema: [],
      settings: {},
    })) as HomeAssistant["callWS"];
    const snap = house();
    snap.rooms[2] = {
      ...snap.rooms[2],
      neighbors: {
        auto: ["binary_sensor.cottura"],
        manual_zones: [],
        sensors: [],
        effective: ["binary_sensor.cottura"],
      },
    };
    const el = document.createElement("br-room-editor");
    Object.assign(el, {
      hass: h,
      snapshot: snap,
      ctx: ctxIt,
      roomId: "sub-table",
      formReady: true,
    });
    const root = await mount(el);
    await vi.waitFor(() => expect(root.querySelector(".neighbors-custom")).not.toBeNull());
    return { el, root };
  };

  it("lists the other zones of the room, the zones of other rooms and the sensors in use", async () => {
    const { root } = await editor({ area: "cucina", auto_neighbors: true, neighbor_zones: [] });
    const box = root.querySelector(".neighbors-custom")!;
    expect(root.querySelector(".section.neighbors h2")!.textContent).toContain("Presenze vicine");
    expect(text(box)).toContain("Le altre zone di questa stanza");
    expect(box.querySelector(".auto-list")!.textContent!.trim()).toBe("Piano cottura");
    const chips = [...box.querySelectorAll(".zone-toggle")];
    expect(chips.map((c) => c.textContent!.trim())).toEqual(["Salone"]);
    expect(chips[0].getAttribute("aria-pressed")).toBe("false");
    expect(text(box)).toContain("In uso: Presenza cottura");
    expect((box.querySelector(".auto-neighbors") as BrSwitch).checked).toBe(true);
  });

  it("switches auto neighbours off and picks a zone of another room", async () => {
    const { el, root } = await editor({
      area: "cucina",
      auto_neighbors: true,
      neighbor_zones: ["sub-gone"],
    });
    const box = root.querySelector(".neighbors-custom")!;
    const sw = box.querySelector(".auto-neighbors") as BrSwitch;
    await sw.updateComplete;
    (sw.shadowRoot!.querySelector("button") as HTMLButtonElement).click();
    const chips = [...box.querySelectorAll(".zone-toggle")] as HTMLButtonElement[];
    expect(chips.map((c) => c.textContent!.trim())).toEqual(["Salone", "Zona eliminata"]);
    chips[0].click();
    await el.updateComplete;
    const data = (el as unknown as { _data: Record<string, unknown> })._data;
    expect(data.auto_neighbors).toBe(false);
    expect(data.neighbor_zones).toEqual(["sub-gone", "sub-living"]);
    expect(root.querySelector(".neighbors-custom .zone-toggle")!.getAttribute("aria-pressed")).toBe(
      "true",
    );
  });
});

describe("card by room", () => {
  it("filters by zone or by room and groups the zones", () => {
    const snap = house();
    expect(visibleRooms(snap, ["cucina"]).map((z) => z.id)).toEqual(["sub-cooktop", "sub-table"]);
    expect(visibleGroups(snap, ["sub-living", "sub-table"]).map((g) => g.area.name)).toEqual([
      "Cucina",
      "Salone",
    ]);
    expect(cardChoices(snap).map((c) => c.label)).toEqual([
      "Cucina",
      "Cucina · Piano cottura",
      "Cucina · Tavolo",
      "Salone",
      "Salone · Salone",
    ]);
  });

  it("draws a header per room with its zones under it", async () => {
    const el = document.createElement("bright-rooms-card");
    el.setConfig({ type: "custom:bright-rooms-card" });
    const h = hass("it");
    h.connection = {
      subscribeMessage: async (cb: (s: Snapshot) => void) => {
        cb(house());
        return () => undefined;
      },
    } as unknown as HomeAssistant["connection"];
    el.hass = h;
    const root = await mount(el);
    await vi.waitFor(() => expect(root.querySelectorAll(".area")).toHaveLength(2));
    const [kitchen, living] = [...root.querySelectorAll(".area")];
    expect(kitchen.querySelector(".area-name")!.textContent).toBe("Cucina");
    expect(text(kitchen.querySelector(".area-summary")!)).toBe("1 zone accese su 2");
    expect([...kitchen.querySelectorAll(".rname")].map((n) => n.textContent)).toEqual([
      "Piano cottura",
      "Tavolo",
    ]);
    expect(living.querySelectorAll(".room")).toHaveLength(1);
  });
});
