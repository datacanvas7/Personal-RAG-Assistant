import { AlertTriangle, CheckCircle2, Clock, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/lib/api/types";

const CONFIG: Record<
  DocumentStatus,
  { label: string; variant: "success" | "warning" | "info" | "destructive"; icon: typeof Clock; spin?: boolean }
> = {
  pending: { label: "Queued", variant: "warning", icon: Clock },
  processing: { label: "Processing", variant: "info", icon: Loader2, spin: true },
  ready: { label: "Ready", variant: "success", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "destructive", icon: AlertTriangle },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const { label, variant, icon: Icon, spin } = CONFIG[status];
  return (
    <Badge variant={variant} data-status={status}>
      <Icon className={spin ? "animate-spin" : undefined} aria-hidden />
      {label}
    </Badge>
  );
}
