import { SystemStatus } from "@/components/system-status";

// Temporary Phase 1 page. The landing page replaces it in Phase 7.
export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-6 px-6 py-16">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Personal RAG Assistant</h1>
        <p className="text-neutral-500">
          Foundation check — every service the application depends on, as seen from the backend.
        </p>
      </header>
      <SystemStatus />
    </main>
  );
}
