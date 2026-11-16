import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names, letting later Tailwind utilities override earlier ones. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const UNITS = ["B", "KB", "MB", "GB"] as const;

/** 1536 → "1.5 KB". Binary units, one decimal from KB up. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return unit === 0 ? `${value} B` : `${value.toFixed(1)} ${UNITS[unit]}`;
}

const TIME_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "2 minutes ago" for an ISO timestamp. `now` is injectable for tests. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const diff = (new Date(iso).getTime() - now.getTime()) / 1000; // negative = in the past
  if (Number.isNaN(diff)) return "";
  const magnitude = Math.abs(diff);
  if (magnitude < 45) return "just now";
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of TIME_UNITS) {
    if (magnitude >= size) return format.format(Math.round(diff / size), unit);
  }
  return format.format(Math.round(diff / 60), "minute");
}
