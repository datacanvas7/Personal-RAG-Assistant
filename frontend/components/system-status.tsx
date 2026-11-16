"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

const REFRESH_MS = 15_000;

/** Backend health as seen through the same proxy the app uses: browser → Next.js → FastAPI → Postgres/Redis. */
export function SystemStatus() {
  const { data: health, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: REFRESH_MS,
    retry: false,
  });

  if (isPending) return <p className="text-sm text-muted-foreground">Checking services…</p>;
  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The API is not reachable.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm">
        Overall:{" "}
        <span
          data-testid="overall-status"
          className={cn("font-medium", health.status === "ok" ? "text-success" : "text-warning")}
        >
          {health.status}
        </span>{" "}
        <span className="text-muted-foreground">
          · v{health.version} · {health.environment}
        </span>
      </p>
      <ul className="divide-y rounded-lg border">
        {Object.entries(health.checks).map(([name, check]) => (
          <li key={name} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
            <span className="font-medium">{name}</span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <span className="truncate">{check.detail ?? ""}</span>
              <span
                role="img"
                aria-label={check.status}
                className={cn("size-2.5 shrink-0 rounded-full", check.status === "ok" ? "bg-success" : "bg-destructive")}
              />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
