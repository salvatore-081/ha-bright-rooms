// Dashboard card: the rooms in compact form; a tap opens the room in the panel.

import { element } from "../define";
import { LitElement, type PropertyValues, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import "../components/br-countdown";
import { errorCode, errorMessage, subscribeSnapshot } from "../api";
import {
  type FormatContext,
  ambientText,
  deadlineTemplate,
  formatContext,
  lightsOn,
  statusIcon,
  statusLabel,
  statusTone,
} from "../format";
import { type Localize, localizer } from "../localize";
import { BASE, navigate } from "../nav";
import { shared, tokens } from "../styles";
import type { HomeAssistant, RoomSnapshot, Snapshot } from "../types";
import { type AreaGroup, areaSummary, groupByArea } from "../zones";

export interface BrightRoomsCardConfig {
  type: string;
  title?: string;
  rooms?: string[];
}

/**
 * The light zones the card shows: all, or those chosen in the configuration,
 * by zone id or by room (area id), in snapshot order.
 */
export const visibleRooms = (snapshot: Snapshot | undefined, wanted?: string[]): RoomSnapshot[] => {
  if (!snapshot) return [];
  return wanted?.length
    ? snapshot.rooms.filter((r) => wanted.includes(r.id) || wanted.includes(r.area_id))
    : snapshot.rooms;
};

/** The choices of the card editor: each room, then its zones as "Room · Zone". */
export const cardChoices = (
  snapshot: Snapshot | undefined,
  areaNames: Record<string, string> = {},
) =>
  snapshot
    ? groupByArea(snapshot, areaNames).flatMap((g) => [
        { value: g.area.area_id, label: g.area.name },
        ...g.zones.map((z) => ({ value: z.id, label: `${g.area.name} · ${z.name}` })),
      ])
    : [];

/** The visible zones grouped by room. */
export const visibleGroups = (
  snapshot: Snapshot | undefined,
  wanted?: string[],
  areaNames: Record<string, string> = {},
): AreaGroup[] => {
  if (!snapshot) return [];
  const shown = new Set(visibleRooms(snapshot, wanted).map((z) => z.id));
  return groupByArea(snapshot, areaNames)
    .map((g) => ({ ...g, zones: g.zones.filter((z) => shown.has(z.id)) }))
    .filter((g) => g.zones.length > 0);
};

/** "Ambient 35 lx · 2 of 3 lights on". */
export const roomDetail = (room: RoomSnapshot, ctx: FormatContext): string => {
  const { t } = ctx;
  const on = lightsOn(room);
  const lights =
    on === 0
      ? t("card.lights_off")
      : room.lights.length === 1
        ? t("card.light_on")
        : t("card.lights_on", { n: on, total: room.lights.length });
  return `${ambientText(room, ctx)} · ${lights}`;
};

// Not installed (unknown_command), not set up (not_found) or not loaded (not_loaded).
const NOT_RUNNING = ["unknown_command", "not_found", "not_loaded"];

@element("bright-rooms-card")
export class BrightRoomsCard extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private _config!: BrightRoomsCardConfig;
  @state() private _snapshot?: Snapshot;
  @state() private _error?: string;
  @state() private _now = new Date();
  private _unsub?: Promise<() => void>;

  static getConfigElement() {
    return document.createElement("bright-rooms-card-editor");
  }

  static getStubConfig(): Partial<BrightRoomsCardConfig> {
    return {};
  }

  setConfig(config: BrightRoomsCardConfig) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { ...config };
  }

  getCardSize() {
    const groups = visibleGroups(this._snapshot, this._config?.rooms).length;
    return (this._config?.title ? 1 : 0) + groups + (this._rooms().length || 3);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: this.getCardSize() };
  }

  static styles = [
    tokens,
    shared,
    css`
      ha-card {
        overflow: hidden;
        height: 100%;
      }
      .header {
        padding: 12px 16px 4px;
        font-weight: 500;
        font-size: 1rem;
      }
      .rooms {
        padding: 4px 0 8px;
      }
      .area + .area {
        border-top: 1px solid var(--br-border);
        margin-top: 4px;
        padding-top: 4px;
      }
      .area-head {
        display: flex;
        align-items: baseline;
        gap: 8px;
        padding: 8px 16px 2px;
      }
      .area-name {
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--br-muted);
      }
      .area-summary {
        flex: 1;
        text-align: right;
        font-size: 0.8rem;
        color: var(--br-muted);
      }
      .room {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 16px;
        cursor: pointer;
      }
      .room:hover {
        background: color-mix(in srgb, var(--br-text) 4%, transparent);
      }
      .room:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: -2px;
      }
      .room .icon {
        flex: none;
        color: var(--tone);
      }
      .room .text {
        flex: 1;
        min-width: 0;
      }
      .room .rname {
        font-weight: 500;
        font-size: 0.95rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .room .detail {
        color: var(--br-muted);
        font-size: 0.8rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .room .countdown {
        flex: none;
        color: var(--tone);
        font-size: 0.85rem;
        font-weight: 500;
      }
      .room.off .rname,
      .room.off .detail {
        opacity: 0.6;
      }
      .message {
        padding: 16px;
        color: var(--br-muted);
      }
    `,
  ];

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsub?.then((u) => u()).catch(() => undefined);
    this._unsub = undefined;
  }

  protected willUpdate(_changed: PropertyValues) {
    if (!this.hass || !this._config || this._unsub || !this.isConnected) return;
    this._unsub = subscribeSnapshot(this.hass, (snap) => {
      this._snapshot = snap;
      this._error = undefined;
      this._now = new Date();
    });
    // No retry on failure: a user who is not an administrator would retry on every state change.
    this._unsub.catch((err) => {
      const code = errorCode(err);
      this._error =
        code === "unauthorized"
          ? "unauthorized"
          : code && NOT_RUNNING.includes(code)
            ? "not_running"
            : errorMessage(err);
    });
  }

  private get _t(): Localize {
    return localizer(this.hass?.locale?.language || this.hass?.language);
  }

  private _rooms(): RoomSnapshot[] {
    return visibleRooms(this._snapshot, this._config?.rooms);
  }

  render() {
    if (!this._config || !this.hass) return nothing;
    const t = this._t;
    let body;
    if (this._error === "unauthorized" || this._error === "not_running")
      body = html`<div class="message">${t(`card.${this._error}`)}</div>`;
    else if (this._error) body = html`<div class="message">${this._error}</div>`;
    else if (!this._snapshot) body = html`<div class="message">${t("card.loading")}</div>`;
    else body = this._content(formatContext(this.hass, t, this._now));
    return html`<ha-card>
      ${this._config.title ? html`<div class="header">${this._config.title}</div>` : nothing}
      ${body}
    </ha-card>`;
  }

  private _content(ctx: FormatContext) {
    const { t } = ctx;
    const areaNames = Object.fromEntries(
      Object.values(this.hass.areas ?? {}).map((a) => [a.area_id, a.name]),
    );
    const groups = visibleGroups(this._snapshot, this._config?.rooms, areaNames);
    if (!groups.length) return html`<div class="message">${t("card.no_rooms")}</div>`;
    return html`<div class="rooms">
      ${groups.map(
        (group) =>
          html`<div class="area">
            <div class="area-head">
              <span class="area-name">${group.area.name}</span>
              <span class="area-summary">${areaSummary(group, t)}</span>
            </div>
            ${group.zones.map((room) => this._zone(room, ctx))}
          </div>`,
      )}
    </div>`;
  }

  private _zone(room: RoomSnapshot, ctx: FormatContext) {
    const { t } = ctx;
    const template = deadlineTemplate(room, t);
    return html`<div
      class="room tone-${statusTone(room.status)} ${room.enabled ? "" : "off"}"
      role="link"
      tabindex="0"
      @click=${() => this._open(room)}
      @keydown=${(ev: KeyboardEvent) => {
        if (ev.key === "Enter") this._open(room);
      }}
    >
      <ha-icon
        class="icon"
        .icon=${statusIcon(room.status)}
        title=${statusLabel(room.status, t)}
      ></ha-icon>
      <div class="text">
        <div class="rname">${room.name}</div>
        <div class="detail">${roomDetail(room, ctx)}</div>
      </div>
      ${
        template && room.deadline
          ? html`<br-countdown
              class="countdown"
              .deadline=${room.deadline}
              .template=${"{time}"}
              title=${template.replaceAll("{time}", "").trim()}
            ></br-countdown>`
          : nothing
      }
    </div>`;
  }

  private _open(room: RoomSnapshot) {
    navigate(`${BASE}/rooms/${room.id}`);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "bright-rooms-card": BrightRoomsCard;
  }
}
