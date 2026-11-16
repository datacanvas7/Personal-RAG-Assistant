import { describe, expect, it } from "vitest";

import { filterDocuments } from "./documents";
import type { DocumentRead } from "./api/types";
import { isInFlight, pollInterval } from "./queries";
import { loginSchema, registerSchema, retrievalSchema, validateUpload } from "./validation";

describe("registerSchema", () => {
  const valid = { email: " Me@Example.com ", password: "correct horse battery", confirmPassword: "correct horse battery" };

  it("accepts valid input and trims the email", () => {
    const result = registerSchema.safeParse(valid);
    expect(result.success).toBe(true);
    expect(result.data?.email).toBe("Me@Example.com");
  });

  it("requires 12–128 character passwords", () => {
    expect(registerSchema.safeParse({ ...valid, password: "short", confirmPassword: "short" }).success).toBe(false);
    const long = "x".repeat(129);
    expect(registerSchema.safeParse({ ...valid, password: long, confirmPassword: long }).success).toBe(false);
    const edge = "x".repeat(12);
    expect(registerSchema.safeParse({ ...valid, password: edge, confirmPassword: edge }).success).toBe(true);
  });

  it("flags a mismatched confirmation on that field", () => {
    const result = registerSchema.safeParse({ ...valid, confirmPassword: "something else entirely" });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["confirmPassword"]);
  });

  it("rejects an invalid email", () => {
    expect(registerSchema.safeParse({ ...valid, email: "nope" }).success).toBe(false);
  });
});

describe("loginSchema", () => {
  it("only needs a plausible email and some password", () => {
    expect(loginSchema.safeParse({ email: "a@b.co", password: "x" }).success).toBe(true);
    expect(loginSchema.safeParse({ email: "", password: "x" }).success).toBe(false);
    expect(loginSchema.safeParse({ email: "a@b.co", password: "" }).success).toBe(false);
  });
});

describe("validateUpload", () => {
  const MB = 1024 * 1024;
  it("accepts the supported types, any case", () => {
    for (const name of ["a.pdf", "b.DOCX", "c.txt", "d.md"]) {
      expect(validateUpload({ name, size: 1000 })).toBeNull();
    }
  });
  it("rejects other types, empty files and oversized files", () => {
    expect(validateUpload({ name: "a.exe", size: 1000 })).toMatch(/Unsupported/);
    expect(validateUpload({ name: "a.pdf", size: 0 })).toMatch(/empty/);
    expect(validateUpload({ name: "a.pdf", size: 25 * MB + 1 })).toMatch(/25 MB/);
    expect(validateUpload({ name: "a.pdf", size: 25 * MB })).toBeNull();
  });
  it("honours the server's limit", () => {
    expect(validateUpload({ name: "a.pdf", size: 3 * MB }, 2 * MB)).toMatch(/2 MB/);
  });
});

describe("retrievalSchema", () => {
  it("coerces form strings and enforces the bounds the API enforces", () => {
    expect(retrievalSchema.parse({ topK: "5", scoreThreshold: "0.3" })).toEqual({ topK: 5, scoreThreshold: 0.3 });
    expect(retrievalSchema.safeParse({ topK: "0", scoreThreshold: "0.3" }).success).toBe(false);
    expect(retrievalSchema.safeParse({ topK: "21", scoreThreshold: "0.3" }).success).toBe(false);
    expect(retrievalSchema.safeParse({ topK: "2.5", scoreThreshold: "0.3" }).success).toBe(false);
    expect(retrievalSchema.safeParse({ topK: "5", scoreThreshold: "1.1" }).success).toBe(false);
    expect(retrievalSchema.safeParse({ topK: "5", scoreThreshold: "0" }).success).toBe(true);
  });
});

function doc(overrides: Partial<DocumentRead>): DocumentRead {
  return {
    id: "1",
    filename: "Report.pdf",
    content_type: "application/pdf",
    size_bytes: 10,
    status: "ready",
    error_message: null,
    total_pages: 1,
    total_chunks: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("filterDocuments", () => {
  const items = [
    doc({ id: "1", filename: "Report.pdf", status: "ready" }),
    doc({ id: "2", filename: "notes.md", status: "processing" }),
    doc({ id: "3", filename: "queued.txt", status: "pending" }),
    doc({ id: "4", filename: "broken.docx", status: "failed" }),
  ];
  const ids = (list: DocumentRead[]) => list.map((item) => item.id);

  it("searches file names case-insensitively", () => {
    expect(ids(filterDocuments(items, "REPORT", "all"))).toEqual(["1"]);
    expect(ids(filterDocuments(items, "  ", "all"))).toEqual(["1", "2", "3", "4"]);
  });
  it("treats 'processing' as queued + processing", () => {
    expect(ids(filterDocuments(items, "", "processing"))).toEqual(["2", "3"]);
  });
  it("combines the search and the status filter", () => {
    expect(ids(filterDocuments(items, "t", "ready"))).toEqual(["1"]);
    expect(ids(filterDocuments(items, "broken", "ready"))).toEqual([]);
  });
});

describe("polling", () => {
  it("polls only while something is in flight", () => {
    const list = (...statuses: DocumentRead["status"][]) => ({
      items: statuses.map((status, index) => doc({ id: String(index), status })),
      total: statuses.length,
      limit: 100,
      offset: 0,
    });
    expect(pollInterval(undefined)).toBe(false);
    expect(pollInterval(list("ready", "failed"))).toBe(false);
    expect(pollInterval(list("ready", "pending"))).toBe(2000);
    expect(pollInterval(list("processing"))).toBe(2000);
    expect(isInFlight({ status: "ready" })).toBe(false);
  });
});
