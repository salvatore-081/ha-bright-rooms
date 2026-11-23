// One room: status, presence, ambient light, lights, countdown, last action, Automatic switch.

import { element } from "../define";
import { LitElement, css, html, nothing } from "lit";
import { property } from "lit/decorators.js";
import { live } from "lit/directives/live.js";
import "./br-countdown";
import "./br-lux-bar";
import "./br-switch";
import {
  type FormatContext,
  LAST_ACTION_ICONS,
  ambientText,
  darkText,
  deadlineTemplate,
  formatAgo,
  formatLux,
  isOn,
  lastActionText,
  lightText,
  occupancyText,
  statusIcon,
  statusLabel,
  statusTone,
} from "../format";
import { activeBand, bandName, effectiveWaits, formatSeconds } from "../schedule";
import { shared, tokens } from "../styles";
import type { LightSnapshot, RoomSnapshot } from "../types";

const occupancyIcon = (room: RoomSnapshot) =>
  room.occupied === null
    ? "mdi:account-question-outline"
    : room.occupied
      ? "mdi:account"
      : room.zone_occupied
        ? "mdi:account-arrow-right-outline"
        : "mdi:account-off-outline";

const lightIcon = (light: LightSnapshot) =>
  light.state === "on"
    ? "mdi:lightbulb-on"
    : light.state === "off"
      ? "mdi:lightbulb-outline"
      : "mdi:lightbulb-question-outline";

