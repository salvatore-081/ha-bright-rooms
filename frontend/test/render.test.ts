import { afterEach, describe, expect, it, vi } from "vitest";
import "../src/components/br-room-tile";
import "../src/components/br-entities-card";
import "../src/card/bright-rooms-card";
import "../src/panel/br-view-overview";
import { roomDetail, visibleRooms } from "../src/card/bright-rooms-card";
import { formatContext } from "../src/format";
import { localizer } from "../src/localize";
import type { HomeAssistant, Snapshot } from "../src/types";
import { NOW, hass, room, snapshot } from "./fixtures";

const ctx = formatContext(hass("en"), localizer("en"), NOW);

const mount = async <T extends HTMLElement & { updateComplete: Promise<boolean> }>(el: T) => {
  document.body.appendChild(el);
  await el.updateComplete;
  return el.shadowRoot!;
};

const text = (root: ShadowRoot | Element) => root.textContent!.replace(/\s+/g, " ");

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("room tile", () => {
  it("shows status, presence, ambient light, lights, countdown and last action", async () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    const el = document.createElement("br-room-tile");
    Object.assign(el, { room: room(), ctx });
    const root = await mount(el);
    const all = text(root);
    expect(all).toContain("Cucina");
    expect(all).toContain("Nobody here, waiting");
    expect(all).toContain("Empty, someone nearby");
    expect(all).toContain("Ambient light 35 lx Dark");
    expect(all).toContain("held");
    expect(all).toContain("Sensor reading 95 lx");
    expect(all).toContain("Tavolo On · 50 %");
    expect(all).toContain("Cappa Off");
    expect(all).toContain("Turned on: someone came in and it was dark · 5 minutes ago");
    expect(root.querySelector(".head")!.classList).toContain("tone-active");

    const bar = root.querySelector("br-lux-bar")!;
    await bar.updateComplete;
    expect(bar.darkBelow).toBe(40);
    expect(bar.brightAbove).toBe(80);
    expect(text(bar.shadowRoot!)).toContain("40");
    expect((bar.shadowRoot!.querySelector(".fill") as HTMLElement).style.width).toBe(
      `${(35 / 120) * 100}%`,
    );

    const countdown = root.querySelector("br-countdown")!;
    await countdown.updateComplete;
    expect(text(countdown.shadowRoot!)).toBe("Dims in 2:05");
  });

  it("emits set-enabled from the Automatic switch and open-room from the head", async () => {
    const el = document.createElement("br-room-tile");
    Object.assign(el, { room: room(), ctx });
    const root = await mount(el);
    const events: [string, unknown][] = [];
    for (const type of ["set-enabled", "open-room"])
      el.addEventListener(type, (ev) => events.push([type, (ev as CustomEvent).detail]));
    const sw = root.querySelector("br-switch")!;
    await sw.updateComplete;
    (sw.shadowRoot!.querySelector("button") as HTMLButtonElement).click();
    (root.querySelector(".open") as HTMLElement).click();
    expect(events).toEqual([
      ["set-enabled", { room: "sub-kitchen", enabled: false }],
      ["open-room", { room: "sub-kitchen" }],
    ]);
  });

  it("explains a room without a light sensor and without actions", async () => {
    const el = document.createElement("br-room-tile");
    const r = room({
      config: { ...room().config, illuminance_sensor: null },
      ambient: null,
      raw_lux: null,
      dark: null,
      held: false,
      deadline: null,
      last_action: null,
      status: "off",
    });
    Object.assign(el, { room: r, ctx, link: false });
    const root = await mount(el);
    const all = text(root);
    expect(all).toContain("no light sensor");
    expect(all).toContain("Nothing done yet");
    expect(root.querySelector("br-lux-bar")).toBeNull();
    expect(root.querySelector("br-countdown")).toBeNull();
    expect(root.querySelector(".open")!.getAttribute("role")).toBeNull();
  });
});

describe("overview", () => {
  it("shows a tile per room, or the way to add one", async () => {
    const el = document.createElement("br-view-overview");
    Object.assign(el, { snapshot: snapshot(), ctx });
    const root = await mount(el);
    expect(root.querySelectorAll("br-room-tile")).toHaveLength(2);
    el.snapshot = snapshot({ rooms: [] });
    await el.updateComplete;
    expect(text(root)).toContain("No rooms yet");
  });
});

