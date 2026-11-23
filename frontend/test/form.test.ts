import { describe, expect, it } from "vitest";
import { cleanData, formCallbacks, groupFields, humanize, nestErrors } from "../src/form";
import { localizer } from "../src/localize";
import { parseContribution } from "../src/panel/br-room-editor";
import type { FormField } from "../src/types";

const field = (name: string): FormField => ({ name, selector: { number: {} } });

describe("form callbacks", () => {
  const cb = formCallbacks(localizer("it"));

  it("translates labels, helpers and errors", () => {
    expect(cb.computeLabel(field("dark_below"))).toBe("Buio sotto (lx)");
    expect(cb.computeHelper(field("zone_wait"))).toBe(
      "Attesa massima in più finché un sensore vicino è acceso.",
    );
    expect(cb.computeHelper(field("dark_below"))).toBeUndefined();
    expect(cb.computeError("no_lights")).toBe("Scegli almeno una luce.");
  });

  it("falls back to readable names and raw codes", () => {
    expect(cb.computeLabel(field("brand_new_option"))).toBe("Brand new option");
    expect(cb.computeLabel({ name: "daylight", type: "expandable", schema: [] })).toBe(
      "Luce del giorno",
    );
    expect(cb.computeError("weird_code")).toBe("weird_code");
    expect(cb.localizeValue("mode.options.fast")).toBe("fast");
    expect(humanize("")).toBe("");
  });
});

describe("room form", () => {
  it("groups the fields by name, the unknown ones last", () => {
    const groups = groupFields(
      ["area", "lights", "dark_below", "transition", "presence_sensors", "mystery"].map(field),
    );
    expect(groups.map((g) => [g.key, g.schema.map((f) => f.name)])).toEqual([
      ["area", ["area"]],
      ["presence", ["presence_sensors"]],
      ["lights", ["lights"]],
      ["daylight", ["dark_below"]],
      ["off", ["transition"]],
      ["other", ["mystery"]],
    ]);
  });

  it("keeps the integration's sections whole, with their errors nested", () => {
    const schema: FormField[] = [
      field("area"),
      { name: "off", type: "expandable", schema: [field("dim_percent"), field("dim_wait")] },
    ];
    expect(groupFields(schema)).toEqual([{ key: "room", icon: "mdi:tune-variant", schema }]);
    expect(nestErrors(schema, { area: "area_taken", dim_wait: "invalid" })).toEqual({
      area: "area_taken",
      off: { dim_wait: "invalid" },
    });
    const flat: FormField[] = [{ ...schema[1], flatten: true }];
    expect(nestErrors(flat, { dim_wait: "invalid" })).toEqual({ dim_wait: "invalid" });
  });

  it("drops cleared values before saving", () => {
    expect(
      cleanData({ area: "cucina", zone_sensors: [], illuminance_sensor: "", x: null, n: 0 }),
    ).toEqual({ area: "cucina", n: 0 });
  });

  it("reads a typed contribution", () => {
    expect(parseContribution("120")).toBe(120);
    expect(parseContribution(" 85,6 ")).toBe(86);
    expect(parseContribution("0")).toBe(0);
    expect(parseContribution("")).toBeNull();
    expect(parseContribution("-3")).toBeNull();
    expect(parseContribution("abc")).toBeNull();
  });
});
