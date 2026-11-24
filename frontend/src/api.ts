// WebSocket commands of the integration (custom_components/bright_rooms/websocket_api.py).

import type { HomeAssistant, SaveResult, SchemaResponse, Snapshot } from "./types";

export const fetchSnapshot = (hass: HomeAssistant) =>
  hass.callWS<Snapshot>({ type: "bright_rooms/rooms" });

/** Calls `callback` with a snapshot now and after every change; resolves to the unsubscribe. */
export const subscribeSnapshot = (hass: HomeAssistant, callback: (snapshot: Snapshot) => void) =>
  hass.connection.subscribeMessage<Snapshot>(callback, { type: "bright_rooms/subscribe" });

/** The room form (of `roomId`, or empty for a new room) and the settings form. */
export const fetchSchema = (hass: HomeAssistant, roomId?: string) =>
  hass.callWS<SchemaResponse>({
    type: "bright_rooms/schema",
    ...(roomId ? { room_id: roomId } : {}),
  });

export const saveRoom = (hass: HomeAssistant, data: Record<string, unknown>, roomId?: string) =>
  hass.callWS<SaveResult>({
    type: "bright_rooms/room/save",
    data,
    ...(roomId ? { room_id: roomId } : {}),
  });

export const deleteRoom = (hass: HomeAssistant, roomId: string) =>
  hass.callWS<null>({ type: "bright_rooms/room/delete", room_id: roomId });

export const setRoomEnabled = (hass: HomeAssistant, roomId: string, enabled: boolean) =>
  hass.callWS<null>({ type: "bright_rooms/room/set_enabled", room_id: roomId, enabled });

/** Switch Automatic for every light zone of a room (area). */
export const setAreaEnabled = (hass: HomeAssistant, areaId: string, enabled: boolean) =>
  hass.callWS<null>({ type: "bright_rooms/area/set_enabled", area_id: areaId, enabled });

/** Set a light's contribution by hand; null forgets it, so it is learned again. */
export const setContribution = (
  hass: HomeAssistant,
  roomId: string,
  entityId: string,
  value: number | null,
) =>
  hass.callWS<null>({
    type: "bright_rooms/contribution/set",
    room_id: roomId,
    entity_id: entityId,
    value,
  });

export const saveSettings = (hass: HomeAssistant, data: Record<string, unknown>) =>
  hass.callWS<SaveResult>({ type: "bright_rooms/settings/save", data });

/** The message of an error thrown by callWS. */
export const errorMessage = (err: unknown): string => {
  if (err && typeof err === "object") {
    const e = err as { message?: string; code?: string };
    return e.message || e.code || String(err);
  }
  return String(err);
};

export const errorCode = (err: unknown): string | undefined =>
  err && typeof err === "object" ? (err as { code?: string }).code : undefined;
