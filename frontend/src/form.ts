// Helpers that make ha-form speak the panel's language and split the room form.

import type { Localize } from "./localize";
import type { FormField } from "./types";

export interface FormCallbacks {
  computeLabel: (field: FormField) => string;
  computeHelper: (field: FormField) => string | undefined;
  computeError: (error: string, field?: FormField) => string;
  localizeValue: (key: string) => string;
}

/** Turn "learn_min_previous" into "Learn min previous" when there is no translation. */
export const humanize = (name: string): string => {
  const text = name.replaceAll("_", " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : name;
};

const translated = (t: Localize, key: string): string | undefined => {
  const text = t(key);
  return text === key ? undefined : text;
};

export const formCallbacks = (t: Localize): FormCallbacks => ({
  // Sections (type "expandable") have their title under "section.".
  computeLabel: (field) =>
    translated(t, field.type === "expandable" ? `section.${field.name}` : `field.${field.name}`) ??
    humanize(field.name),
  computeHelper: (field) => translated(t, `help.${field.name}`),
  // ha-form passes our error codes (name_taken, no_lights, ...).
  computeError: (error) => translated(t, `error.${error}`) ?? error,
  localizeValue: (key) => translated(t, `selector.${key}`) ?? key.split(".").pop() ?? key,
});

/** Field errors of a save, with "base" shown above the form. */
export const splitErrors = (errors: Record<string, string> | undefined) => {
  const { base, ...fields } = errors ?? {};
  return { base, fields };
};

/**
 * ha-form looks up the errors of a section's fields under the section's
 * name; the integration answers with flat field names. Move them there.
 */
export const nestErrors = (
  schema: FormField[],
  errors: Record<string, string>,
): Record<string, unknown> => {
  const out: Record<string, unknown> = { ...errors };
  for (const field of schema) {
    if (field.type !== "expandable" || !field.schema) continue;
    const inner: Record<string, string> = {};
    for (const sub of field.schema) {
      if (sub.name in errors) {
        inner[sub.name] = errors[sub.name];
        if (!field.flatten) delete out[sub.name];
      }
    }
    if (Object.keys(inner).length && !field.flatten) out[field.name] = inner;
  }
  return out;
};

export interface FieldGroup {
  key: string;
  icon: string;
  schema: FormField[];
}

/** Groups of the room form by field name, when the integration sends no sections. */
export const ROOM_GROUPS: { key: string; icon: string; fields: string[] }[] = [
  { key: "area", icon: "mdi:floor-plan", fields: ["name", "area"] },
  {
    key: "presence",
    icon: "mdi:motion-sensor",
    fields: ["presence_sensors", "on_delay"],
  },
  // Drawn by the editor itself (other zones), with these fields in an ha-form.
  { key: "neighbors", icon: "mdi:account-multiple-outline", fields: ["zone_sensors"] },
  { key: "lights", icon: "mdi:lightbulb-group-outline", fields: ["lights", "min_off_seconds"] },
  {
    key: "daylight",
    icon: "mdi:brightness-6",
    fields: [
      "illuminance_sensor",
      "other_lights",
      "only_when_dark",
      "dark_below",
      "bright_above",
      "off_when_bright",
      "on_when_dark",
      "bright_minutes",
    ],
  },
  {
    key: "brightness",
    icon: "mdi:brightness-percent",
    fields: ["brightness_min", "brightness_dark_lux", "brightness_full_lux"],
  },
  {
    key: "off",
    icon: "mdi:lightbulb-off-outline",
    fields: ["empty_wait", "zone_wait", "dim_percent", "dim_wait", "transition"],
  },
];

/**
 * The room form in cards. With sections from the integration the schema is
 * kept whole (ha-form draws them); otherwise fields are grouped by name, and
 * fields not listed go to an "other" group at the end.
 */
export const groupFields = (schema: FormField[]): FieldGroup[] => {
  if (schema.some((f) => f.type === "expandable"))
    return [{ key: "room", icon: "mdi:tune-variant", schema }];
  const listed = new Set(ROOM_GROUPS.flatMap((g) => g.fields));
  const groups: FieldGroup[] = ROOM_GROUPS.map((g) => ({
    key: g.key,
    icon: g.icon,
    schema: schema.filter((f) => g.fields.includes(f.name)),
  }));
  groups.push({
    key: "other",
    icon: "mdi:tune-variant",
    schema: schema.filter((f) => !listed.has(f.name)),
  });
  return groups.filter((g) => g.schema.length > 0);
};

/** Fields the editor draws itself: the nearby zones. */
export const NEIGHBOR_FIELDS = ["auto_neighbors", "neighbor_zones"];

/** Fields the editor draws itself: nearby zones and the other zones' lights. */
export const CUSTOM_FIELDS = [...NEIGHBOR_FIELDS, "auto_other_lights"];

/** The schema without some fields, also inside sections. */
export const withoutFields = (schema: FormField[], names: string[]): FormField[] =>
  schema
    .filter((f) => !names.includes(f.name))
    .map((f) => (f.schema ? { ...f, schema: withoutFields(f.schema, names) } : f));

/**
 * The groups of the room form with the "neighbors" group always present
 * (after "presence", or last), since the editor draws the nearby zones in it.
 */
export const zoneFormGroups = (schema: FormField[]): FieldGroup[] => {
  const groups = groupFields(withoutFields(schema, CUSTOM_FIELDS));
  if (groups.some((g) => g.key === "neighbors")) return groups;
  const neighbors: FieldGroup = {
    key: "neighbors",
    icon: "mdi:account-multiple-outline",
    schema: [],
  };
  const at = groups.findIndex((g) => g.key === "presence");
  if (at < 0) return [...groups, neighbors];
  return [...groups.slice(0, at + 1), neighbors, ...groups.slice(at + 1)];
};

/** Drop empty values (cleared fields), as the integration expects them missing. */
export const cleanData = (data: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(data).filter(
      ([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
    ),
  );
