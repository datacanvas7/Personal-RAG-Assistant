import type { Metadata } from "next";

import { DocumentList } from "@/components/documents/document-list";
import { UploadDropzone } from "@/components/documents/upload-dropzone";

export const metadata: Metadata = { title: "Documents" };

export default function DocumentsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload files to make them searchable. Processing happens in the background and this page updates by
          itself.
        </p>
      </header>
      <UploadDropzone />
      <DocumentList />
    </div>
  );
}
