# Roadmap

What is finished, what is deliberately missing, and what would be built next. Items are ordered
by how much they would improve a real deployment, not by effort.

## Done (Phases 0-11)

Foundations, authentication, document ingestion, embeddings and vector search, grounded
answers, chat with streaming, the frontend, retrieval evaluation and hybrid search, security
hardening and container hardening, and this presentation layer. Phase by phase detail and the
verification evidence are in [PROGRESS.md](PROGRESS.md).

## Next

| # | Item | Why it matters |
|---|---|---|
| 1 | **Run the demo with a real Gemini key and record the results** | The answer pipeline is tested with a stand-in model; real transcripts and screenshots would replace that caveat. Also the first honest data for tuning the relevance threshold. |
| 2 | **Tune the relevance threshold on real documents** | `RETRIEVAL_SCORE_THRESHOLD=0.45` is a starting point. Too high refuses good questions, too low lets weak passages through. |
| 3 | **Answer-quality evaluation** | Groundedness and citation correctness need an LLM judge plus a labelled question set; today only retrieval is measured. |
| 4 | **OCR for scanned PDFs** | They are rejected with a clear message today. |
| 5 | **S3-compatible file storage** | Needed to run more than one host; the `StorageBackend` interface exists, the adapter does not. |
| 6 | **Cross-encoder reranker** | The lexical reranker only breaks near-ties; a cross-encoder plugs into the same `Reranker` interface and could help on larger, messier collections. |
| 7 | **Nonce-based Content-Security-Policy** | Removes the remaining `'unsafe-inline'` gap in the page CSP. |
| 8 | **Error tracker and metrics** | Only the hook and structured logs exist. |
| 9 | **Per-user storage quota and upload malware scanning** | Listed as known gaps in [operations.md](operations.md). |
| 10 | **E-mail verification and password reset** | Needs a mail provider. |
| 11 | **Load test** | Single-instance behaviour has not been measured. |

## Ideas, not commitments

* Sharing a document or a collection between users (needs a permission model on top of the
  current strict per-user isolation).
* More file types (HTML, EPUB, spreadsheets).
* Per-conversation document scoping in the UI (the API already accepts `document_ids`).
* Larger local embedding models, and multilingual models.
* Choosing a licence.