describe("presence sensor settings", () => {
  it("uses the frontend's entities card and passes every hass to it", async () => {
    const created: Record<string, unknown>[] = [];
    const card = document.createElement("div") as HTMLElement & { hass?: unknown };
    (window as unknown as { loadCardHelpers: unknown }).loadCardHelpers = async () => ({
      createCardElement: (config: Record<string, unknown>) => {
        created.push(config);
        return card;
      },
    });
    const el = document.createElement("br-entities-card");
    const h1 = hass("en");
    Object.assign(el, { hass: h1, entities: ["number.a", "select.b"] });
    const root = await mount(el);
    await vi.waitFor(() => expect(root.contains(card)).toBe(true));
    expect(created).toEqual([
      { type: "entities", entities: ["number.a", "select.b"], state_color: false },
    ]);
    expect(card.hass).toBe(h1);
    const h2 = hass("en");
    el.hass = h2;
    await el.updateComplete;
    expect(card.hass).toBe(h2);
    delete (window as unknown as { loadCardHelpers?: unknown }).loadCardHelpers;
  });

  it("says so when the entities card cannot be loaded", async () => {
    const el = document.createElement("br-entities-card");
    Object.assign(el, { hass: hass("en"), entities: ["number.a"], unavailable: "Not available" });
    const root = await mount(el);
    await vi.waitFor(() => expect(text(root)).toContain("Not available"));
  });
});

describe("card", () => {
  const fakeHass = (snap: Snapshot): HomeAssistant => {
    const h = hass("en");
    h.connection = {
      subscribeMessage: async (cb: (s: Snapshot) => void, msg: unknown) => {
        expect(msg).toEqual({ type: "bright_rooms/subscribe" });
        cb(snap);
        return () => undefined;
      },
    } as unknown as HomeAssistant["connection"];
    return h;
  };

  it("lists the rooms with status, ambient light, lights and countdown", async () => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date"] });
    const el = document.createElement("bright-rooms-card");
    el.setConfig({ type: "custom:bright-rooms-card", title: "Luci" });
    el.hass = fakeHass(snapshot());
    const root = await mount(el);
    await vi.waitFor(() => expect(root.querySelectorAll(".room")).toHaveLength(2));
    const all = text(root);
    expect(all).toContain("Luci");
    expect(all).toContain("Cucina");
    expect(all).toContain("35 lx · 1 of 2 lights on");
    expect(all).toContain("150 lx · lights off");
    const rows = root.querySelectorAll(".room");
    expect(rows[0].classList).toContain("tone-active");
    expect(rows[1].classList).toContain("off");
    const countdown = rows[0].querySelector("br-countdown")!;
    await countdown.updateComplete;
    expect(text(countdown.shadowRoot!)).toBe("2:05");
    expect(countdown.getAttribute("title")).toBe("Dims in");
    expect(rows[1].querySelector("br-countdown")).toBeNull();
  });

  it("opens the room page of the panel on tap", async () => {
    const el = document.createElement("bright-rooms-card");
    el.setConfig({ type: "custom:bright-rooms-card", rooms: ["sub-living"] });
    el.hass = fakeHass(snapshot());
    const root = await mount(el);
    await vi.waitFor(() => expect(root.querySelectorAll(".room")).toHaveLength(1));
    let changed = false;
    window.addEventListener("location-changed", () => (changed = true), { once: true });
    (root.querySelector(".room") as HTMLElement).click();
    expect(location.pathname).toBe("/bright-rooms/rooms/sub-living");
    expect(changed).toBe(true);
  });

  it("says when Bright Rooms is not running", async () => {
    const el = document.createElement("bright-rooms-card");
    el.setConfig({ type: "custom:bright-rooms-card" });
    const h = hass("it");
    h.connection = {
      subscribeMessage: async () => {
        throw { code: "not_loaded", message: "Bright Rooms is not loaded" };
      },
    } as unknown as HomeAssistant["connection"];
    el.hass = h;
    const root = await mount(el);
    await vi.waitFor(() => expect(text(root)).toContain("Bright Rooms non è attivo"));
  });

  it("filters rooms and words the lights", () => {
    const snap = snapshot();
    expect(visibleRooms(snap, ["sub-living"]).map((r) => r.id)).toEqual(["sub-living"]);
    expect(visibleRooms(snap, []).map((r) => r.id)).toEqual(["sub-kitchen", "sub-living"]);
    expect(visibleRooms(undefined)).toEqual([]);
    const single = room({ lights: [room().lights[0]] });
    expect(roomDetail(single, ctx)).toBe("35 lx · light on");
  });

  it("is registered for the card picker", async () => {
    await import("../src/card");
    const cards = (window as unknown as { customCards: { type: string }[] }).customCards;
    expect(cards.filter((c) => c.type === "bright-rooms-card")).toHaveLength(1);
    expect(customElements.get("bright-rooms-card-editor")).toBeDefined();
  });
});
