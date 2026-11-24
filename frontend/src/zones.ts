// Rooms (Home Assistant areas) and their light zones: grouping and names.
// The card uses this module too: its strings stay under card. (vite.card.config.ts).

import type { Localize } from "./localize";
import type { AreaSnapshot, HomeAssistant, RoomSnapshot, Snapshot } from "./types";

export interface AreaGroup {
  area: AreaSnapshot;
  zones: RoomSnapshot[];
}

/** A light zone has its lights on (or is about to turn them off). */
export const zoneLit = (zone: RoomSnapshot) =>
  zone.status === "on" || zone.status === "waiting" || zone.status === "dimmed";

/**
 * The zones grouped by room, in the snapshot's order. Without `areas` (an
 * older integration) the rooms are made from the zones' area ids, named from
 * `areaNames` when given. Zones missing from every area end in their own group.
 */
export const groupByArea = (
  snapshot: Snapshot,
  areaNames: Record<string, string> = {},
): AreaGroup[] => {
  const byId = new Map(snapshot.rooms.map((z) => [z.id, z]));
  const areas =
    snapshot.areas ??
    [...new Set(snapshot.rooms.map((z) => z.area_id))]
      .map((areaId) => {
        const zones = snapshot.rooms.filter((z) => z.area_id === areaId);
        return {
          area_id: areaId,
          name: areaNames[areaId] ?? areaId,
          zone_ids: zones.map((z) => z.id),
          enabled: zones.every((z) => z.enabled),
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  const groups = areas.map((area) => ({
    area,
    zones: area.zone_ids.map((id) => byId.get(id)).filter((z): z is RoomSnapshot => !!z),
  }));
  const placed = new Set(groups.flatMap((g) => g.zones.map((z) => z.id)));
  const rest = snapshot.rooms.filter((z) => !placed.has(z.id));
  for (const zone of rest) {
    let group = groups.find((g) => g.area.area_id === zone.area_id);
    if (!group) {
      group = {
        area: {
          area_id: zone.area_id,
          name: areaNames[zone.area_id] ?? zone.area_id,
          zone_ids: [],
          enabled: zone.enabled,
        },
        zones: [],
      };
      groups.push(group);
    }
    group.zones.push(zone);
  }
  return groups.filter((g) => g.zones.length > 0);
};

/** "Cucina · Tavolo"; just "Tavolo" when the zone is named like its room. */
export const zoneLabel = (snapshot: Snapshot, zoneId: string): string => {
  const zone = snapshot.rooms.find((z) => z.id === zoneId);
  if (!zone) return zoneId;
  const area = snapshot.areas?.find((a) => a.area_id === zone.area_id);
  if (!area || area.name.toLowerCase() === zone.name.toLowerCase()) return zone.name;
  return `${area.name} · ${zone.name}`;
};

/** The labels of every zone, by id. */
export const zoneLabels = (snapshot: Snapshot): Record<string, string> =>
  Object.fromEntries(snapshot.rooms.map((z) => [z.id, zoneLabel(snapshot, z.id)]));

/** "2 of 3 zones on", "1 zone, on", "lights off". */
export const areaSummary = (group: AreaGroup, t: Localize): string => {
  const lit = group.zones.filter(zoneLit).length;
  if (lit === 0) return t("card.area_off");
  return t("card.area_lit", { n: lit, total: group.zones.length });
};

/** The friendly name of an entity, or its id. */
export const entityName = (hass: HomeAssistant | undefined, entityId: string): string => {
  const name = hass?.states[entityId]?.attributes?.friendly_name;
  return typeof name === "string" && name ? name : entityId;
};
