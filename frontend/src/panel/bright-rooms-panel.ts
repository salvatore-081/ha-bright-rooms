// The sidebar panel: toolbar, tabs and routing; it owns the live snapshot.

import { element } from "../define";
import { LitElement, css, html } from "lit";
import { property, state } from "lit/decorators.js";
import "../components/br-confirm";
import "./br-view-overview";
import "./br-view-rooms";
import "./br-room-editor";
import "./br-view-settings";
import { errorMessage, setAreaEnabled, setRoomEnabled, subscribeSnapshot } from "../api";
import { type FormatContext, formatContext } from "../format";
import { loadHaForm } from "../load-ha-elements";
import { type Localize, localizer } from "../localize";
import { BASE, navigate, notify, panelPath } from "../nav";
import { shared, tokens } from "../styles";
import type { HomeAssistant, Snapshot } from "../types";

type Tab = "overview" | "rooms" | "settings";
const TABS: Tab[] = ["overview", "rooms", "settings"];
const TAB_ICONS: Record<Tab, string> = {
  overview: "mdi:view-dashboard-outline",
  rooms: "mdi:floor-plan",
  settings: "mdi:cog-outline",
};
// Relative times ("5 minutes ago"); countdowns tick on their own.
const TICK_MS = 30_000;

@element("bright-rooms-panel")
export class BrightRoomsPanel extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ type: Boolean, reflect: true }) narrow = false;
  @property({ attribute: false }) route?: { prefix: string; path: string };

  @state() private _snapshot?: Snapshot;
  @state() private _error?: string;
  @state() private _formReady = false;
  @state() private _now = new Date();

  private _unsub?: Promise<() => void>;
  private _timer?: number;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
        min-height: 100vh;
        background: var(--primary-background-color, #fafafa);
        color: var(--br-text);
        font-family: var(--paper-font-body1_-_font-family, inherit);
      }
      .toolbar {
        position: sticky;
        top: 0;
        z-index: 4;
        background: var(--app-header-background-color, var(--primary-color));
        color: var(--app-header-text-color, var(--text-primary-color, #fff));
        border-bottom: var(--app-header-border-bottom, none);
        padding-top: env(safe-area-inset-top);
      }
      .bar {
        display: flex;
        align-items: center;
        gap: 4px;
        height: var(--header-height, 56px);
        padding: 0 12px 0 4px;
        box-sizing: border-box;
      }
      .bar .title {
        flex: 1;
        font-size: 20px;
        font-weight: 400;
        margin-left: 12px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      nav {
        display: flex;
        gap: 4px;
        padding: 0 8px;
        overflow-x: auto;
        scrollbar-width: none;
      }
      .tab {
        position: relative;
        padding: 0 16px;
        height: 48px;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: inherit;
        opacity: 0.75;
        text-decoration: none;
        font-weight: 500;
        font-size: 0.95rem;
        white-space: nowrap;
        border-radius: 8px 8px 0 0;
      }
      .tab ha-icon {
        --mdc-icon-size: 20px;
      }
      .tab[aria-current="page"] {
        opacity: 1;
      }
      .tab[aria-current="page"]::after {
        content: "";
        position: absolute;
        left: 12px;
        right: 12px;
        bottom: 0;
        height: 3px;
        border-radius: 3px 3px 0 0;
        background: currentColor;
      }
      main {
        max-width: 1280px;
        margin: 0 auto;
        padding: var(--br-gap);
        box-sizing: border-box;
      }
      :host([narrow]) main {
        padding: 12px;
      }
      :host([narrow]) .tab span {
        display: none;
      }
      :host([narrow]) .tab {
        flex: 1;
        justify-content: center;
      }
      .center {
        display: flex;
        justify-content: center;
        padding: 64px 16px;
        color: var(--br-muted);
      }
    `,
  ];

  private get _t(): Localize {
    return localizer(this.hass?.locale?.language || this.hass?.language);
  }

  private get _ctx(): FormatContext {
    return formatContext(this.hass, this._t, this._now);
  }

  connectedCallback() {
    super.connectedCallback();
    this._timer = window.setInterval(() => (this._now = new Date()), TICK_MS);
    if (this.hass) this._subscribe();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.clearInterval(this._timer);
    this._unsub?.then((unsub) => unsub()).catch(() => undefined);
    this._unsub = undefined;
  }

  protected firstUpdated() {
    loadHaForm().then((ok) => (this._formReady = ok));
  }

  protected updated(changed: Map<string, unknown>) {
    if (changed.has("hass") && !this._unsub) this._subscribe();
  }

  private _subscribe() {
    if (!this.hass || this._unsub || !this.isConnected) return;
    this._unsub = subscribeSnapshot(this.hass, (snap) => {
      this._snapshot = snap;
      this._error = undefined;
      this._now = new Date();
    });
    this._unsub.catch((err) => (this._error = errorMessage(err)));
  }

  private get _segments(): string[] {
    return (this.route?.path ?? "").split("/").filter(Boolean);
  }

  private get _tab(): Tab {
    const first = this._segments[0] as Tab | undefined;
    return first && TABS.includes(first) ? first : "overview";
  }

  render() {
    const t = this._t;
    return html`
      <div class="toolbar">
        <div class="bar">
          <ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>
          <div class="title">Bright Rooms</div>
        </div>
        <nav aria-label="Bright Rooms">
          ${TABS.map(
            (tab) =>
              html`<a
                class="tab"
                href=${tab === "overview" ? BASE : `${BASE}/${tab}`}
                aria-current=${this._tab === tab ? "page" : "false"}
                @click=${(ev: MouseEvent) => this._goTab(ev, tab)}
              >
                <ha-icon .icon=${TAB_ICONS[tab]}></ha-icon><span>${t(`tab.${tab}`)}</span>
              </a>`,
          )}
        </nav>
      </div>
      <main
        @set-enabled=${this._setEnabled}
        @set-area-enabled=${this._setAreaEnabled}
        @open-room=${this._openRoom}
      >
        ${this._content()}
      </main>
    `;
  }

  private _content() {
    const t = this._t;
    if (this._error) return html`<div class="error-box">${this._error}</div>`;
    const snap = this._snapshot;
    if (!snap) return html`<div class="center">${t("panel.loading")}</div>`;
    const ctx = this._ctx;
    switch (this._tab) {
      case "overview":
        return html`<br-view-overview
          .snapshot=${snap}
          .ctx=${ctx}
          .areaNames=${this._areaNames}
        ></br-view-overview>`;
      case "rooms": {
        const id = this._segments[1];
        if (id)
          return html`<br-room-editor
            .hass=${this.hass}
            .snapshot=${snap}
            .ctx=${ctx}
            .roomId=${id === "new" ? undefined : id}
            .formReady=${this._formReady}
          ></br-room-editor>`;
        return html`<br-view-rooms
          .hass=${this.hass}
          .snapshot=${snap}
          .ctx=${ctx}
          .areaNames=${this._areaNames}
        ></br-view-rooms>`;
      }
      case "settings":
        return html`<br-view-settings
          .hass=${this.hass}
          .ctx=${ctx}
          .formReady=${this._formReady}
        ></br-view-settings>`;
    }
  }

  private _goTab(ev: MouseEvent, tab: Tab) {
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;
    ev.preventDefault();
    navigate(panelPath(tab === "overview" ? "" : `/${tab}`));
  }

  private async _setEnabled(ev: CustomEvent<{ room: string; enabled: boolean }>) {
    try {
      await setRoomEnabled(this.hass, ev.detail.room, ev.detail.enabled);
    } catch (err) {
      notify(this, errorMessage(err));
      this._now = new Date(); // redraw the switch with the real state
    }
  }

  private async _setAreaEnabled(ev: CustomEvent<{ area: string; enabled: boolean }>) {
    try {
      await setAreaEnabled(this.hass, ev.detail.area, ev.detail.enabled);
    } catch (err) {
      notify(this, errorMessage(err));
      this._now = new Date(); // redraw the switch with the real state
    }
  }

  private get _areaNames(): Record<string, string> {
    return Object.fromEntries(Object.values(this.hass.areas ?? {}).map((a) => [a.area_id, a.name]));
  }

  private _openRoom(ev: CustomEvent<{ room: string }>) {
    navigate(panelPath(`/rooms/${ev.detail.room}`));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "bright-rooms-panel": BrightRoomsPanel;
  }
}
