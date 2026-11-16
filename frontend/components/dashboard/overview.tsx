"use client";

import { CheckCircle2, FileText, Layers, Loader2, MessageSquare, Quote, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { useOverview } from "@/lib/queries";

function Stat({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: number;
  icon: typeof FileText;
  hint?: string;
}) {
  return (
    <Card className="gap-2">
      <CardHeader className="flex-row items-center justify-between gap-2">
        <CardDescription>{label}</CardDescription>
        <Icon className="size-4 text-muted-foreground" aria-hidden />
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tabular-nums">{value.toLocaleString("en")}</p>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

export function Overview() {
  const { user } = useAuth();
  const { data, isPending, isError, error, refetch } = useOverview();

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 truncate text-sm text-muted-foreground">Welcome, {user?.email}.</p>
        </div>
        <Button asChild>
          <Link href="/documents">Upload documents</Link>
        </Button>
      </header>

      {isError ? (
        <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm">
          <p className="text-destructive">{errorMessage(error, "Couldn't load your overview.")}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-busy>
          {[0, 1, 2, 3].map((key) => (
            <Skeleton key={key} className="h-28" />
          ))}
        </div>
      ) : data.documents.total === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Start with a document</CardTitle>
            <CardDescription>
              Your library is empty. Upload a PDF, Word, text or Markdown file and it will be ready to question
              in a moment.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/documents">Go to documents</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <section aria-label="Library" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Documents" value={data.documents.total} icon={FileText} />
            <Stat label="Ready to ask" value={data.documents.ready} icon={CheckCircle2} />
            <Stat
              label="Processing"
              value={data.documents.processing}
              icon={Loader2}
              hint={data.documents.processing > 0 ? "Updating automatically" : undefined}
            />
            <Stat
              label="Failed"
              value={data.documents.failed}
              icon={TriangleAlert}
              hint={data.documents.failed > 0 ? "Retry them from Documents" : undefined}
            />
          </section>

          <section aria-label="Usage" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Indexed passages" value={data.chunks} icon={Layers} />
            <Stat label="Conversations" value={data.conversations} icon={MessageSquare} />
            <Stat label="Questions asked" value={data.questions} icon={MessageSquare} />
            <Stat
              label="Answers with citations"
              value={data.cited_answers}
              icon={Quote}
              hint={`of ${data.answers.toLocaleString("en")} answers`}
            />
          </section>

          <Card>
            <CardHeader>
              <CardTitle>Last {data.recent_activity.days} days</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-4 sm:grid-cols-3">
                <div>
                  <dt className="text-sm text-muted-foreground">Documents uploaded</dt>
                  <dd className="text-xl font-semibold tabular-nums">{data.recent_activity.documents_uploaded}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Conversations started</dt>
                  <dd className="text-xl font-semibold tabular-nums">{data.recent_activity.conversations_started}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Questions asked</dt>
                  <dd className="text-xl font-semibold tabular-nums">{data.recent_activity.questions_asked}</dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
