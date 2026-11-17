/**
 * A minimal Server-Sent Events reader for `fetch` responses.
 *
 * `EventSource` can't be used: it only issues GET requests and can't send an Authorization
 * header, and the chat stream is a POST with a bearer token.
 *
 * The wire format (see backend `app/api/sse.py`) is `event: <name>\ndata: <json>\n\n`.
 */

export type SseEvent = { event: string; data: string };

/** Incremental parser: feed it text chunks as they arrive, get back the complete events. */
export class SseParser {
  private buffer = "";
  /** A chunk may end between the "\r" and "\n" of one line ending: wait for the next chunk. */
  private heldCarriageReturn = false;

  push(chunk: string): SseEvent[] {
    let text = (this.heldCarriageReturn ? "\r" : "") + chunk;
    this.heldCarriageReturn = text.endsWith("\r");
    if (this.heldCarriageReturn) text = text.slice(0, -1);
    // Normalise line endings so the rest only deals with "\n".
    this.buffer += text.replace(/\r\n?/g, "\n");
    const events: SseEvent[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const parsed = parseBlock(block);
      if (parsed) events.push(parsed);
      boundary = this.buffer.indexOf("\n\n");
    }
    return events;
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // blank line or comment (keep-alive)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/** Read a response body as a stream of SSE events. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode());
  } finally {
    reader.releaseLock();
  }
}
