import { describe, expect, it } from "vitest";

import { SseParser, readEvents } from "./sse";

describe("SseParser", () => {
  it("parses a complete event", () => {
    const events = new SseParser().push('event: token\ndata: {"text":"Hi"}\n\n');
    expect(events).toEqual([{ event: "token", data: '{"text":"Hi"}' }]);
  });

  it("holds back an event until its blank line arrives", () => {
    const parser = new SseParser();
    expect(parser.push("event: token\nda")).toEqual([]);
    expect(parser.push('ta: {"text":"a"}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([{ event: "token", data: '{"text":"a"}' }]);
  });

  it("returns several events from one chunk, in order", () => {
    const events = new SseParser().push("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");
    expect(events.map((e) => e.event)).toEqual(["a", "b"]);
  });

  it("handles CRLF line endings, even split across chunks", () => {
    const parser = new SseParser();
    expect(parser.push("event: a\r\ndata: 1\r\n\r")).toEqual([]);
    expect(parser.push("\n")).toEqual([{ event: "a", data: "1" }]);
  });

  it("does not mistake a split CRLF for a blank line", () => {
    const parser = new SseParser();
    expect(parser.push("event: a\r\ndata: 1\r")).toEqual([]);
    expect(parser.push("\ndata: 2\r\n\r\n")).toEqual([{ event: "a", data: "1\n2" }]);
  });

  it("joins multi-line data and ignores comments", () => {
    const events = new SseParser().push(": keep-alive\n\nevent: a\ndata: one\ndata: two\n\n");
    expect(events).toEqual([{ event: "a", data: "one\ntwo" }]);
  });

  it("defaults the event name to message", () => {
    expect(new SseParser().push("data: x\n\n")).toEqual([{ event: "message", data: "x" }]);
  });

  it("keeps non-ASCII text intact", () => {
    const events = new SseParser().push('event: token\ndata: {"text":"héllo — 你好"}\n\n');
    expect(JSON.parse(events[0]!.data)).toEqual({ text: "héllo — 你好" });
  });
});

describe("readEvents", () => {
  it("reassembles events when a multi-byte character is split across network chunks", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"你好"}\n\n');
    const cut = bytes.indexOf(0xe4) + 1; // inside the first CJK character
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut));
        controller.enqueue(bytes.slice(cut));
        controller.close();
      },
    });
    const seen: string[] = [];
    for await (const event of readEvents(stream)) seen.push(JSON.parse(event.data).text);
    expect(seen).toEqual(["你好"]);
  });
});
