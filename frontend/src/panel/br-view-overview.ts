// Overview tab: the rooms (areas), each with its Automatic switch and its light zones.

import { element } from "../define";
import { LitElement, css, html } from "lit";
import { property } from "lit/decorators.js";
import { live } from "lit/directives/live.js";
import "../components/br-room-tile";
import "../components/br-switch";
import type { FormatContext } from "../format";
import { navigate, panelPath } from "../nav";
import { shared, tokens } from "../styles";
import type { Snapshot } from "../types";
import { type AreaGroup, areaSummary, groupByArea } from "../zones";

@element("br-view-overview")
export class BrViewOverview extends LitElement {
  @property({ attribute: false }) snapshot!: Snapshot;
  @property({ attribute: false }) ctx!: FormatContext;
  /** Area names of the frontend, for an integration that sends no `areas`. */
  @property({ attribute: false }) areaNames: Record<string, string> = {};

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: grid;
        gap: 24px;
      }
      .area-head {
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 0 4px 12px;
      }
      .area-head h2 {
        margin: 0;
        font-size: 1.15rem;
        font-weight: 500;
      }
      .area-head .summary {
        flex: 1;
        min-width: 0;
        color: var(--br-muted);
        font-size: 0.9rem;
      }
      .auto {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.85rem;
        color: var(--br-muted);
      }
      .zones {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: var(--br-gap);
      }
      @media (max-width: 600px) {
        :host {
          gap: 20px;
        }
        .area-head {
          flex-wrap: wrap;
        }
        .zones {
          grid-template-columns: 1fr;
          gap: 12px;
        }
      }
    `,
  ];

  render() {
    const { t } = this.ctx;
    if (!this.snapshot.rooms.length)
      return html`<div class="card empty-state">
        <ha-icon icon="mdi:lightbulb-auto-outline"></ha-icon>
        <p>${t("overview.no_rooms")}</p>
        <button class="btn filled" @click=${() => navigate(panelPath("/rooms/new"))}>
          <ha-icon icon="mdi:plus"></ha-icon>${t("rooms.add")}
        </button>
      </div>`;
    return groupByArea(this.snapshot, this.areaNames).map((group) => this._area(group));
  }

  private _area(group: AreaGroup) {
    const { t } = this.ctx;
    const { area } = group;
    return html`<section class="area" aria-labelledby="area-${area.area_id}">
      <div class="area-head">
        <h2 id="area-${area.area_id}">${area.name}</h2>
        <span class="summary">${areaSummary(group, t)}</span>
        <div class="auto">
          <span aria-hidden="true">${t("room.automatic")}</span>
          <br-switch
            .checked=${live(area.enabled)}
            .label=${t("area.automatic_for", { room: area.name })}
            @change=${(ev: CustomEvent<{ checked: boolean }>) => {
              ev.stopPropagation();
              this.dispatchEvent(
                new CustomEvent("set-area-enabled", {
                  detail: { area: area.area_id, enabled: ev.detail.checked },
                  bubbles: true,
                  composed: true,
                }),
              );
            }}
          ></br-switch>
        </div>
      </div>
      <div class="zones">
        ${group.zones.map(
          (zone) => html`<br-room-tile .room=${zone} .ctx=${this.ctx}></br-room-tile>`,
        )}
      </div>
    </section>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-view-overview": BrViewOverview;
  }
}
