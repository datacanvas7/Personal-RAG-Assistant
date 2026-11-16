"use client";

import { FileUp, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { documentsApi } from "@/lib/api/endpoints";
import { errorMessage } from "@/lib/api/errors";
import { useInvalidateDocuments, useSettings } from "@/lib/queries";
import { cn, formatBytes } from "@/lib/utils";
import { ACCEPTED_EXTENSIONS, DEFAULT_MAX_UPLOAD_BYTES, validateUpload } from "@/lib/validation";

type Upload = {
  id: string;
  file: File;
  /** 0–100 while the bytes leave the browser. */
  progress: number;
  phase: "queued" | "uploading" | "error";
  error?: string;
};

let nextUploadId = 0;

export function UploadDropzone() {
  const { data: settings } = useSettings();
  const maxBytes = settings?.server.max_upload_bytes ?? DEFAULT_MAX_UPLOAD_BYTES;
  const invalidate = useInvalidateDocuments();

  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const controllers = useRef(new Map<string, AbortController>());
  const running = useRef(false);
  const queue = useRef<Upload[]>([]);

  const patch = useCallback((id: string, changes: Partial<Upload>) => {
    setUploads((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const remove = useCallback((id: string) => {
    controllers.current.get(id)?.abort();
    controllers.current.delete(id);
    queue.current = queue.current.filter((item) => item.id !== id);
    setUploads((current) => current.filter((item) => item.id !== id));
  }, []);

  // One file at a time: keeps the server's work (parse, chunk, embed) from piling up and
  // gives every file honest progress instead of all of them crawling together.
  const drain = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    try {
      let item = queue.current.shift();
      while (item) {
        const { id, file } = item;
        const controller = new AbortController();
        controllers.current.set(id, controller);
        patch(id, { phase: "uploading", progress: 0 });
        try {
          await documentsApi.upload(file, {
            signal: controller.signal,
            onProgress: (percent) => patch(id, { progress: percent }),
          });
          // The file is stored and queued; it now lives in the library list with its
          // own status, so this progress row has done its job.
          setUploads((current) => current.filter((entry) => entry.id !== id));
          void invalidate();
        } catch (error) {
          if (!(error instanceof DOMException && error.name === "AbortError")) {
            patch(id, { phase: "error", error: errorMessage(error, "The upload failed.") });
          }
        } finally {
          controllers.current.delete(id);
        }
        item = queue.current.shift();
      }
    } finally {
      running.current = false;
    }
  }, [invalidate, patch]);

  const addFiles = useCallback(
    (files: File[]) => {
      const accepted: Upload[] = [];
      for (const file of files) {
        const problem = validateUpload(file, maxBytes);
        if (problem) {
          toast.error(`${file.name}: ${problem}`);
          continue;
        }
        accepted.push({ id: `upload-${nextUploadId++}`, file, progress: 0, phase: "queued" });
      }
      if (accepted.length === 0) return;
      queue.current.push(...accepted);
      setUploads((current) => [...current, ...accepted]);
      void drain();
    },
    [drain, maxBytes],
  );

  // Cancel anything still in flight if the page goes away.
  useEffect(() => {
    const active = controllers.current;
    return () => {
      for (const controller of active.values()) controller.abort();
    };
  }, []);

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(Array.from(event.dataTransfer.files));
        }}
        data-dragging={dragging}
        className={cn(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors",
          dragging ? "border-primary bg-accent" : "border-border bg-card",
        )}
      >
        <span className="flex size-10 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <FileUp className="size-5" aria-hidden />
        </span>
        <div>
          <p className="font-medium">Drag files here, or choose them</p>
          <p className="mt-1 text-sm text-muted-foreground">
            PDF, DOCX, TXT or Markdown · up to {formatBytes(maxBytes)} each
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="sr-only"
          aria-label="Upload documents"
          data-testid="file-input"
          onChange={(event) => {
            addFiles(Array.from(event.target.files ?? []));
            event.target.value = ""; // lets the same file be chosen again
          }}
        />
      </div>

      {uploads.length > 0 ? (
        <ul className="space-y-2" aria-label="Uploads in progress">
          {uploads.map((item) => (
            <li key={item.id} className="rounded-lg border bg-card p-3">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{item.file.name}</p>
                  <p
                    className={cn("text-xs", item.phase === "error" ? "text-destructive" : "text-muted-foreground")}
                    role={item.phase === "error" ? "alert" : undefined}
                  >
                    {item.phase === "error"
                      ? item.error
                      : item.phase === "queued"
                        ? `Waiting · ${formatBytes(item.file.size)}`
                        : item.progress < 100
                          ? `Uploading ${item.progress}% · ${formatBytes(item.file.size)}`
                          : "Uploaded — saving…"}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  aria-label={item.phase === "error" ? `Dismiss ${item.file.name}` : `Cancel ${item.file.name}`}
                  onClick={() => remove(item.id)}
                >
                  <X aria-hidden />
                </Button>
              </div>
              {item.phase === "uploading" ? (
                <Progress value={item.progress} className="mt-2" aria-label={`Uploading ${item.file.name}`} />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
