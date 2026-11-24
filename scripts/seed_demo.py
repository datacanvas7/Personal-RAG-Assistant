#!/usr/bin/env python3
"""Load the demo dataset into a running Personal RAG Assistant.

Creates (or signs in to) a demo account, uploads every file in ``demo/documents`` through the
public API and waits until each one is ``ready``. It can be run again safely: files that are
already uploaded are skipped.

    python scripts/seed_demo.py                 # against http://localhost:3000/api/v1
    python scripts/seed_demo.py --ask           # then ask the sample questions (needs LLM_API_KEY)

Only the Python standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = ROOT / "demo" / "documents"
DEFAULT_URL = "http://localhost:3000/api/v1"

# A demo account on your own machine. Pick your own credentials for anything shared.
DEFAULT_EMAIL = "demo@example.com"
DEFAULT_PASSWORD = "demo-passphrase-2026"  # noqa: S105 - documented demo credential

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}

# Questions whose answers are in the demo documents (see demo/questions.md).
SAMPLE_QUESTIONS = [
    "How often must I change my password?",
    "How much parental leave does the second parent get?",
    "What does error E-4471 mean and how do I reset it?",
    "What is the hotel limit per night when travelling?",
    "What is the CEO's favourite colour?",  # not in the documents: must be refused
]


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 60,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            data = json.dumps(json_body).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(  # noqa: S310 - the URL is the one the user passed in
            self.base_url + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, _error_message(error.read())) from None
        except urllib.error.URLError as error:
            raise SystemExit(
                f"Cannot reach {self.base_url} ({error.reason}).\n"
                "Is the stack running? Start it with: docker compose up --build --wait"
            ) from None
        return json.loads(body) if body else None


def _error_message(body: bytes) -> str:
    try:
        return str(json.loads(body)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return body.decode(errors="replace")[:200]


def multipart(field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    body = head + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def sign_in(client: Client, email: str, password: str) -> None:
    credentials = {"email": email, "password": password}
    try:
        client.request("POST", "/auth/register", json_body=credentials)
        print(f"Created account {email}")
    except ApiError as error:
        if error.status != 409:
            raise
        print(f"Account {email} already exists, signing in")
    client.token = client.request("POST", "/auth/login", json_body=credentials)["access_token"]


def existing_filenames(client: Client) -> set[str]:
    names: set[str] = set()
    offset = 0
    while True:
        page = client.request("GET", f"/documents?limit=100&offset={offset}")
        names.update(item["filename"] for item in page["items"])
        offset += 100
        if offset >= page["total"]:
            return names


def wait_until_ready(client: Client, document_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = client.request("GET", f"/documents/{document_id}/status")
        if status["status"] in {"ready", "failed"} or time.monotonic() > deadline:
            return status
        time.sleep(2)


def upload_all(client: Client, files: list[Path], timeout: float) -> bool:
    known = existing_filenames(client)
    pending: list[tuple[str, str]] = []
    for path in files:
        if path.name in known:
            print(f"  skip   {path.name} (already uploaded)")
            continue
        body, content_type = multipart("file", path.name, path.read_bytes())
        try:
            document = client.request(
                "POST", "/documents/upload", data=body, content_type=content_type
            )
        except ApiError as error:
            if error.status == 409:
                print(f"  skip   {path.name} ({error})")
                continue
            raise
        print(f"  upload {path.name}")
        pending.append((path.name, document["id"]))

    ok = True
    if pending:
        print("Waiting for processing (the first run downloads the embedding model, ~130 MB)...")
    for name, document_id in pending:
        status = wait_until_ready(client, document_id, timeout)
        if status["status"] == "ready":
            print(f"  ready  {name}: {status['total_chunks']} passages")
        else:
            ok = False
            print(f"  {status['status']:<6} {name}: {status.get('error_message') or 'timed out'}")
    return ok


def ask_samples(client: Client) -> None:
    print("\nAsking the sample questions (needs LLM_API_KEY in .env):")
    for question in SAMPLE_QUESTIONS:
        print(f"\nQ: {question}")
        try:
            reply = client.request("POST", "/ask", json_body={"question": question}, timeout=120)
        except ApiError as error:
            print(f"   {error}")
            if error.status == 503:
                print("   No language model is configured; see the README (Gemini key).")
                return
            continue
        print(f"A: {reply['answer']}")
        for source in reply["sources"]:
            page = f", page {source['page_number']}" if source["page_number"] else ""
            print(f"   [{source['number']}] {source['filename']}{page}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=DEFAULT_URL, help=f"API base URL (default {DEFAULT_URL})")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS, help="folder to upload")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait per document")
    parser.add_argument("--ask", action="store_true", help="ask the sample questions afterwards")
    args = parser.parse_args()

    files = sorted(p for p in args.docs.iterdir() if p.suffix.lower() in SUPPORTED)
    if not files:
        raise SystemExit(f"No supported files in {args.docs}")

    client = Client(args.url)
    sign_in(client, args.email, args.password)
    print(f"Uploading {len(files)} files from {args.docs}")
    ok = upload_all(client, files, args.timeout)
    if ok:
        print(f"\nDone. Sign in at the frontend with {args.email} / {args.password}")
    if ok and args.ask:
        ask_samples(client)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
