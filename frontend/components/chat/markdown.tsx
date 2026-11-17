"use client";

import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Source } from "@/lib/api/types";
import { citationNumber, linkCitations } from "@/lib/chat";
import { cn } from "@/lib/utils";

/**
 * Renders a model answer as Markdown.
 *
 * Safety: react-markdown builds React elements from the Markdown syntax tree and never
 * injects HTML strings, and raw HTML in the text is not interpreted (there is no rehype-raw
 * plugin), so a document or a model reply cannot add scripts, iframes or event handlers.
 * Link targets with unsafe schemes such as `javascript:` are dropped by the default URL
 * transform, and real links open in a new tab without a referrer.
 */
export function Markdown({
  text,
  sources = [],
  onCite,
  className,
}: {
  text: string;
  sources?: readonly Pick<Source, "number">[];
  /** Called when the reader clicks a [n] chip. */
  onCite?: (number: number) => void;
  className?: string;
}) {
  const components = useMemo<Components>(
    () => ({
      a({ href, children }) {
        const number = citationNumber(href);
        if (number !== null) {
          return (
            <button
              type="button"
              data-testid="citation"
              aria-label={`Show source ${number}`}
              onClick={() => onCite?.(number)}
              className="mx-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] -translate-y-px items-center justify-center rounded bg-primary/15 px-1 align-middle text-[0.7rem] font-semibold text-primary transition-colors hover:bg-primary hover:text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              {number}
            </button>
          );
        }
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="text-primary underline underline-offset-2 hover:opacity-80"
          >
            {children}
          </a>
        );
      },
      p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
      ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
      ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
      h1: ({ children }) => <h3 className="mt-4 mb-2 text-base font-semibold">{children}</h3>,
      h2: ({ children }) => <h3 className="mt-4 mb-2 text-base font-semibold">{children}</h3>,
      h3: ({ children }) => <h4 className="mt-3 mb-1.5 text-sm font-semibold">{children}</h4>,
      h4: ({ children }) => <h4 className="mt-3 mb-1.5 text-sm font-semibold">{children}</h4>,
      blockquote: ({ children }) => (
        <blockquote className="my-2 border-l-2 pl-3 text-muted-foreground">{children}</blockquote>
      ),
      hr: () => <hr className="my-3" />,
      pre: ({ children }) => (
        <pre className="my-2 overflow-x-auto rounded-md border bg-muted p-3 text-xs leading-relaxed">
          {children}
        </pre>
      ),
      code: ({ className: codeClass, children }) => (
        <code
          className={cn(
            "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] [pre_&]:bg-transparent [pre_&]:p-0",
            codeClass,
          )}
        >
          {children}
        </code>
      ),
      table: ({ children }) => (
        <div className="my-2 overflow-x-auto">
          <table className="w-full border-collapse text-sm">{children}</table>
        </div>
      ),
      th: ({ children }) => <th className="border bg-muted px-2 py-1 text-left font-medium">{children}</th>,
      td: ({ children }) => <td className="border px-2 py-1 align-top">{children}</td>,
      // Images in a model reply would be fetched by the browser on render: not allowed.
      img: () => null,
    }),
    [onCite],
  );

  return (
    <div className={cn("break-words", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(text, sources)}
      </ReactMarkdown>
    </div>
  );
}
