"use client";

import { useEffect, useState } from "react";

import { fetchHealth, type HealthResponse } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "loaded"; health: HealthResponse }
  | { kind: "unreachable" };

const REFRESH_MS = 10_000;

// Phase 1 only: proves browser → Next.js proxy → FastAPI → Postgres/Redis end to end.
// Replaced by the real dashboard in Phase 7 (which will use TanStack Query).
export function SystemStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      try {
        const health = await fetchHealth(controller.signal);
        setState({ kind: "loaded", health });
      } catch {
        if (!controller.signal.aborted) setState({ kind: "unreachable" });
      }
    };

    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  if (state.kind === "loading") {
    return <p className="text-sm text-neutral-500">Checking services…</p>;
  }

  if (state.kind === "unreachable") {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        The API is not reachable.
      </p>
    );
  }

  const { health } = state;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        Overall:{" "}
        <span
          data-testid="overall-status"
          className={health.status === "ok" ? "font-medium text-emerald-600" : "font-medium text-amber-600"}
        >
          {health.status}
        </span>{" "}
        <span className="text-neutral-500">
          · v{health.version} · {health.environment}
        </span>
      </p>
      <ul className="divide-y divide-neutral-200 rounded-xl border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
        {Object.entries(health.checks).map(([name, check]) => (
          <li key={name} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <span className="font-medium">{name}</span>
            <span className="flex items-center gap-2 text-neutral-500">
              {check.detail ?? ""}
              <span
                aria-label={check.status}
                className={
                  "h-2.5 w-2.5 rounded-full " + (check.status === "ok" ? "bg-emerald-500" : "bg-red-500")
                }
              />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
