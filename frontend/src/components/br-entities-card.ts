// The frontend's own entities card for a list of entities (the presence
// sensors' settings): numbers, selects and buttons work natively.

import { element } from "../define";
import { LitElement, type PropertyValues, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import type { HomeAssistant } from "../types";

interface LovelaceCard extends HTMLElement {
  hass?: HomeAssistant;
}

interface CardHelpers {
  createCardElement(config: Record<string, unknown>): LovelaceCard | Promise<LovelaceCard>;
}

const cardHelpers = (): Promise<CardHelpers> | undefined =>
  (window as unknown as { loadCardHelpers?: () => Promise<CardHelpers> }).loadCardHelpers?.();

@element("br-entities-card")
export class BrEntitiesCard extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ attribute: false }) entities: string[] = [];
  /** Shown when the frontend's cards cannot be loaded. */
  @property() unavailable = "";
  @state() private _card?: LovelaceCard;
  @state() private _failed = false;
  private _builtFor?: string;

  static styles = css`
    :host {
      display: block;
    }
    .unavailable {
      color: var(--secondary-text-color, #727272);
    }
  `;

  protected willUpdate(changed: PropertyValues) {
    const key = this.entities.join(",");
    if (changed.has("entities") && key !== this._builtFor) {
      this._builtFor = key;
      this._build(key);
    }
    // Every change of the states reaches the card.
    if (changed.has("hass") && this._card) this._card.hass = this.hass;
  }

  private async _build(key: string) {
    try {
      const helpers = await cardHelpers();
      if (!helpers) throw new Error("no card helpers");
      const card = await helpers.createCardElement({
        type: "entities",
        entities: this.entities,
        state_color: false,
      });
      if (key !== this._builtFor) return;
      card.hass = this.hass;
      this._card = card;
      this._failed = false;
    } catch {
      this._failed = true;
    }
  }

  render() {
    if (this._failed) return html`<div class="unavailable">${this.unavailable}</div>`;
    return this._card ?? nothing;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-entities-card": BrEntitiesCard;
  }
}
