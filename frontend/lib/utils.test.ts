import { describe, expect, it } from "vitest";

import { cn, formatBytes, timeAgo } from "./utils";

describe("formatBytes", () => {
  it("uses whole bytes below 1 KB", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });
  it("uses one decimal from KB up", () => {
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(10 * 1024 * 1024)).toBe("10.0 MB");
  });
  it("rejects nonsense", () => {
    expect(formatBytes(-1)).toBe("—");
    expect(formatBytes(Number.NaN)).toBe("—");
  });
});

describe("timeAgo", () => {
  const now = new Date("2026-01-10T12:00:00Z");
  it("says just now for the last few seconds", () => {
    expect(timeAgo("2026-01-10T11:59:40Z", now)).toBe("just now");
  });
  it("counts minutes, hours and days", () => {
    expect(timeAgo("2026-01-10T11:55:00Z", now)).toBe("5 minutes ago");
    expect(timeAgo("2026-01-10T09:00:00Z", now)).toBe("3 hours ago");
    expect(timeAgo("2026-01-08T12:00:00Z", now)).toBe("2 days ago");
  });
  it("returns an empty string for an invalid date", () => {
    expect(timeAgo("not a date", now)).toBe("");
  });
});

describe("cn", () => {
  it("lets a later Tailwind utility win", () => {
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
  });
});
