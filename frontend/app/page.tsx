import { FileSearch, Quote, ShieldCheck, Upload } from "lucide-react";
import Link from "next/link";

import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: Upload,
    title: "Bring your documents",
    text: "Upload PDF, Word, text and Markdown files. They are read, split and indexed in the background.",
  },
  {
    icon: FileSearch,
    title: "Ask in plain language",
    text: "Questions are matched to the most relevant passages of your own files, not the open web.",
  },
  {
    icon: Quote,
    title: "Answers with citations",
    text: "Every claim points back to the document and page it came from, so you can check it yourself.",
  },
  {
    icon: ShieldCheck,
    title: "Private by design",
    text: "Your files and questions belong to your account only. Nobody else's queries can reach them.",
  },
] as const;

export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-4 sm:px-6">
        <Brand />
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button asChild variant="ghost" className="hidden sm:inline-flex">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild>
            <Link href="/register">Get started</Link>
          </Button>
        </div>
      </header>

      <main className="flex-1">
        <section className="mx-auto max-w-3xl px-4 pt-16 pb-14 text-center sm:px-6 sm:pt-24">
          <p className="mb-4 inline-block rounded-full border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
            Retrieval-augmented generation, on your own files
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            Ask your documents. Get answers you can verify.
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-lg text-pretty text-muted-foreground">
            Upload your notes, papers and reports, then ask questions in plain language. Each answer comes with
            citations to the exact passages it used.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button asChild size="lg" className="w-full sm:w-auto">
              <Link href="/register">Create a free account</Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="w-full sm:w-auto">
              <Link href="/login">I already have an account</Link>
            </Button>
          </div>
        </section>

        <section aria-labelledby="features" className="mx-auto max-w-5xl px-4 pb-20 sm:px-6">
          <h2 id="features" className="sr-only">
            What it does
          </h2>
          <ul className="grid gap-4 sm:grid-cols-2">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="rounded-xl border bg-card p-5 shadow-xs">
                <span className="mb-3 flex size-9 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                  <Icon className="size-4" aria-hidden />
                </span>
                <h3 className="font-semibold">{title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t px-4 py-6 text-center text-sm text-muted-foreground">
        Personal RAG Assistant · a portfolio project
      </footer>
    </div>
  );
}
