import { describe, expect, it } from "vitest";
import { LANGUAGES, localize, localizer, pickLanguage } from "../src/localize";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("locales", () => {
  const en = LANGUAGES.en;
  for (const [lang, strings] of Object.entries(LANGUAGES)) {
    it(`${lang} has every key of en, with the same placeholders`, () => {
      expect(Object.keys(strings).sort()).toEqual(Object.keys(en).sort());
      for (const [key, text] of Object.entries(en)) {
        expect(placeholders(strings[key]), `${lang} ${key}`).toEqual(placeholders(text));
      }
    });
  }

  it("ships English and Italian only", () => {
    expect(Object.keys(LANGUAGES).sort()).toEqual(["en", "it"]);
  });

  it("picks the base language and falls back to English", () => {
    expect(pickLanguage("it")).toBe("it");
    expect(pickLanguage("it-CH")).toBe("it");
    expect(pickLanguage("en_GB")).toBe("en");
    expect(pickLanguage("de")).toBe("en");
    expect(pickLanguage(undefined)).toBe("en");
    expect(localize("status.on", "de")).toBe("Lights on");
  });

  it("fills placeholders and falls back to the key", () => {
    expect(localize("card.lights_on", "it", { n: 2, total: 3 })).toBe("2 luci accese su 3");
    expect(localize("no.such.key", "it")).toBe("no.such.key");
    // Placeholders without a value stay, for the countdown to fill.
    expect(localizer("en")("deadline.off")).toBe("Turns off in {time}");
  });
});
