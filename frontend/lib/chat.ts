import type { Source } from "@/lib/api/types";

/** Longest question the API accepts (backend MAX_QUESTION_CHARS). */
export const MAX_QUESTION_CHARS = 2000;

/** Prefix of the fake link target used to mark a citation inside Markdown. */
export const CITATION_HREF = "#cite-";

/**
 * Turn the model's `[1]` markers into Markdown links to `#cite-1`, so the renderer can show
 * them as citation chips. Only numbers that match a real source are linked: a stray "[7]"
 * with no source behind it stays plain text instead of pointing at nothing.
 * Fenced and inline code is left alone.
 */
export function linkCitations(text: string, sources: readonly Pick<Source, "number">[]): string {
  if (sources.length === 0) return text;
  const known = new Set(sources.map((source) => source.number));
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part.replace(/\[(\d{1,3})\](?!\()/g, (match, digits: string) =>
            known.has(Number(digits)) ? `[${digits}](${CITATION_HREF}${digits})` : match,
          ),
    )
    .join("");
}

/** The citation number a link target stands for, or null if it is an ordinary link. */
export function citationNumber(href: string | undefined): number | null {
  if (!href?.startsWith(CITATION_HREF)) return null;
  const number = Number(href.slice(CITATION_HREF.length));
  return Number.isInteger(number) ? number : null;
}

/** Sources in citation order, one entry per number. */
export function orderedSources(sources: readonly Source[]): Source[] {
  const seen = new Set<number>();
  return [...sources]
    .sort((a, b) => a.number - b.number)
    .filter((source) => (seen.has(source.number) ? false : (seen.add(source.number), true)));
}

/** "report.pdf · p. 3" - where a passage came from, in a few words. */
export function describeSource(source: Pick<Source, "filename" | "page_number">): string {
  return source.page_number ? `${source.filename} · p. ${source.page_number}` : source.filename;
}

/** Relevance as a whole-number percentage for display. Scores are cosine similarities. */
export function formatScore(score: number): string {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}
