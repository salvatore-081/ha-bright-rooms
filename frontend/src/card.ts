// Entry point of the dashboard card (loaded on every page of the frontend).
import "./card/bright-rooms-card";
import "./card/bright-rooms-card-editor";
import { localize } from "./localize";

interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
  documentationURL?: string;
}

const w = window as unknown as { customCards?: CustomCardEntry[] };
w.customCards = w.customCards || [];
if (!w.customCards.some((c) => c.type === "bright-rooms-card")) {
  const language = document.documentElement.lang || navigator.language;
  w.customCards.push({
    type: "bright-rooms-card",
    name: localize("card.name", language),
    description: localize("card.description", language),
    preview: true,
    documentationURL: "https://github.com/salvatore-081/ha-bright-rooms",
  });
}
