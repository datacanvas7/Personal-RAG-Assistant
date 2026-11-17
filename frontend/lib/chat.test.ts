import { describe, expect, it } from "vitest";

import { citationNumber, describeSource, formatScore, linkCitations, orderedSources } from "./chat";
import type { Source } from "./api/types";

const source = (number: number, extra: Partial<Source> = {}): Source => ({
  number,
  document_id: "d",
  chunk_id: "c",
  filename: "a.txt",
  page_number: null,
  score: 0.5,
  ...extra,
});

describe("linkCitations", () => {
  it("links markers that match a source", () => {
    expect(linkCitations("Rotate every 90 days [1].", [source(1)])).toBe(
      "Rotate every 90 days [1](#cite-1).",
    );
  });

  it("leaves markers without a source as plain text", () => {
    expect(linkCitations("See [1] and [4].", [source(1)])).toBe("See [1](#cite-1) and [4].");
  });

  it("does nothing when there are no sources", () => {
    expect(linkCitations("It says [1].", [])).toBe("It says [1].");
  });

  it("does not touch code", () => {
    const text = "Use `a[1]` or\n```\nx[1]\n```\nthen [1].";
    expect(linkCitations(text, [source(1)])).toBe("Use `a[1]` or\n```\nx[1]\n```\nthen [1](#cite-1).");
  });

  it("does not double-wrap existing links", () => {
    expect(linkCitations("[1](https://example.com)", [source(1)])).toBe("[1](https://example.com)");
  });

  it("links several markers in a row", () => {
    expect(linkCitations("[1][2]", [source(1), source(2)])).toBe("[1](#cite-1)[2](#cite-2)");
  });
});

describe("citationNumber", () => {
  it("reads citation targets and ignores other links", () => {
    expect(citationNumber("#cite-3")).toBe(3);
    expect(citationNumber("https://example.com")).toBeNull();
    expect(citationNumber("#cite-x")).toBeNull();
    expect(citationNumber(undefined)).toBeNull();
  });
});

describe("source helpers", () => {
  it("orders by number and drops repeats", () => {
    expect(orderedSources([source(2), source(1), source(2)]).map((s) => s.number)).toEqual([1, 2]);
  });

  it("describes the origin with the page when known", () => {
    expect(describeSource({ filename: "a.pdf", page_number: 3 })).toBe("a.pdf · p. 3");
    expect(describeSource({ filename: "a.txt", page_number: null })).toBe("a.txt");
  });

  it("formats and clamps scores", () => {
    expect(formatScore(0.834)).toBe("83%");
    expect(formatScore(-0.2)).toBe("0%");
    expect(formatScore(1.4)).toBe("100%");
  });
});
