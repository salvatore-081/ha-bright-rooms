// The ambient light on a small bar, with the dark and bright thresholds.

import { element } from "../define";
import { LitElement, css, html, nothing } from "lit";
import { property } from "lit/decorators.js";
import { luxScale } from "../format";
import { tokens } from "../styles";

@element("br-lux-bar")
export class BrLuxBar extends LitElement {
  @property({ type: Number }) ambient: number | null = null;
  @property({ type: Number }) darkBelow = 40;
  @property({ type: Number }) brightAbove = 80;
  @property() label = "";

  static styles = [
    tokens,
    css`
      :host {
        display: block;
      }
      .bar {
        position: relative;
        height: 8px;
        border-radius: 4px;
        background: linear-gradient(
          to right,
          color-mix(in srgb, var(--br-muted) 30%, transparent) 0 var(--dark),
          color-mix(in srgb, var(--br-light) 22%, transparent) var(--dark) var(--bright),
          color-mix(in srgb, var(--br-light) 45%, transparent) var(--bright) 100%
        );
      }
      .fill {
        position: absolute;
        inset: 0 auto 0 0;
        border-radius: 4px;
        background: var(--br-light);
      }
      .mark {
        position: absolute;
        top: -3px;
        bottom: -3px;
        width: 2px;
        margin-left: -1px;
        border-radius: 1px;
        background: var(--br-text);
        opacity: 0.55;
      }
      .scale {
        position: relative;
        height: 14px;
        margin-top: 3px;
        font-size: 0.7rem;
        color: var(--br-muted);
        font-variant-numeric: tabular-nums;
      }
      .scale span {
        position: absolute;
        transform: translateX(-50%);
        white-space: nowrap;
      }
    `,
  ];

  render() {
    const s = luxScale(this.ambient, this.darkBelow, this.brightAbove);
    return html`
      <div
        class="bar"
        role="meter"
        aria-label=${this.label}
        aria-valuemin="0"
        aria-valuemax=${s.max}
        aria-valuenow=${this.ambient ?? nothing}
        style="--dark:${s.dark}%;--bright:${s.bright}%"
      >
        ${s.value === null ? nothing : html`<div class="fill" style="width:${s.value}%"></div>`}
        <div class="mark dark" style="left:${s.dark}%"></div>
        <div class="mark bright" style="left:${s.bright}%"></div>
      </div>
      <div class="scale" aria-hidden="true">
        <span style="left:${s.dark}%">${this.darkBelow}</span>
        <span style="left:${s.bright}%">${this.brightAbove}</span>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "br-lux-bar": BrLuxBar;
  }
}
