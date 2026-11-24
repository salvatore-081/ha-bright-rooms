// The bands of a room, in order (the first active one wins): add, edit,
// move, delete. Each band has conditions ("when": a time window and days,
// the measured light) and overrides ("what changes"). Plain inputs, except
// the zone sensors, which use ha-form's entity picker when it is loaded.

import { element } from "../define";
import { LitElement, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import "./br-switch";
import { confirmDialog } from "./br-confirm";
import type { FormatContext } from "../format";
import {
  DAYS,
  MAX_BANDS,
  ON_DELAY_MAX,
  type ScheduleSaveError,
  WAIT_MAX,
  bandErrors,
  bandName,
  bandSummary,
  daysText,
} from "../schedule";
import { shared, tokens } from "../styles";
import type { Band, BandLight, HomeAssistant } from "../types";

/** A new band: when it is dark, with no override yet (one must be set). */
export const newBand = (): Band => ({
  name: null,
  start: null,
  end: null,
  days: [],
  light: "dark",
  light_room: null,
  on_delay: null,
  empty_wait: null,
  zone_wait: null,
  zone_sensors: null,
});

/** The band's time condition is shown (a window or days, even half filled). */
export const timeOn = (band: Band): boolean =>
  band.start !== null || band.end !== null || band.days.length > 0;

type NumberKey = "on_delay" | "empty_wait" | "zone_wait";

@element("br-schedule-editor")
export class BrScheduleEditor extends LitElement {
  @property({ attribute: false }) ctx!: FormatContext;
  @property({ attribute: false }) hass?: HomeAssistant;
  /** ha-form is loaded (for the zone sensors picker). */
  @property({ type: Boolean }) formReady = false;
  @property({ attribute: false }) bands: Band[] = [];
  /** The id of the band in force now. */
  @property({ attribute: false }) activeBand: string | null = null;
  /** The room's own values, shown as placeholders. */
  @property({ attribute: false }) roomValues = {
    on_delay: 0,
    empty_wait: 30,
    zone_wait: 150,
    zone_sensors: [] as string[],
  };
  /** The rooms of the entry, for the light measured in another room. */
  @property({ attribute: false }) rooms: { id: string; name: string }[] = [];
  /** The room being edited (undefined for a new room). */
  @property({ attribute: false }) roomId?: string;
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
      .group {
        display: grid;
        gap: 12px;
        padding-top: 4px;
        border-top: 1px solid var(--br-border);
      }
      .group h3 {
        margin: 8px 0 0;
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--br-muted);
      }
      .condition {
        display: grid;
        gap: 10px;
      }
      .switch-row {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      label.field.name {
        max-width: 320px;
      }
      select {
        min-height: 40px;
        box-sizing: border-box;
        padding: 0 8px;
        border-radius: 8px;
        border: 1px solid var(--br-border);
        background: var(--br-card-bg);
        color: var(--br-text);
        font: inherit;
        font-size: 1rem;
        width: 100%;
      }
      select:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: 1px;
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

  private get _roomNames(): Record<string, string> {
    return Object.fromEntries(this.rooms.map((r) => [r.id, r.name]));
  }

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
    const name = bandName(band, i, t);
    const shown = this.showErrors || this._touched.has(band);
    const errors = shown ? bandErrors(band) : [];
    const fromSave = this.saveError?.bands.includes(i) ? this._saveErrorText() : "";
    const failed = errors.length > 0 || Boolean(fromSave);
    const open = failed || this._open.has(band) || !band.id;
    const active = Boolean(band.id) && band.id === this.activeBand;
    const bodyId = `band-${i}`;
    const summary = bandSummary(band, this.ctx, {
      roomNames: this._roomNames,
      roomId: this.roomId,
    });
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
            <span class="summary">${summary}</span>
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
      ${open ? this._body(band, i, errors, fromSave, bodyId) : nothing}
    </div>`;
  }

  private _body(band: Band, i: number, errors: string[], fromSave: string, id: string) {
    const { t } = this.ctx;
    return html`<div class="body" id=${id}>
      <label class="field name"
        >${t("band.field_name")}
        <input
          .value=${band.name ?? ""}
          placeholder=${t("band.n", { n: i + 1 })}
          maxlength="40"
          ?disabled=${this.disabled}
          @input=${(ev: Event) => this._set(i, { name: (ev.target as HTMLInputElement).value })}
        />
      </label>
      <section class="group when">
        <h3>${t("band.when")}</h3>
        ${this._time(band, i, errors)} ${this._light(band, i, errors)}
      </section>
      <section class="group what">
        <h3>${t("band.what")}</h3>
        <div class="fields">
          ${this._number(band, i, "on_delay", ON_DELAY_MAX, errors)}
          ${this._number(band, i, "empty_wait", WAIT_MAX, errors)}
          ${this._number(band, i, "zone_wait", WAIT_MAX, errors)}
        </div>
        ${this._zones(band, i)}
        <div class="hint">${t("band.overrides_hint")}</div>
      </section>
      ${
        errors.length || fromSave
          ? html`<ul class="errors" role="alert">
              ${errors.map(
                (e) =>
                  html`<li>${t(`band_error.${e}`, { max: WAIT_MAX, max_on: ON_DELAY_MAX })}</li>`,
              )}
              ${fromSave ? html`<li>${fromSave}</li>` : nothing}
            </ul>`
          : nothing
      }
    </div>`;
  }

  private _switchRow(label: string, checked: boolean, change: (on: boolean) => void) {
    return html`<div class="switch-row">
      <br-switch
        .checked=${checked}
        .label=${label}
        .disabled=${this.disabled}
        @change=${(ev: CustomEvent<{ checked: boolean }>) => change(ev.detail.checked)}
      ></br-switch>
      <span aria-hidden="true">${label}</span>
    </div>`;
  }

  private _time(band: Band, i: number, errors: string[]) {
    const { t } = this.ctx;
    const on = timeOn(band);
    const has = (key: string) => errors.includes(key) || errors.includes("time_pair");
    return html`<div class="condition time">
      ${this._switchRow(t("band.time"), on, (checked) =>
        this._set(
          i,
          checked
            ? { start: band.start ?? "17:00", end: band.end ?? "23:00" }
            : { start: null, end: null, days: [] },
        ),
      )}
      ${
        on
          ? html`<div class="fields">
                <label class="field"
                  >${t("band.field_start")}
                  <input
                    type="time"
                    .value=${band.start ?? ""}
                    aria-invalid=${has("start") ? "true" : "false"}
                    ?disabled=${this.disabled}
                    @change=${(ev: Event) =>
                      this._set(i, { start: (ev.target as HTMLInputElement).value })}
                  />
                </label>
                <label class="field"
                  >${t("band.field_end")}
                  <input
                    type="time"
                    .value=${band.end ?? ""}
                    aria-invalid=${has("end") ? "true" : "false"}
                    ?disabled=${this.disabled}
                    @change=${(ev: Event) =>
                      this._set(i, { end: (ev.target as HTMLInputElement).value })}
                  />
                </label>
              </div>
              <fieldset>
                <legend>${t("band.field_days")} · ${daysText(band.days, t)}</legend>
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
              </fieldset>`
          : nothing
      }
    </div>`;
  }

  private _light(band: Band, i: number, errors: string[]) {
    const { t } = this.ctx;
    const others = this.rooms.filter((r) => r.id !== this.roomId);
    const lightRoom = band.light_room === this.roomId ? null : band.light_room;
    return html`<div class="fields condition light">
      <label class="field"
        >${t("band.field_light")}
        <select
          class="light-select"
          aria-invalid=${errors.includes("light") ? "true" : "false"}
          ?disabled=${this.disabled}
          @change=${(ev: Event) => {
            const value = (ev.target as HTMLSelectElement).value as BandLight | "";
            this._set(i, value ? { light: value } : { light: null, light_room: null });
          }}
        >
          <option value="" ?selected=${!band.light}>${t("band.light_any")}</option>
          <option value="bright" ?selected=${band.light === "bright"}>
            ${t("band.light_bright_option")}
          </option>
          <option value="dark" ?selected=${band.light === "dark"}>
            ${t("band.light_dark_option")}
          </option>
        </select>
      </label>
      ${
        band.light
          ? html`<label class="field"
              >${t("band.field_light_room")}
              <select
                class="room-select"
                ?disabled=${this.disabled}
                @change=${(ev: Event) =>
                  this._set(i, { light_room: (ev.target as HTMLSelectElement).value || null })}
              >
                <option value="" ?selected=${!lightRoom}>${t("band.this_room")}</option>
                ${others.map(
                  (r) =>
                    html`<option value=${r.id} ?selected=${lightRoom === r.id}>${r.name}</option>`,
                )}
                ${
                  lightRoom && !others.some((r) => r.id === lightRoom)
                    ? html`<option value=${lightRoom} selected>${t("band.other_room")}</option>`
                    : nothing
                }
              </select>
            </label>`
          : nothing
      }
    </div>`;
  }

  private _number(band: Band, i: number, key: NumberKey, max: number, errors: string[]) {
    const { t } = this.ctx;
    const value = band[key];
    const bad =
      errors.includes("no_override") ||
      (key === "on_delay" ? errors.includes("on_delay_range") : errors.includes("wait_range"));
    return html`<label class="field"
      >${t(`band.field_${key}`)}
      <input
        type="number"
        inputmode="numeric"
        min="0"
        max=${max}
        step="1"
        data-key=${key}
        .value=${value === null || value === undefined ? "" : String(value)}
        placeholder=${t("band.room_value", { value: this.roomValues[key] })}
        aria-invalid=${bad ? "true" : "false"}
        ?disabled=${this.disabled}
        @input=${(ev: Event) => {
          const text = (ev.target as HTMLInputElement).value.trim();
          const n = text === "" ? null : Number(text);
          this._set(i, { [key]: n === null || Number.isNaN(n) ? null : n });
        }}
      />
    </label>`;
  }

  private _zones(band: Band, i: number) {
    const { t } = this.ctx;
    const on = band.zone_sensors !== null;
    const zones = band.zone_sensors ?? [];
    const own = this.roomValues.zone_sensors.length
      ? t("band.zone_room", { n: this.roomValues.zone_sensors.length })
      : t("band.zone_room_none");
    return html`<div class="zones">
      ${this._switchRow(t("band.zone_override"), on, (checked) =>
        this._set(i, { zone_sensors: checked ? [...this.roomValues.zone_sensors] : null }),
      )}
      ${
        !on
          ? html`<div class="hint">${own}</div>`
          : this.formReady && this.hass
            ? html`<ha-form
                .hass=${this.hass}
                .data=${{ zone_sensors: zones }}
                .schema=${[
                  {
                    name: "zone_sensors",
                    selector: { entity: { filter: { domain: "binary_sensor" }, multiple: true } },
                  },
                ]}
                .computeLabel=${() => t("band.field_zone_sensors")}
                .disabled=${this.disabled}
                @value-changed=${(ev: CustomEvent<{ value: { zone_sensors?: string[] } }>) =>
                  this._set(i, { zone_sensors: ev.detail.value.zone_sensors ?? [] })}
              ></ha-form>`
            : html`<label class="field"
                >${t("band.field_zone_sensors_text")}
                <input
                  class="zone-text"
                  .value=${zones.join(", ")}
                  placeholder="binary_sensor.…"
                  ?disabled=${this.disabled}
                  @change=${(ev: Event) =>
                    this._set(i, {
                      zone_sensors: (ev.target as HTMLInputElement).value
                        .split(/[\s,]+/)
                        .filter(Boolean),
                    })}
                />
              </label>`
      }
      ${on && zones.length === 0 ? html`<div class="hint">${t("band.zone_none_hint")}</div>` : nothing}
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
