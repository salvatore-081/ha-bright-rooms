// A room: its live status, contributions and presence sensor settings, and
// the form to add or edit it.

import { element } from "../define";
import { LitElement, type PropertyValues, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import "../components/br-room-tile";
import "../components/br-entities-card";
import "../components/br-schedule-editor";
import { errorMessage, fetchSchema, saveRoom, setContribution } from "../api";
import { confirmDialog } from "../components/br-confirm";
import { type FormatContext, formatAgo, formatLux } from "../format";
import { cleanData, formCallbacks, groupFields, nestErrors, splitErrors } from "../form";
import { navigate, notify, panelPath } from "../nav";
import {
  normalizeBands,
  roomValues,
  scheduleSaveError,
  scheduleValid,
  serializeBands,
  validateSchedule,
} from "../schedule";
import { shared, tokens } from "../styles";
import type {
  Band,
  FormField,
  HomeAssistant,
  LightSnapshot,
  RoomSnapshot,
  Snapshot,
} from "../types";
import { confirmDelete } from "./br-view-rooms";

/** A contribution typed in the panel: a non-negative number, or null when not valid. */
export const parseContribution = (text: string): number | null => {
  const trimmed = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  return Math.round(Number(trimmed));
};

@element("br-room-editor")
export class BrRoomEditor extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ attribute: false }) snapshot!: Snapshot;
  @property({ attribute: false }) ctx!: FormatContext;
  @property({ attribute: false }) roomId?: string;
  @property({ type: Boolean }) formReady = false;

  @state() private _schema?: FormField[];
  @state() private _data: Record<string, unknown> = {};
  @state() private _errors: Record<string, string> = {};
  /** The time bands being edited (saved with the rest of the room). */
  @state() private _bands: Band[] = [];
  @state() private _showBandErrors = false;
  @state() private _loadError?: string;
  @state() private _saving = false;
  /** Contributions being typed, by light. */
  @state() private _edits: Record<string, string> = {};
  @state() private _busyLight?: string;
  private _loadedFor?: string;

  static styles = [
    tokens,
    shared,
    css`
      :host {
        display: block;
        max-width: 1100px;
        margin: 0 auto;
      }
      .header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0 0 16px;
      }
      .header h1 {
        flex: 1;
        margin: 0;
        font-size: 1.5rem;
        font-weight: 400;
      }
      .layout {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 360px;
        gap: var(--br-gap);
        align-items: start;
      }
      .layout.new {
        grid-template-columns: minmax(0, 720px);
        justify-content: center;
      }
      .side,
      .forms {
        display: grid;
        gap: var(--br-gap);
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
      .section .card-content {
        padding-top: 8px;
      }
      .hint {
        margin: 4px 0 0;
        color: var(--br-muted);
        font-size: 0.9rem;
        line-height: 1.5;
      }
      .actions {
        position: sticky;
        bottom: 0;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        padding: 12px 0;
        border-top: 1px solid var(--br-border);
        background: var(--primary-background-color, #fafafa);
      }
      .contribution {
        display: grid;
        gap: 6px;
        padding: 10px 16px;
      }
      .contribution + .contribution {
        border-top: 1px solid var(--br-border);
      }
      .contribution .lname {
        font-weight: 500;
      }
      .contribution .meta {
        color: var(--br-muted);
        font-size: 0.85rem;
      }
      .contribution .edit {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .contribution input {
        width: 6em;
        min-height: 36px;
        box-sizing: border-box;
        padding: 0 8px;
        border-radius: 8px;
        border: 1px solid var(--br-border);
        background: transparent;
        color: var(--br-text);
        font: inherit;
      }
      .contribution input:focus-visible {
        outline: 2px solid var(--br-primary);
        outline-offset: 1px;
      }
      .contribution .btn {
        min-height: 32px;
        padding: 0 12px;
      }
      .sensors br-entities-card {
        margin-top: 8px;
      }
      @media (max-width: 900px) {
        .layout {
          grid-template-columns: minmax(0, 1fr);
        }
        .side {
          order: -1;
        }
      }
    `,
  ];

  protected willUpdate(changed: PropertyValues) {
    const key = this.roomId ?? "new";
    if ((changed.has("roomId") || changed.has("hass")) && this._loadedFor !== key && this.hass) {
      this._loadedFor = key;
      this._load();
    }
  }

  private async _load() {
    this._schema = undefined;
    this._errors = {};
    this._loadError = undefined;
    this._edits = {};
    try {
      const form = await fetchSchema(this.hass, this.roomId);
      this._schema = form.schema;
      const { schedule, ...values } = form.values;
      this._data = values;
      this._bands = normalizeBands(schedule);
      this._showBandErrors = false;
    } catch (err) {
      this._loadError = errorMessage(err);
    }
  }

  private get _room(): RoomSnapshot | undefined {
    return this.roomId ? this.snapshot.rooms.find((r) => r.id === this.roomId) : undefined;
  }

  render() {
    const { t } = this.ctx;
    const room = this._room;
    const title = this.roomId ? (room?.name ?? t("editor.unknown")) : t("editor.new_title");
    return html`
      <div class="header">
        <button
          class="icon-btn"
          aria-label=${t("common.back")}
          title=${t("common.back")}
          @click=${this._back}
        >
          <ha-icon icon="mdi:arrow-left"></ha-icon>
        </button>
        <h1>${title}</h1>
      </div>
      ${
        this.roomId && !room && this._loadError
          ? html`<div class="error-box">${t("editor.not_found")}</div>`
          : html`<div class="layout ${room ? "" : "new"}">
              <div class="forms">${this._form()}</div>
              ${
                room
                  ? html`<div class="side">
                      <br-room-tile .room=${room} .ctx=${this.ctx} .link=${false}></br-room-tile>
                      ${this._contributions(room)} ${this._sensors(room)}
                    </div>`
                  : nothing
              }
            </div>`
      }
    `;
  }

  private _form() {
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
      ${groupFields(this._schema).map(
        (group) =>
          html`<div class="card section">
            <h2><ha-icon .icon=${group.icon}></ha-icon>${t(`editor.section_${group.key}`)}</h2>
            ${
              group.key === "area" || group.key === "daylight" || group.key === "off"
                ? html`<div class="card-content hint">${t(`editor.hint_${group.key}`)}</div>`
                : nothing
            }
            <div class="card-content">
              <ha-form
                .hass=${this.hass}
                .data=${this._data}
                .schema=${group.schema}
                .error=${nestErrors(group.schema, fields)}
                .computeLabel=${cb.computeLabel}
                .computeHelper=${cb.computeHelper}
                .computeError=${cb.computeError}
                .localizeValue=${cb.localizeValue}
                .disabled=${this._saving}
                @value-changed=${this._changed}
              ></ha-form>
            </div>
          </div>`,
      )}
      ${this._schedule(fields)}
      <div class="actions">
        <button class="btn filled" ?disabled=${this._saving} @click=${this._save}>
          <ha-icon icon="mdi:content-save-outline"></ha-icon>${t("common.save")}
        </button>
        <button class="btn" ?disabled=${this._saving} @click=${this._back}>
          ${t("common.cancel")}
        </button>
        <span class="spacer"></span>
        ${
          this.roomId
            ? html`<button class="btn danger" ?disabled=${this._saving} @click=${this._delete}>
                <ha-icon icon="mdi:delete-outline"></ha-icon>${t("common.delete")}
              </button>`
            : nothing
        }
      </div>
    `;
  }

  private _schedule(fields: Record<string, string>) {
    const { t } = this.ctx;
    const room = this._room;
    return html`<div class="card section schedule">
      <h2><ha-icon icon="mdi:tune-vertical"></ha-icon>${t("editor.section_schedule")}</h2>
      <div class="card-content hint">${t("editor.hint_schedule")}</div>
      <div class="card-content">
        <br-schedule-editor
          .ctx=${this.ctx}
          .hass=${this.hass}
          .formReady=${this.formReady}
          .rooms=${this.snapshot.rooms.map((r) => ({ id: r.id, name: r.name }))}
          .roomId=${this.roomId}
          .bands=${this._bands}
          .activeBand=${room?.active_band ?? null}
          .roomValues=${roomValues(this._data)}
          .saveError=${scheduleSaveError(fields)}
          .showErrors=${this._showBandErrors}
          .disabled=${this._saving}
          @bands-changed=${(ev: CustomEvent<{ bands: Band[] }>) => (this._bands = ev.detail.bands)}
        ></br-schedule-editor>
      </div>
    </div>`;
  }

  private _contributions(room: RoomSnapshot) {
    const { t } = this.ctx;
    return html`<div class="card section">
      <h2><ha-icon icon="mdi:lightbulb-on-outline"></ha-icon>${t("contrib.title")}</h2>
      <div class="card-content hint">${t("contrib.hint")}</div>
      ${room.lights.map((light) => this._contribution(room, light))}
      <div style="height:6px"></div>
    </div>`;
  }

  private _contribution(room: RoomSnapshot, light: LightSnapshot) {
    const { t } = this.ctx;
    const typed = this._edits[light.entity_id];
    const value = typed ?? (light.contribution === null ? "" : String(light.contribution));
    const parsed = typed === undefined ? undefined : parseContribution(typed);
    const busy = this._busyLight === light.entity_id;
    const meta =
      light.contribution === null
        ? t("contrib.not_learned")
        : [
            t("contrib.samples", { n: light.samples }),
            light.updated ? t("contrib.updated", { when: formatAgo(light.updated, this.ctx) }) : "",
          ]
            .filter(Boolean)
            .join(" · ");
    const id = `c-${light.entity_id}`;
    return html`<div class="contribution">
      <label class="lname" for=${id}>${light.name}</label>
      <div class="meta">
        ${light.contribution === null ? nothing : html`${formatLux(light.contribution, this.ctx.language)} · `}${meta}
      </div>
      <div class="edit">
        <input
          id=${id}
          inputmode="numeric"
          .value=${value}
          placeholder="—"
          aria-invalid=${parsed === null ? "true" : "false"}
          ?disabled=${busy}
          @input=${(ev: InputEvent) =>
            (this._edits = {
              ...this._edits,
              [light.entity_id]: (ev.target as HTMLInputElement).value,
            })}
          @keydown=${(ev: KeyboardEvent) => {
            if (ev.key === "Enter" && parsed !== null && parsed !== undefined)
              this._setContribution(room, light, parsed);
          }}
        />
        <span class="muted">lx</span>
        <button
          class="btn"
          ?disabled=${busy || parsed === null || parsed === undefined || parsed === light.contribution}
          @click=${() => this._setContribution(room, light, parsed ?? null)}
        >
          ${t("common.save")}
        </button>
        <button
          class="btn"
          ?disabled=${busy || light.contribution === null}
          @click=${() => this._measureAgain(room, light)}
        >
          <ha-icon icon="mdi:refresh"></ha-icon>${t("contrib.measure_again")}
        </button>
      </div>
    </div>`;
  }

  private _sensors(room: RoomSnapshot) {
    const { t } = this.ctx;
    return html`<div class="card section sensors">
      <h2><ha-icon icon="mdi:motion-sensor"></ha-icon>${t("sensors.title")}</h2>
      <div class="card-content">
        ${
          room.sensor_entities.length
            ? html`<div class="hint">${t("sensors.hint")}</div>
                <br-entities-card
                  .hass=${this.hass}
                  .entities=${room.sensor_entities}
                  .unavailable=${t("sensors.unavailable")}
                ></br-entities-card>`
            : html`<div class="hint">${t("sensors.none")}</div>`
        }
      </div>
    </div>`;
  }

  private async _setContribution(room: RoomSnapshot, light: LightSnapshot, value: number | null) {
    const { t } = this.ctx;
    this._busyLight = light.entity_id;
    try {
      await setContribution(this.hass, room.id, light.entity_id, value);
      const edits = { ...this._edits };
      delete edits[light.entity_id];
      this._edits = edits;
      notify(
        this,
        value === null
          ? t("toast.contribution_reset", { light: light.name })
          : t("toast.contribution_saved", { light: light.name }),
      );
    } catch (err) {
      notify(this, errorMessage(err));
    } finally {
      this._busyLight = undefined;
    }
  }

  private async _measureAgain(room: RoomSnapshot, light: LightSnapshot) {
    const { t } = this.ctx;
    const ok = await confirmDialog(this.renderRoot as ShadowRoot, {
      title: t("confirm.measure_title", { light: light.name }),
      text: t("confirm.measure_text"),
      confirm: t("contrib.measure_again"),
      cancel: t("common.cancel"),
    });
    if (ok) await this._setContribution(room, light, null);
  }

  private _changed(ev: CustomEvent<{ value: Record<string, unknown> }>) {
    this._data = { ...this._data, ...ev.detail.value };
    for (const [key, value] of Object.entries(ev.detail.value))
      if (value === undefined) delete this._data[key];
  }

  private async _save() {
    const { t } = this.ctx;
    if (!scheduleValid(validateSchedule(this._bands))) {
      this._showBandErrors = true;
      notify(this, t("band_error.fix_first"));
      return;
    }
    this._saving = true;
    try {
      const data = { ...cleanData(this._data), schedule: serializeBands(this._bands) };
      const res = await saveRoom(this.hass, data, this.roomId);
      if (res.errors) {
        this._errors = res.errors;
        return;
      }
      this._errors = {};
      notify(this, t(this.roomId ? "toast.room_saved" : "toast.room_added"));
      if (this.roomId) this._load();
      else if (res.room_id) navigate(panelPath(`/rooms/${res.room_id}`), true);
      else navigate(panelPath("/rooms"));
    } catch (err) {
      this._errors = { base: errorMessage(err) };
    } finally {
      this._saving = false;
    }
  }

  private async _delete() {
    const room = this._room;
    if (!this.roomId) return;
    const deleted = await confirmDelete(
      this,
      this.hass,
      { id: this.roomId, name: room?.name ?? "" },
      this.ctx,
    );
    if (deleted) navigate(panelPath("/rooms"), true);
  }

  private _back() {
    navigate(panelPath("/rooms"));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-room-editor": BrRoomEditor;
  }
}
