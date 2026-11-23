// The time bands of a room, in order (the first active one wins): add, edit,
// move, delete. Plain inputs, so it works before ha-form is loaded.

import { element } from "../define";
import { LitElement, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { confirmDialog } from "./br-confirm";
import type { FormatContext } from "../format";
import {
  DAYS,
  MAX_BANDS,
  WAIT_MAX,
  bandErrors,
  bandName,
  bandRange,
  daysText,
  overridesText,
  type ScheduleSaveError,
} from "../schedule";
import { shared, tokens } from "../styles";
import type { Band } from "../types";

/** A new band: the evening, every day, with no override yet (one must be set). */
export const newBand = (): Band => ({
  name: null,
  start: "22:00",
  end: "06:00",
  days: [],
  empty_wait: null,
  zone_wait: null,
});

@element("br-schedule-editor")
export class BrScheduleEditor extends LitElement {
  @property({ attribute: false }) ctx!: FormatContext;
  @property({ attribute: false }) bands: Band[] = [];
  /** The id of the band in force now. */
  @property({ attribute: false }) activeBand: string | null = null;
  /** The room's own waits, shown as placeholders. */
  @property({ attribute: false }) roomWaits = { empty_wait: 30, zone_wait: 150 };
  /** An error of the integration's save: its key and the bands, if known. */
  @property({ attribute: false }) saveError: ScheduleSaveError | null = null;
  /** Show the errors of every band (after a save attempt), not only of touched ones. */
  @property({ type: Boolean }) showErrors = false;
  @property({ type: Boolean }) disabled = false;
  /** Bands opened by the user, by object (so moves keep them open). */
  @state() private _open = new Set<Band>();
  @state() private _touched = new Set<Band>();

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
      }
      .band {
        border: 1px solid var(--br-border);
        border-radius: var(--br-radius);
        margin-bottom: 12px;
      }
      .band.active {
        border-color: var(--br-light);
      }
      .band.error {
        border-color: var(--br-error);
      }
      .head {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 4px 4px 8px;
      }
      .toggle {
        flex: 1;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 4px;
        border: none;
        background: none;
        color: inherit;
        font: inherit;
        text-align: left;
        cursor: pointer;
        border-radius: 8px;
      }
      .toggle:focus-visible {
        outline: 2px solid var(--br-primary);
      }
      .toggle .chevron {
        flex: none;
        color: var(--br-muted);
        transition: transform 0.15s;
      }
      .band.open .toggle .chevron {
        transform: rotate(90deg);
      }
      .info {
        min-width: 0;
        display: grid;
        gap: 2px;
      }
      .title {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        font-weight: 500;
      }
      .summary {
        color: var(--br-muted);
        font-size: 0.85rem;
      }
      .chips {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
      }
      .chip.day {
        --tone: var(--br-muted);
        padding: 0 8px;
        font-weight: 400;
      }
      .body {
        display: grid;
        gap: 12px;
        padding: 4px 16px 16px;
      }
      .fields {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 12px;
      }
      label.field {
        display: grid;
        gap: 4px;
        font-size: 0.85rem;
        color: var(--br-muted);
      }
      input {
        min-height: 40px;
        box-sizing: border-box;
        padding: 0 10px;
        border-radius: 8px;
        border: 1px solid var(--br-border);
        background: transparent;
        color: var(--br-text);
        font: inherit;
        font-size: 1rem;
        width: 100%;
        color-scheme: light dark;
      }
      input:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: 1px;
      }
      input[aria-invalid="true"] {
        border-color: var(--br-error);
      }
      fieldset {
        border: 0;
        margin: 0;
        padding: 0;
      }
      legend {
        padding: 0;
        margin-bottom: 6px;
        font-size: 0.85rem;
        color: var(--br-muted);
      }
      .day-toggle {
        min-width: 44px;
        min-height: 32px;
        padding: 0 10px;
        border-radius: 16px;
        border: 1px solid var(--br-border);
        background: transparent;
        color: var(--br-text);
        font: inherit;
        font-size: 0.85rem;
        cursor: pointer;
      }
      .day-toggle[aria-pressed="true"] {
        background: var(--br-primary);
        border-color: var(--br-primary);
        color: var(--br-on-primary);
      }
      .day-toggle:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: 2px;
      }
      .hint {
        color: var(--br-muted);
        font-size: 0.85rem;
      }
      .errors {
        margin: 0;
        padding: 0 0 0 18px;
        color: var(--br-error);
        font-size: 0.9rem;
      }
      .list-error {
        margin: 0 0 12px;
        color: var(--br-error);
      }
      .empty {
        margin: 0 0 12px;
        color: var(--br-muted);
      }
      .footer {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
      }
    `,
  ];

  render() {
    const { t } = this.ctx;
    const listError =
      this.bands.length > MAX_BANDS
        ? t("band_error.too_many", { n: MAX_BANDS })
        : this.saveError && this.saveError.bands.length === 0
          ? this._saveErrorText()
          : "";
    return html`
      ${listError ? html`<p class="list-error" role="alert">${listError}</p>` : nothing}
      ${
        this.bands.length
          ? this.bands.map((band, i) => this._band(band, i))
          : html`<p class="empty">${t("band.none")}</p>`
      }
      <div class="footer">
        <button
          class="btn"
          ?disabled=${this.disabled || this.bands.length >= MAX_BANDS}
          @click=${this._add}
        >
          <ha-icon icon="mdi:plus"></ha-icon>${t("band.add")}
        </button>
        <span class="hint">${t("band.count", { n: this.bands.length, max: MAX_BANDS })}</span>
      </div>
    `;
  }

  private _saveErrorText(): string {
    const key = this.saveError?.key ?? "schedule_invalid";
    const text = this.ctx.t(`error.${key}`);
    return text === `error.${key}` ? this.ctx.t("error.schedule_invalid") : text;
  }

  private _band(band: Band, i: number) {
    const { t } = this.ctx;
    const n = i + 1;
    const name = bandName(band, i, t);
    const shown = this.showErrors || this._touched.has(band);
    const errors = shown ? bandErrors(band) : [];
    const fromSave = this.saveError?.bands.includes(i) ? this._saveErrorText() : "";
    const failed = errors.length > 0 || Boolean(fromSave);
    const open = failed || this._open.has(band) || !band.id;
    const active = Boolean(band.id) && band.id === this.activeBand;
    const overrides = overridesText(band, t);
    const bodyId = `band-${i}`;
    return html`<div
      class="band ${open ? "open" : ""} ${active ? "active" : ""} ${failed ? "error" : ""}"
    >
      <div class="head">
        <button
          class="toggle"
          aria-expanded=${open ? "true" : "false"}
          aria-controls=${bodyId}
          @click=${() => this._toggle(band)}
        >
          <ha-icon class="chevron" icon="mdi:chevron-right"></ha-icon>
          <span class="info">
            <span class="title">
              ${name}
              ${
                active
                  ? html`<span class="chip tone-light active-marker"
                      ><ha-icon icon="mdi:clock-check-outline"></ha-icon>${t("band.active")}</span
                    >`
                  : nothing
              }
            </span>
            <span class="summary"
              >${bandRange(band, this.ctx)}${overrides ? ` · ${overrides}` : ""}</span
            >
            <span class="chips">${this._dayChips(band)}</span>
          </span>
        </button>
        <button
          class="icon-btn"
          ?disabled=${this.disabled || i === 0}
          aria-label=${t("band.move_up", { name })}
          title=${t("band.move_up", { name })}
          @click=${() => this._move(i, -1)}
        >
          <ha-icon icon="mdi:chevron-up"></ha-icon>
        </button>
        <button
          class="icon-btn"
          ?disabled=${this.disabled || i === this.bands.length - 1}
          aria-label=${t("band.move_down", { name })}
          title=${t("band.move_down", { name })}
          @click=${() => this._move(i, 1)}
        >
          <ha-icon icon="mdi:chevron-down"></ha-icon>
        </button>
        <button
          class="icon-btn delete"
          ?disabled=${this.disabled}
          aria-label=${t("band.remove", { name })}
          title=${t("band.remove", { name })}
          @click=${() => this._remove(i)}
        >
          <ha-icon icon="mdi:delete-outline"></ha-icon>
        </button>
      </div>
      ${open ? this._body(band, i, n, errors, fromSave, bodyId) : nothing}
    </div>`;
  }

  private _dayChips(band: Band) {
    const { t } = this.ctx;
    if (!band.days.length || band.days.length === DAYS.length)
      return html`<span class="chip day">${t("band.every_day")}</span>`;
    return daysText(band.days, t)
      .split(", ")
      .map((part) => html`<span class="chip day">${part}</span>`);
  }

  private _body(band: Band, i: number, n: number, errors: string[], fromSave: string, id: string) {
    const { t } = this.ctx;
    const wait = (v: number | null) => (v === null || v === undefined ? "" : String(v));
    const has = (key: string) => errors.includes(key);
    return html`<div class="body" id=${id}>
      <div class="fields">
        <label class="field"
          >${t("band.field_name")}
          <input
            .value=${band.name ?? ""}
            placeholder=${t("band.n", { n })}
            maxlength="40"
            ?disabled=${this.disabled}
            @input=${(ev: Event) => this._set(i, { name: (ev.target as HTMLInputElement).value })}
          />
        </label>
        <label class="field"
          >${t("band.field_start")}
          <input
            type="time"
            required
            .value=${band.start}
            aria-invalid=${has("start") ? "true" : "false"}
            ?disabled=${this.disabled}
            @change=${(ev: Event) => this._set(i, { start: (ev.target as HTMLInputElement).value })}
          />
        </label>
        <label class="field"
          >${t("band.field_end")}
          <input
            type="time"
            required
            .value=${band.end}
            aria-invalid=${has("end") ? "true" : "false"}
            ?disabled=${this.disabled}
            @change=${(ev: Event) => this._set(i, { end: (ev.target as HTMLInputElement).value })}
          />
        </label>
      </div>
      <fieldset>
        <legend>${t("band.field_days")}</legend>
        <div class="chips">
          ${DAYS.map(
            (day) =>
              html`<button
                class="day-toggle"
                aria-pressed=${band.days.includes(day) ? "true" : "false"}
                ?disabled=${this.disabled}
                @click=${() => this._toggleDay(i, day)}
              >
                ${t(`day.${day}`)}
              </button>`,
          )}
        </div>
      </fieldset>
      <div class="fields">
        <label class="field"
          >${t("band.field_empty_wait")}
          <input
            type="number"
            inputmode="numeric"
            min="0"
            max=${WAIT_MAX}
            step="1"
            .value=${wait(band.empty_wait)}
            placeholder=${t("band.room_value", { value: this.roomWaits.empty_wait })}
            aria-invalid=${has("no_override") || has("wait_range") ? "true" : "false"}
            ?disabled=${this.disabled}
            @input=${(ev: Event) => this._setWait(i, "empty_wait", ev)}
          />
        </label>
        <label class="field"
          >${t("band.field_zone_wait")}
          <input
            type="number"
            inputmode="numeric"
            min="0"
            max=${WAIT_MAX}
            step="1"
            .value=${wait(band.zone_wait)}
            placeholder=${t("band.room_value", { value: this.roomWaits.zone_wait })}
            aria-invalid=${has("no_override") || has("wait_range") ? "true" : "false"}
            ?disabled=${this.disabled}
            @input=${(ev: Event) => this._setWait(i, "zone_wait", ev)}
          />
        </label>
      </div>
      <div class="hint">${t("band.overrides_hint")}</div>
      ${
        errors.length || fromSave
          ? html`<ul class="errors" role="alert">
              ${errors.map((e) => html`<li>${t(`band_error.${e}`, { max: WAIT_MAX })}</li>`)}
              ${fromSave ? html`<li>${fromSave}</li>` : nothing}
            </ul>`
          : nothing
      }
    </div>`;
  }

  private _emit(bands: Band[]) {
    this.dispatchEvent(new CustomEvent("bands-changed", { detail: { bands } }));
  }

  private _set(index: number, change: Partial<Band>) {
    const old = this.bands[index];
    const band: Band = { ...old, ...change };
    // Keep the band open and its errors shown under its new object.
    if (this._open.has(old)) this._open = new Set([...this._open, band]);
    this._touched = new Set([...this._touched, band]);
    this._emit(this.bands.map((b, i) => (i === index ? band : b)));
  }

  private _setWait(index: number, key: "empty_wait" | "zone_wait", ev: Event) {
    const text = (ev.target as HTMLInputElement).value.trim();
    const value = text === "" ? null : Number(text);
    this._set(index, { [key]: value === null || Number.isNaN(value) ? null : value });
  }

  private _toggleDay(index: number, day: string) {
    const days = this.bands[index].days;
    const next = days.includes(day) ? days.filter((d) => d !== day) : [...days, day];
    this._set(index, { days: DAYS.filter((d) => next.includes(d)) });
  }

  private _toggle(band: Band) {
    const open = new Set(this._open);
    if (open.has(band)) open.delete(band);
    else open.add(band);
    this._open = open;
  }

  private _add() {
    if (this.bands.length >= MAX_BANDS) return;
    this._emit([...this.bands, newBand()]);
  }

  private _move(index: number, delta: number) {
    const bands = [...this.bands];
    const [moved] = bands.splice(index, 1);
    bands.splice(index + delta, 0, moved);
    this._emit(bands);
  }

  private async _remove(index: number) {
    const { t } = this.ctx;
    const band = this.bands[index];
    const ok = await confirmDialog(this.renderRoot as ShadowRoot, {
      title: t("band.remove_title", { name: bandName(band, index, t) }),
      text: t("band.remove_text"),
      confirm: t("common.delete"),
      cancel: t("common.cancel"),
      destructive: true,
    });
    if (ok) this._emit(this.bands.filter((_, i) => i !== index));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-schedule-editor": BrScheduleEditor;
  }
}
