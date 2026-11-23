// Overview tab: one tile per room.

import { element } from "../define";
import { LitElement, css, html } from "lit";
import { property } from "lit/decorators.js";
import "../components/br-room-tile";
import type { FormatContext } from "../format";
import { navigate, panelPath } from "../nav";
import { shared, tokens } from "../styles";
import type { Snapshot } from "../types";

@element("br-view-overview")
export class BrViewOverview extends LitElement {
  @property({ attribute: false }) snapshot!: Snapshot;
  @property({ attribute: false }) ctx!: FormatContext;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
      }
      .rooms {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: var(--br-gap);
      }
      @media (max-width: 600px) {
        .rooms {
          grid-template-columns: 1fr;
          gap: 12px;
        }
      }
    `,
  ];

  render() {
    const { t } = this.ctx;
    const rooms = this.snapshot.rooms;
    if (!rooms.length)
      return html`<div class="card empty-state">
        <ha-icon icon="mdi:lightbulb-auto-outline"></ha-icon>
        <p>${t("overview.no_rooms")}</p>
        <button class="btn filled" @click=${() => navigate(panelPath("/rooms/new"))}>
          <ha-icon icon="mdi:plus"></ha-icon>${t("rooms.add")}
        </button>
      </div>`;
    return html`<div class="rooms">
      ${rooms.map((room) => html`<br-room-tile .room=${room} .ctx=${this.ctx}></br-room-tile>`)}
    </div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-view-overview": BrViewOverview;
  }
}
