// Rooms tab: the rooms, to switch on or off, edit, add or delete.

import { element } from "../define";
import { LitElement, css, html } from "lit";
import { property } from "lit/decorators.js";
import { live } from "lit/directives/live.js";
import "../components/br-switch";
import { deleteRoom, errorMessage } from "../api";
import { confirmDialog } from "../components/br-confirm";
import { type FormatContext, statusIcon, statusLabel, statusTone } from "../format";
import { navigate, notify, panelPath } from "../nav";
import { shared, tokens } from "../styles";
import type { HomeAssistant, RoomSnapshot, Snapshot } from "../types";

/** Ask to delete a room, then delete it; resolves to true when deleted. */
export const confirmDelete = async (
  host: LitElement,
  hass: HomeAssistant,
  room: { id: string; name: string },
  ctx: FormatContext,
): Promise<boolean> => {
  const { t } = ctx;
  const ok = await confirmDialog(host.renderRoot as ShadowRoot, {
    title: t("confirm.delete_title", { room: room.name }),
    text: t("confirm.delete_text"),
    confirm: t("common.delete"),
    cancel: t("common.cancel"),
    destructive: true,
  });
  if (!ok) return false;
  try {
    await deleteRoom(hass, room.id);
    notify(host, t("toast.room_deleted", { room: room.name }));
    return true;
  } catch (err) {
    notify(host, errorMessage(err));
    return false;
  }
};

@element("br-view-rooms")
export class BrViewRooms extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ attribute: false }) snapshot!: Snapshot;
  @property({ attribute: false }) ctx!: FormatContext;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
        max-width: 900px;
        margin: 0 auto;
      }
      .intro {
        display: flex;
        align-items: center;
        gap: 16px;
        flex-wrap: wrap;
        margin: 0 4px 16px;
      }
      .intro p {
        flex: 1;
        min-width: 240px;
        margin: 0;
        color: var(--br-muted);
        line-height: 1.5;
      }
      ul {
        list-style: none;
        margin: 0;
        padding: 0;
      }
      li {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 8px 10px 16px;
      }
      li + li {
        border-top: 1px solid var(--br-border);
      }
      .info {
        flex: 1;
        min-width: 0;
        cursor: pointer;
      }
      .name {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-weight: 500;
      }
      .summary {
        margin-top: 2px;
        font-size: 0.85rem;
        color: var(--br-muted);
      }
      .summary span + span::before {
        content: " · ";
      }
      .off .name,
      .off .summary {
        opacity: 0.6;
      }
      @media (max-width: 600px) {
        .delete {
          display: none;
        }
      }
    `,
  ];

  render() {
    const { t } = this.ctx;
    const rooms = this.snapshot.rooms;
    return html`
      <div class="intro">
        <p>${t("rooms.intro")}</p>
        <button class="btn filled" @click=${() => navigate(panelPath("/rooms/new"))}>
          <ha-icon icon="mdi:plus"></ha-icon>${t("rooms.add")}
        </button>
      </div>
      ${
        rooms.length
          ? html`<div class="card">
              <ul>
                ${rooms.map((room) => this._row(room))}
              </ul>
            </div>`
          : html`<div class="card empty-state">
              <ha-icon icon="mdi:floor-plan"></ha-icon>${t("overview.no_rooms")}
            </div>`
      }
    `;
  }

  private _row(room: RoomSnapshot) {
    const { t } = this.ctx;
    const c = room.config;
    const sensor = c.illuminance_sensor ? t("rooms.light_sensor") : t("rooms.no_light_sensor");
    return html`<li class=${room.enabled ? "" : "off"}>
      <div class="info" @click=${() => this._edit(room)}>
        <div class="name">
          ${room.name}
          <span class="chip tone-${statusTone(room.status)}"
            ><ha-icon .icon=${statusIcon(room.status)}></ha-icon
            >${statusLabel(room.status, t)}</span
          >
        </div>
        <div class="summary">
          <span>${t("rooms.sensors", { n: c.presence_sensors?.length ?? 0 })}</span
          ><span>${t("rooms.lights", { n: room.lights.length })}</span><span>${sensor}</span>
        </div>
      </div>
      <br-switch
        .checked=${live(room.enabled)}
        .label=${t("room.automatic_for", { room: room.name })}
        @change=${(ev: CustomEvent<{ checked: boolean }>) => this._enable(ev, room)}
      ></br-switch>
      <button
        class="icon-btn"
        aria-label=${t("rooms.edit", { room: room.name })}
        title=${t("rooms.edit", { room: room.name })}
        @click=${() => this._edit(room)}
      >
        <ha-icon icon="mdi:pencil-outline"></ha-icon>
      </button>
      <button
        class="icon-btn delete"
        aria-label=${t("rooms.delete", { room: room.name })}
        title=${t("rooms.delete", { room: room.name })}
        @click=${() => confirmDelete(this, this.hass, room, this.ctx)}
      >
        <ha-icon icon="mdi:delete-outline"></ha-icon>
      </button>
    </li>`;
  }

  private _edit(room: RoomSnapshot) {
    navigate(panelPath(`/rooms/${room.id}`));
  }

  private _enable(ev: CustomEvent<{ checked: boolean }>, room: RoomSnapshot) {
    ev.stopPropagation();
    this.dispatchEvent(
      new CustomEvent("set-enabled", {
        detail: { room: room.id, enabled: ev.detail.checked },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-view-rooms": BrViewRooms;
  }
}
