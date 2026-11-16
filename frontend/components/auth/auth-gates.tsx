"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth-provider";

function FullPageSpinner({ label }: { label: string }) {
  return (
    <div role="status" className="flex flex-1 items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

/** Renders its children only for a signed-in user; everyone else is sent to /login. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return <FullPageSpinner label={status === "loading" ? "Loading your workspace…" : "Redirecting to sign in…"} />;
  }
  return <>{children}</>;
}

/** For the sign-in / register pages: a signed-in visitor goes straight to the dashboard. */
export function GuestOnly({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  if (status === "authenticated") return <FullPageSpinner label="Taking you to your dashboard…" />;
  // While the session check runs the form is shown straight away; a signed-in user is
  // redirected the moment the check finishes.
  return <>{children}</>;
}
