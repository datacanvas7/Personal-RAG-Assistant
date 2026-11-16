import { describe, expect, it } from "vitest";

import { ApiError, NetworkError, errorMessage, isUnauthorized, parseErrorBody } from "./errors";

describe("parseErrorBody", () => {
  it("reads the API's own error shape", () => {
    const error = parseErrorBody(409, { error: { code: "conflict", message: "Email already registered." } });
    expect(error).toMatchObject({ status: 409, code: "conflict", message: "Email already registered." });
  });

  it("turns a FastAPI validation error into a readable line", () => {
    const error = parseErrorBody(422, {
      detail: [{ loc: ["body", "password"], msg: "String should have at least 12 characters" }],
    });
    expect(error.code).toBe("validation_error");
    expect(error.message).toBe("password: String should have at least 12 characters");
  });

  it("falls back to a friendly message for a proxy's HTML or an empty body", () => {
    expect(parseErrorBody(502, undefined).message).toMatch(/isn't reachable/);
    expect(parseErrorBody(413, "<html>too big</html>").message).toBe("That file is too large.");
    expect(parseErrorBody(418, {}).message).toBe("The request failed (HTTP 418).");
  });

  it("ignores a blank message from the server", () => {
    expect(parseErrorBody(404, { error: { code: "not_found", message: "" } }).message).toBe(
      "That couldn't be found.",
    );
  });
});

describe("helpers", () => {
  it("errorMessage shows only errors that are safe to show", () => {
    expect(errorMessage(new ApiError(400, "x", "Nope"))).toBe("Nope");
    expect(errorMessage(new NetworkError())).toMatch(/Can't reach the server/);
    expect(errorMessage(new TypeError("internal detail"), "Generic")).toBe("Generic");
  });

  it("isUnauthorized is true only for a 401 ApiError", () => {
    expect(isUnauthorized(new ApiError(401, "unauthorized", "x"))).toBe(true);
    expect(isUnauthorized(new ApiError(403, "forbidden", "x"))).toBe(false);
    expect(isUnauthorized(new Error("x"))).toBe(false);
  });
});
