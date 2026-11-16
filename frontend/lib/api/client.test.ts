import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, getAccessToken, onSessionExpired, refreshAccessToken, setAccessToken } from "./client";
import { ApiError, NetworkError } from "./errors";

const fetchMock = vi.fn<typeof fetch>();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function tokenResponse(token: string): Response {
  return json({ access_token: token, token_type: "bearer", expires_in: 900 });
}

function authHeader(call: number): string | null {
  const init = fetchMock.mock.calls[call]?.[1];
  return new Headers(init?.headers).get("Authorization");
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  setAccessToken(null);
  onSessionExpired(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("refreshAccessToken", () => {
  it("shares one request between simultaneous callers (the server rotates the cookie)", async () => {
    fetchMock.mockResolvedValue(tokenResponse("fresh"));
    const [a, b, c] = await Promise.all([refreshAccessToken(), refreshAccessToken(), refreshAccessToken()]);
    expect([a, b, c]).toEqual(["fresh", "fresh", "fresh"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe("fresh");
  });

  it("returns null, not an error, when there is no session", async () => {
    fetchMock.mockResolvedValue(json({ error: { code: "unauthorized", message: "no" } }, 401));
    await expect(refreshAccessToken()).resolves.toBeNull();
  });

  it("throws when the server is down, so 'signed out' and 'server down' stay distinct", async () => {
    fetchMock.mockResolvedValue(json({}, 503));
    await expect(refreshAccessToken()).rejects.toBeInstanceOf(ApiError);
  });

  it("can run again after a call finished", async () => {
    fetchMock.mockResolvedValueOnce(tokenResponse("one")).mockResolvedValueOnce(tokenResponse("two"));
    expect(await refreshAccessToken()).toBe("one");
    expect(await refreshAccessToken()).toBe("two");
  });
});

describe("apiRequest", () => {
  it("sends the bearer token and parses JSON", async () => {
    setAccessToken("t1");
    fetchMock.mockResolvedValue(json({ ok: true }));
    await expect(apiRequest("/ping")).resolves.toEqual({ ok: true });
    expect(authHeader(0)).toBe("Bearer t1");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/ping");
  });

  it("restores the session from the refresh cookie when there is no token yet", async () => {
    fetchMock.mockResolvedValueOnce(tokenResponse("restored")).mockResolvedValueOnce(json({ id: "u" }));
    await expect(apiRequest("/users/me")).resolves.toEqual({ id: "u" });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/refresh");
    expect(authHeader(1)).toBe("Bearer restored");
  });

  it("refreshes once on a 401 and retries the request", async () => {
    setAccessToken("expired");
    fetchMock
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "expired" } }, 401))
      .mockResolvedValueOnce(tokenResponse("renewed"))
      .mockResolvedValueOnce(json({ data: 1 }));
    await expect(apiRequest("/documents")).resolves.toEqual({ data: 1 });
    expect(authHeader(2)).toBe("Bearer renewed");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("signs the user out when the refresh is refused", async () => {
    const expired = vi.fn();
    onSessionExpired(expired);
    setAccessToken("expired");
    fetchMock
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "expired" } }, 401))
      .mockResolvedValueOnce(json({ error: { code: "unauthorized", message: "no" } }, 401));
    await expect(apiRequest("/documents")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  it("does not retry a 401 forever", async () => {
    setAccessToken("a");
    fetchMock
      .mockResolvedValueOnce(json({}, 401))
      .mockResolvedValueOnce(tokenResponse("b"))
      .mockResolvedValueOnce(json({}, 401));
    await expect(apiRequest("/documents")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not attach a token or refresh for login-style calls", async () => {
    fetchMock.mockResolvedValue(json({ error: { code: "unauthorized", message: "bad credentials" } }, 401));
    await expect(
      apiRequest("/auth/login", { method: "POST", json: { email: "a@b.co", password: "x" }, auth: false }),
    ).rejects.toMatchObject({ status: 401, message: "bad credentials" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(authHeader(0)).toBeNull();
  });

  it("returns undefined for 204", async () => {
    setAccessToken("t");
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiRequest("/documents/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps a failed fetch to NetworkError", async () => {
    setAccessToken("t");
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiRequest("/documents")).rejects.toBeInstanceOf(NetworkError);
  });
});
