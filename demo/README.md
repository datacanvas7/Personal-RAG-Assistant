# Demo dataset

Four short, **fictional** documents for a made-up company ("Northwind Labs"), so you can try the
assistant without uploading anything private. Nothing here is real policy.

| File | Type | What it shows |
|---|---|---|
| `northwind-security-policy.md` | Markdown | Passwords, devices, incident reporting |
| `northwind-leave-and-benefits.md` | Markdown | Leave, parental leave, learning budget |
| `northwind-remote-work-and-travel.md` | Markdown | Remote work and expense rules |
| `pump-station-ps7-field-manual.pdf` | PDF, 3 pages | Page-level citations, exact codes (`E-4471`) |

## Load it

With the stack running (`docker compose up --build --wait`):

```bash
python scripts/seed_demo.py          # creates demo@example.com and uploads the four files
python scripts/seed_demo.py --ask    # ...and then asks the sample questions below
```

The script uses only the Python standard library and can be run again safely (files already
uploaded are skipped). Then sign in at http://localhost:3000 with `demo@example.com` and the
password printed by the script, or upload the files yourself from the Documents page.

## Questions to try

Every answer below can be checked against the document named next to it.

| Question | Expected answer | Source |
|---|---|---|
| How often must I change my password? | Every 90 days, 14+ characters | security policy |
| How quickly must a lost laptop be reported? | Within 4 hours, to security@northwind.example | security policy |
| How much parental leave does the second parent get? | 6 weeks at full pay | leave and benefits |
| How many unused leave days can I carry over, and until when? | 5 days, until 31 March | leave and benefits |
| What is the hotel limit per night? | EUR 140 (EUR 190 in listed cities) | remote work and travel |
| How soon must expense claims be submitted? | Within 30 days | remote work and travel |
| What does error E-4471 mean, and how do I reset it? | Low suction pressure; hold RESET for 5 seconds | field manual (PDF page 3) |
| How often are the bearings greased, and with what? | Every 500 operating hours, grease G-12 | field manual (PDF page 2) |
| What is the maximum operating pressure? | 8.5 bar | field manual (PDF page 1) |

Questions that **should be refused** ("I couldn't find this in your documents."), which is the
point of grounding:

* What is the CEO's favourite colour?
* How many days of leave do employees get in France? (the documents do not say)

Questions that show the retrieval design:

* *"login secret rotation"* finds the password rule although the words differ (embeddings).
* *"E-4471"* is found by the exact code (full-text search in the hybrid mix).
* Ask in one chat, then sign in as a second user: they see none of these documents (isolation).
