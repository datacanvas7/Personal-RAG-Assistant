"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { SystemStatus } from "@/components/system-status";
import { THEME_OPTIONS, useThemeChoice } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import type { SettingsRead } from "@/lib/api/types";
import { useSettings, useUpdateSettings } from "@/lib/queries";
import { formatBytes } from "@/lib/utils";
import { retrievalSchema, TOP_K_MAX, TOP_K_MIN, type RetrievalInput, type RetrievalValues } from "@/lib/validation";

function AppearanceCard() {
  const { theme, choose } = useThemeChoice();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>Saved to your account, so it follows you to other devices.</CardDescription>
      </CardHeader>
      <CardContent>
        <div role="group" aria-label="Theme" className="grid grid-cols-3 gap-2">
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
            <Button
              key={value}
              type="button"
              variant={theme === value ? "secondary" : "outline"}
              aria-pressed={theme === value}
              onClick={() => choose(value)}
            >
              <Icon aria-hidden />
              {label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function RetrievalCard({ settings }: { settings: SettingsRead }) {
  const update = useUpdateSettings();
  const effective = {
    topK: settings.retrieval_top_k ?? settings.defaults.top_k,
    scoreThreshold: settings.retrieval_score_threshold ?? settings.defaults.score_threshold,
  };
  const usingDefaults = settings.retrieval_top_k === null && settings.retrieval_score_threshold === null;

  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
  } = useForm<RetrievalInput, unknown, RetrievalValues>({
    resolver: zodResolver(retrievalSchema),
    // `values` keeps the form in step with the server after a save or a reset.
    values: effective,
  });

  const save = handleSubmit((values) =>
    update.mutate(
      { retrieval_top_k: values.topK, retrieval_score_threshold: values.scoreThreshold },
      {
        onSuccess: () => toast.success("Retrieval settings saved."),
        onError: (error) => toast.error(errorMessage(error, "Couldn't save your settings.")),
      },
    ),
  );

  const reset = () =>
    update.mutate(
      { retrieval_top_k: null, retrieval_score_threshold: null },
      {
        onSuccess: () => toast.success("Back to the defaults."),
        onError: (error) => toast.error(errorMessage(error, "Couldn't reset your settings.")),
      },
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Retrieval</CardTitle>
        <CardDescription>
          How much of your documents is looked at when you ask a question.{" "}
          {usingDefaults ? "You are using the defaults." : "You have customised these values."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={save} noValidate className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="topK"
              label="Passages per question"
              error={errors.topK?.message}
              hint={`${TOP_K_MIN}–${TOP_K_MAX}. More passages give more context but a slower, costlier answer. Default ${settings.defaults.top_k}.`}
            >
              {(props) => <Input {...props} type="number" inputMode="numeric" step={1} {...register("topK")} />}
            </Field>
            <Field
              id="scoreThreshold"
              label="Minimum relevance"
              error={errors.scoreThreshold?.message}
              hint={`0–1. Passages scoring below this are ignored; higher is stricter. Default ${settings.defaults.score_threshold}.`}
            >
              {(props) => (
                <Input {...props} type="number" inputMode="decimal" step="any" {...register("scoreThreshold")} />
              )}
            </Field>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={update.isPending} disabled={!isDirty}>
              Save changes
            </Button>
            <Button type="button" variant="ghost" onClick={reset} disabled={usingDefaults || update.isPending}>
              Reset to defaults
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function ServerCard({ settings }: { settings: SettingsRead }) {
  const { server } = settings;
  const rows: [string, React.ReactNode][] = [
    [
      "Answer model",
      <span key="llm" className="flex items-center gap-2">
        {server.llm_model}
        <Badge variant={server.llm_configured ? "success" : "warning"}>
          {server.llm_configured ? "Connected" : "No API key"}
        </Badge>
      </span>,
    ],
    ["Embeddings", `${server.embedding_provider} · ${server.embedding_model}`],
    ["Chunk size", `${server.chunk_size_chars} characters, ${server.chunk_overlap_chars} overlap`],
    ["Upload limit", formatBytes(server.max_upload_bytes)],
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>This server</CardTitle>
        <CardDescription>Read-only. These are set by whoever runs the deployment.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="divide-y">
          {rows.map(([label, value]) => (
            <div key={label} className="flex flex-col gap-1 py-2.5 text-sm sm:flex-row sm:justify-between sm:gap-4">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium break-words sm:text-right">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

export function SettingsView() {
  const { data, isPending, isError, error, refetch } = useSettings();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Make the assistant behave the way you like.</p>
      </header>

      <AppearanceCard />

      {isError ? (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm">
          <p className="text-destructive">{errorMessage(error, "Couldn't load your settings.")}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : isPending ? (
        <div className="space-y-6" aria-busy>
          <Skeleton className="h-56" />
          <Skeleton className="h-48" />
        </div>
      ) : (
        <>
          <RetrievalCard settings={data} />
          <ServerCard settings={data} />
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>System status</CardTitle>
          <CardDescription>Whether the services behind the app are healthy.</CardDescription>
        </CardHeader>
        <CardContent>
          <SystemStatus />
        </CardContent>
      </Card>
    </div>
  );
}
