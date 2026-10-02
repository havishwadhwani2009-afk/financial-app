import { describe, expect, it } from "vitest";
import { big, day, num, pct, spct } from "./format";

describe("format helpers never turn missing data into zeros", () => {
  it("renders null/undefined/NaN as an em dash", () => {
    for (const f of [pct, spct, num, big]) {
      expect(f(null)).toBe("—");
      expect(f(undefined)).toBe("—");
    }
    expect(pct(NaN)).toBe("—");
    expect(day(null)).toBe("—");
  });
  it("formats values", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(spct(-0.05)).toBe("-5.0%");
    expect(spct(0.05)).toBe("+5.0%");
    expect(big(2.5e9)).toBe("2.50B");
    expect(day("2024-03-01T10:00:00Z")).toBe("2024-03-01");
  });
});
