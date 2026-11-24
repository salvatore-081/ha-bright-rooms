// Visual editor of the card: title and rooms.

import { element } from "../define";
import { LitElement, type PropertyValues, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { fetchSnapshot } from "../api";
import { type Localize, localizer } from "../localize";
import type { HomeAssistant, Snapshot } from "../types";
import { type BrightRoomsCardConfig, cardChoices } from "./bright-rooms-card";

@element("bright-rooms-card-editor")
export class BrightRoomsCardEditor extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private _config!: BrightRoomsCardConfig;
  @state() private _snapshot?: Snapshot;
  private _requested = false;

  setConfig(config: BrightRoomsCardConfig) {
    this._config = config;
  }

  private get _t(): Localize {
    return localizer(this.hass?.locale?.language || this.hass?.language);
  }

  protected willUpdate(changed: PropertyValues) {
    if (!this.hass || !changed.has("hass") || this._requested) return;
    this._requested = true;
    fetchSnapshot(this.hass)
      .then((snap) => (this._snapshot = snap))
      .catch(() => (this._snapshot = undefined));
  }

  private get _areaNames(): Record<string, string> {
    return Object.fromEntries(Object.values(this.hass.areas ?? {}).map((a) => [a.area_id, a.name]));
  }

  render() {
    if (!this.hass || !this._config) return nothing;
    const t = this._t;
    const schema = [
      { name: "title", selector: { text: {} } },
      {
        name: "rooms",
        selector: {
          select: {
            multiple: true,
            mode: "list",
            options: cardChoices(this._snapshot, this._areaNames),
          },
        },
      },
    ];
    return html`<ha-form
      .hass=${this.hass}
      .data=${this._config}
      .schema=${schema}
      .computeLabel=${(field: { name: string }) => t(`card.field_${field.name}`)}
      .computeHelper=${(field: { name: string }) =>
        field.name === "rooms" ? t("card.help_rooms") : undefined}
      @value-changed=${this._changed}
    ></ha-form>`;
  }

  private _changed(ev: CustomEvent<{ value: BrightRoomsCardConfig }>) {
    const config: BrightRoomsCardConfig = { ...ev.detail.value };
    for (const key of Object.keys(config) as (keyof BrightRoomsCardConfig)[]) {
      const value = config[key];
      if (value === "" || value === undefined || (Array.isArray(value) && value.length === 0))
        delete config[key];
    }
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "bright-rooms-card-editor": BrightRoomsCardEditor;
  }
}
