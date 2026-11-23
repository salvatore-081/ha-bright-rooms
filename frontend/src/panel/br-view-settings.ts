// Settings tab: the global options of the integration.

import { element } from "../define";
import { LitElement, type PropertyValues, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { errorMessage, fetchSchema, saveSettings } from "../api";
import type { FormatContext } from "../format";
import { cleanData, formCallbacks, nestErrors, splitErrors } from "../form";
import { notify } from "../nav";
import { shared, tokens } from "../styles";
import type { FormField, HomeAssistant } from "../types";

@element("br-view-settings")
export class BrViewSettings extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ attribute: false }) ctx!: FormatContext;
  @property({ type: Boolean }) formReady = false;

  @state() private _schema?: FormField[];
  @state() private _data: Record<string, unknown> = {};
  @state() private _saved: Record<string, unknown> = {};
  @state() private _errors: Record<string, string> = {};
  @state() private _loadError?: string;
  @state() private _saving = false;
  private _loaded = false;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: grid;
        gap: var(--br-gap);
        max-width: 760px;
        margin: 0 auto;
      }
      .section h2 {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 0;
        padding: 16px 16px 0;
        font-size: 1rem;
        font-weight: 500;
      }
      .section h2 ha-icon {
        color: var(--br-muted);
      }
      .hint {
        margin: 6px 16px 0;
        color: var(--br-muted);
        font-size: 0.9rem;
        line-height: 1.5;
      }
      .actions {
        position: sticky;
        bottom: 0;
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        padding: 12px 0;
        border-top: 1px solid var(--br-border);
        background: var(--primary-background-color, #fafafa);
      }
      .dirty {
        color: var(--br-muted);
        font-size: 0.9rem;
      }
    `,
  ];

  protected willUpdate(changed: PropertyValues) {
    if (changed.has("hass") && !this._loaded && this.hass) {
      this._loaded = true;
      this._load();
    }
  }

  private async _load() {
    try {
      const form = await fetchSchema(this.hass);
      this._schema = form.settings_schema;
      this._data = { ...form.settings };
      this._saved = { ...form.settings };
      this._loadError = undefined;
    } catch (err) {
      this._loadError = errorMessage(err);
    }
  }

  private get _dirty() {
    return JSON.stringify(cleanData(this._data)) !== JSON.stringify(cleanData(this._saved));
  }

  render() {
    const { t } = this.ctx;
    if (this._loadError) return html`<div class="error-box">${this._loadError}</div>`;
    if (!this._schema || !this.formReady)
      return html`<div class="card card-content muted">
        ${this.formReady || !this._schema ? t("panel.loading") : t("editor.form_unavailable")}
      </div>`;
    const cb = formCallbacks(t);
    const { base, fields } = splitErrors(this._errors);
    return html`
      ${base ? html`<div class="error-box">${cb.computeError(base)}</div>` : nothing}
      <div class="card section">
        <h2><ha-icon icon="mdi:school-outline"></ha-icon>${t("settings.section_learning")}</h2>
        <p class="hint">${t("settings.hint_learning")}</p>
        <div class="card-content">
          <ha-form
            .hass=${this.hass}
            .data=${this._data}
            .schema=${this._schema}
            .error=${nestErrors(this._schema, fields)}
            .computeLabel=${cb.computeLabel}
            .computeHelper=${cb.computeHelper}
            .computeError=${cb.computeError}
            .localizeValue=${cb.localizeValue}
            .disabled=${this._saving}
            @value-changed=${this._changed}
          ></ha-form>
        </div>
      </div>
      <div class="actions">
        <button class="btn filled" ?disabled=${this._saving || !this._dirty} @click=${this._save}>
          <ha-icon icon="mdi:content-save-outline"></ha-icon>${t("common.save")}
        </button>
        <button class="btn" ?disabled=${this._saving || !this._dirty} @click=${this._reset}>
          ${t("common.cancel")}
        </button>
        ${this._dirty ? html`<span class="dirty">${t("settings.unsaved")}</span>` : nothing}
      </div>
    `;
  }

  private _changed(ev: CustomEvent<{ value: Record<string, unknown> }>) {
    this._data = { ...this._data, ...ev.detail.value };
  }

  private _reset() {
    this._data = { ...this._saved };
    this._errors = {};
  }

  private async _save() {
    const { t } = this.ctx;
    this._saving = true;
    try {
      const data = cleanData(this._data);
      const res = await saveSettings(this.hass, data);
      if (res.errors) {
        this._errors = res.errors;
        return;
      }
      this._errors = {};
      this._saved = { ...data };
      this._data = { ...data };
      notify(this, t("toast.settings_saved"));
    } catch (err) {
      this._errors = { base: errorMessage(err) };
    } finally {
      this._saving = false;
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-view-settings": BrViewSettings;
  }
}
