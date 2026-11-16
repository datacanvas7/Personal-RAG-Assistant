import { BookOpenText } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

export const APP_NAME = "Personal RAG Assistant";

export function Brand({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <BookOpenText className="size-4" aria-hidden />
      </span>
      <span>{APP_NAME}</span>
    </Link>
  );
}
