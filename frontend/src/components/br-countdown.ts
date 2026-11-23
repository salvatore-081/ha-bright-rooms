// A live countdown to an ISO time: ticks every second only while shown.

import { element } from "../define";
import { LitElement, css, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { countdownText } from "../format";

@element("br-countdown")
export class BrCountdown extends LitElement {
  @property() deadline: string | null = null;
  /** The label, with `{time}` where the countdown goes. */
  @property() template = "{time}";
  @state() private _now = new Date();
  private _timer?: number;

  static styles = css`
    :host {
      font-variant-numeric: tabular-nums;
    }
  `;

  connectedCallback() {
    super.connectedCallback();
    this._timer = window.setInterval(() => {
      if (this.deadline) this._now = new Date();
    }, 1000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.clearInterval(this._timer);
  }

  protected willUpdate(changed: Map<string, unknown>) {
    if (changed.has("deadline")) this._now = new Date();
  }

  render() {
    if (!this.deadline) return nothing;
    return html`${countdownText(this.template, this.deadline, this._now)}`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-countdown": BrCountdown;
  }
}