@element("br-room-tile")
export class BrRoomTile extends LitElement {
  @property({ attribute: false }) room!: RoomSnapshot;
  @property({ attribute: false }) ctx!: FormatContext;
  /** The head opens the room page (false on the room page itself). */
  @property({ type: Boolean }) link = true;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
      }
      .card {
        display: flex;
        flex-direction: column;
        height: 100%;
        box-sizing: border-box;
      }
      .head {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 14px 16px 0;
        border-radius: var(--br-radius) var(--br-radius) 0 0;
      }
      .open {
        flex: 1;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 12px;
        border-radius: 8px;
      }
      .head.link .open {
        cursor: pointer;
      }
      .open:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: -2px;
      }
      .icon {
        flex: none;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        border-radius: 50%;
        color: var(--tone);
        background: color-mix(in srgb, var(--tone) 14%, transparent);
      }
      .title {
        flex: 1;
        min-width: 0;
      }
      .name {
        font-weight: 500;
        font-size: 1.05rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .status {
        font-size: 0.85rem;
        color: var(--tone);
      }
      .auto {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 2px;
        font-size: 0.7rem;
        color: var(--br-muted);
      }
      .body {
        flex: 1;
        display: grid;
        gap: 12px;
        padding: 12px 16px 14px;
      }
      .line {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-size: 0.9rem;
      }
      .line > ha-icon {
        --mdc-icon-size: 18px;
        color: var(--br-muted);
      }
      .ambient {
        display: grid;
        gap: 6px;
      }
      .ambient .value {
        font-weight: 500;
        font-variant-numeric: tabular-nums;
      }
      .ambient .raw {
        color: var(--br-muted);
        font-size: 0.85rem;
      }
      .lights {
        display: grid;
        gap: 4px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .lights li {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.9rem;
      }
      .lights ha-icon {
        --mdc-icon-size: 18px;
        color: var(--br-off);
      }
      .lights li.on ha-icon {
        color: var(--br-light);
      }
      .lights .lname {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .lights .lstate {
        color: var(--br-muted);
        white-space: nowrap;
        font-variant-numeric: tabular-nums;
      }
      .facts {
        display: grid;
        gap: 4px;
        font-size: 0.85rem;
        color: var(--br-muted);
      }
      .facts ha-icon {
        --mdc-icon-size: 16px;
        margin-right: 6px;
        vertical-align: -2px;
      }
      .countdown {
        color: var(--br-text);
        font-weight: 500;
      }
      .wait.band {
        color: var(--br-text);
      }
      .last.failed {
        color: var(--br-warning);
        font-weight: 500;
      }
    `,
  ];

  render() {
    const r = this.room;
    const { t } = this.ctx;
    const tone = statusTone(r.status);
    const template = deadlineTemplate(r, t);
    const hasSensor = Boolean(r.config.illuminance_sensor);
    return html`
      <div class="card">
        <div class="head tone-${tone} ${this.link ? "link" : ""}">
          <div
            class="open"
            role=${this.link ? "button" : nothing}
            tabindex=${this.link ? "0" : nothing}
            aria-label=${this.link ? t("room.open", { room: r.name }) : nothing}
            @click=${this._open}
            @keydown=${this._key}
          >
            <div class="icon"><ha-icon .icon=${statusIcon(r.status)}></ha-icon></div>
            <div class="title">
              <div class="name">${r.name}</div>
              <div class="status">${statusLabel(r.status, t)}</div>
            </div>
          </div>
          <div class="auto">
            <br-switch
              .checked=${live(r.enabled)}
              .label=${t("room.automatic_for", { room: r.name })}
              @change=${this._toggle}
            ></br-switch>
            <span aria-hidden="true">${t("room.automatic")}</span>
          </div>
        </div>
        <div class="body">
          <div class="line">
            <ha-icon .icon=${occupancyIcon(r)}></ha-icon>
            <span>${occupancyText(r, t)}</span>
          </div>
          <div class="ambient">
            <div class="line">
              <ha-icon icon="mdi:brightness-6"></ha-icon>
              <span>${t("room.ambient")}</span>
              <span class="value">${ambientText(r, this.ctx)}</span>
              ${
                hasSensor
                  ? html`<span class="chip tone-${r.dark === false ? "light" : "idle"}"
                      >${darkText(r, t)}</span
                    >`
                  : nothing
              }
              ${
                r.held
                  ? html`<span class="chip tone-active" title=${t("room.held_hint")}
                      ><ha-icon icon="mdi:pause"></ha-icon>${t("room.held")}</span
                    >`
                  : nothing
              }
            </div>
            ${
              hasSensor
                ? html`<br-lux-bar
                      .ambient=${r.ambient}
                      .darkBelow=${r.config.dark_below}
                      .brightAbove=${r.config.bright_above}
                      .label=${t("room.ambient")}
                    ></br-lux-bar>
                    <div class="raw">
                      ${t("room.raw", { lux: formatLux(r.raw_lux, this.ctx.language) })}
                    </div>`
                : nothing
            }
          </div>
          <ul class="lights" aria-label=${t("room.lights")}>
            ${r.lights.map(
              (light) =>
                html`<li class=${isOn(light) ? "on" : ""}>
                  <ha-icon .icon=${lightIcon(light)}></ha-icon>
                  <span class="lname">${light.name}</span>
                  <span class="lstate">${lightText(light, t)}</span>
                </li>`,
            )}
          </ul>
          <div class="facts">
            ${this._wait()}
            ${
              template && r.deadline
                ? html`<div class="countdown">
                    <ha-icon icon="mdi:timer-outline"></ha-icon
                    ><br-countdown .deadline=${r.deadline} .template=${template}></br-countdown>
                  </div>`
                : nothing
            }
            <div class="last ${r.last_action?.action === "failed" ? "failed" : ""}">
              ${
                r.last_action
                  ? html`<ha-icon
                        .icon=${LAST_ACTION_ICONS[r.last_action.action] ?? "mdi:history"}
                      ></ha-icon
                      >${lastActionText(r.last_action, t)} ·
                      ${formatAgo(r.last_action.at, this.ctx)}`
                  : html`<ha-icon icon="mdi:history"></ha-icon>${t("room.no_action")}`
              }
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /** The wait before turning off in force, and the time band that sets it. */
  private _wait() {
    const { t } = this.ctx;
    const r = this.room;
    const wait = formatSeconds(effectiveWaits(r).empty_wait);
    const active = activeBand(r);
    return active
      ? html`<div class="wait band">
          <ha-icon icon="mdi:clock-time-four-outline"></ha-icon>${t("room.band_wait", {
            band: bandName(active.band, active.index, t),
            wait,
          })}
        </div>`
      : html`<div class="wait">
          <ha-icon icon="mdi:timer-sand"></ha-icon>${t("room.wait", { wait })}
        </div>`;
  }

  private _open() {
    if (!this.link) return;
    this.dispatchEvent(
      new CustomEvent("open-room", {
        detail: { room: this.room.id },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private _key(ev: KeyboardEvent) {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      this._open();
    }
  }

  private _toggle(ev: CustomEvent<{ checked: boolean }>) {
    ev.stopPropagation();
    this.dispatchEvent(
      new CustomEvent("set-enabled", {
        detail: { room: this.room.id, enabled: ev.detail.checked },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-room-tile": BrRoomTile;
  }
}
