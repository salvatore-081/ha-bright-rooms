// Shared styles. Only Home Assistant theme variables, with fallbacks, so the
// panel follows the user's theme in light and dark mode.

import { css } from "lit";

export const tokens = css`
  :host {
    --br-gap: 16px;
    --br-radius: var(--ha-card-border-radius, 12px);
    --br-card-bg: var(--card-background-color, var(--ha-card-background, #fff));
    --br-border: var(--divider-color, rgba(0, 0, 0, 0.12));
    --br-text: var(--primary-text-color, #212121);
    --br-muted: var(--secondary-text-color, #727272);
    --br-primary: var(--primary-color, #03a9f4);
    --br-on-primary: var(--text-primary-color, #fff);
    --br-success: var(--success-color, #43a047);
    --br-warning: var(--warning-color, #ffa600);
    --br-error: var(--error-color, #db4437);
    --br-info: var(--info-color, #039be5);
    --br-off: var(--disabled-text-color, #bdbdbd);
    --br-light: var(--state-light-on-color, var(--amber-color, #ffc107));
  }
`;

export const shared = css`
  .card {
    background: var(--br-card-bg);
    border-radius: var(--br-radius);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--br-border));
    box-shadow: var(--ha-card-box-shadow, none);
    color: var(--br-text);
  }
  .card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 16px 0;
    font-size: 1.1rem;
    font-weight: 500;
  }
  .card-content {
    padding: 16px;
  }
  .muted {
    color: var(--br-muted);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .spacer {
    flex: 1;
  }

  /* Buttons */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 36px;
    padding: 0 14px;
    border-radius: 18px;
    border: 1px solid var(--br-border);
    background: transparent;
    color: var(--br-primary);
    font: inherit;
    font-weight: 500;
    font-size: 0.9rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--br-primary) 8%, transparent);
  }
  .btn:focus-visible,
  .icon-btn:focus-visible,
  .tab:focus-visible {
    outline: 2px solid var(--br-primary);
    outline-offset: 2px;
  }
  .btn:disabled {
    color: var(--br-off);
    cursor: default;
  }
  .btn.filled {
    background: var(--br-primary);
    border-color: var(--br-primary);
    color: var(--br-on-primary);
  }
  .btn.filled:hover:not(:disabled) {
    background: color-mix(in srgb, var(--br-primary) 88%, black);
  }
  .btn.filled:disabled {
    background: var(--br-off);
    border-color: var(--br-off);
    color: var(--br-on-primary);
  }
  .btn.danger {
    color: var(--br-error);
  }
  .btn.danger.filled {
    background: var(--br-error);
    border-color: var(--br-error);
    color: #fff;
  }
  .btn ha-icon {
    --mdc-icon-size: 18px;
  }
  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: var(--br-muted);
    cursor: pointer;
    padding: 0;
    flex: none;
  }
  .icon-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--br-text) 8%, transparent);
  }
  .icon-btn:disabled {
    color: var(--br-off);
    cursor: default;
  }

  /* Status chips and tones */
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px 2px 8px;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 500;
    line-height: 20px;
    white-space: nowrap;
    color: var(--tone);
    background: color-mix(in srgb, var(--tone) 14%, transparent);
  }
  .chip ha-icon {
    --mdc-icon-size: 16px;
  }
  .tone-light {
    --tone: var(--br-light);
  }
  .tone-active {
    --tone: var(--br-info);
  }
  .tone-warning {
    --tone: var(--br-warning);
  }
  .tone-idle {
    --tone: var(--br-muted);
  }
  .tone-off {
    --tone: var(--br-off);
  }
  .tone-error {
    --tone: var(--br-error);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  .error-box {
    padding: 12px 16px;
    border-radius: 8px;
    color: var(--br-error);
    background: color-mix(in srgb, var(--br-error) 10%, transparent);
  }
  .empty-state {
    padding: 48px 16px;
    text-align: center;
    color: var(--br-muted);
  }
  .empty-state ha-icon {
    --mdc-icon-size: 48px;
    color: var(--br-off);
    display: block;
    margin: 0 auto 12px;
  }
`;
