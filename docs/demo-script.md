# Demo video script (about 4 minutes)

A shot list with narration. Record it **with a real `LLM_API_KEY`** so the answers are real;
the screenshots in the README use a stand-in model and should not be mistaken for Gemini output.

## Before recording

1. `cp .env.example .env`, add your `LLM_API_KEY`, `docker compose up --build --wait`.
2. `python scripts/seed_demo.py` (creates `demo@example.com`, uploads the four fictional files).
3. Browser at 1280x720, light theme, zoom 110%, notifications off, clean bookmarks bar.
4. Ask each question once beforehand to confirm the answers match
   [demo/README.md](../demo/README.md). If a good question is refused, lower the relevance
   threshold in Settings and note the value you used.
5. Optional: a second browser profile signed in as another user, for the isolation shot.

## Script

| Time | On screen | Narration |
|---|---|---|
| 0:00 | Title card: project name, one line. | "This is a personal RAG assistant: you upload your own documents and ask questions, and every answer comes with the passage it came from." |
| 0:15 | Terminal: `docker compose up --build --wait`, then `docker compose ps` showing healthy services. | "It runs as six containers: PostgreSQL with pgvector, Redis, a worker, the FastAPI API and a Next.js frontend. One command starts them." |
| 0:35 | Browser: register screen, create an account (or sign in as the demo user). | "Accounts use short-lived access tokens and a rotating refresh cookie." |
| 0:50 | Documents page: drop in a PDF; show the status changing from pending to ready. | "Upload returns immediately. A Celery worker extracts text page by page, splits it into chunks, embeds them locally and stores the vectors in Postgres." |
| 1:20 | Chat: ask "How often must I change my password?" Streamed answer, `[1]` citation, open the source panel. | "The answer streams in. The citation points to the exact file and passage, so I can verify it instead of trusting it." |
| 1:50 | Ask "What does error E-4471 mean and how do I reset it?" Show citation with page 3 of the PDF. | "Here the source is page 3 of a PDF. Exact codes like this are the reason retrieval is hybrid: embeddings find meaning, full-text search finds exact terms." |
| 2:20 | Ask "login secret rotation" (different words from the document). | "And a paraphrase with none of the document's words is still found by its meaning." |
| 2:40 | Ask "What is the CEO's favourite colour?" Show "I couldn't find this in your documents." | "When the documents do not contain the answer, it says so and does not even call the language model." |
| 3:00 | Second profile signed in as another user: Documents page empty; the same question is refused. | "Each user's documents are isolated, enforced in the database query, not just in the interface." |
| 3:20 | Phone-width browser window (or device mode): the chat and documents pages. | "The interface works on a phone." |
| 3:35 | Editor or browser: `docs/evaluation.md` results table; then the green CI run. | "I measured retrieval on 44 questions: vector-only and keyword-only each miss a different kind, hybrid misses none. The caveat is in the same document: the set is small and synthetic. CI builds and starts the whole stack and runs the tests on every push." |
| 3:55 | Closing card: repository URL. | "Code, documentation and a demo dataset are in the repository." |

## Recording tips

* Say what is **not** proven when it comes up (small evaluation set, threshold not tuned).
  Honesty about limits reads as seniority.
* Keep the answers on screen for a few seconds; viewers read slower than you think.
* Record in segments and cut; a failed model call is a fine reason to re-record only that shot.
* Check that no real API key, e-mail address or private file name is visible in any frame.
