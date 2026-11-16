import { cn } from "@/lib/utils";

import { Label } from "./label";

/** A label, a control and its error/hint, wired together for screen readers. */
export function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  className?: string;
  /** Render the control; receives the ids/ARIA props it must spread onto the input. */
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby": string | undefined }) => React.ReactNode;
}) {
  const messageId = error || hint ? `${id}-message` : undefined;
  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={id}>{label}</Label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": messageId })}
      {error ? (
        <p id={messageId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={messageId} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
