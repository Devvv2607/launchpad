import assert from "node:assert/strict";
import { test } from "node:test";

import { applyEvent, emptyRun, foldEvents, replyText } from "./events.ts";

const log = [
  { seq: 1, type: "run_started", data: { run_id: "r", thread_id: "t", message: "hi" } },
  {
    seq: 2,
    type: "plan",
    data: {
      goal: "Launch",
      steps: [{ id: 1, title: "Write", tool: "write_content", status: "pending" }],
    },
  },
  { seq: 3, type: "step_started", data: { key: "think_1", label: "Thinking" } },
  { seq: 4, type: "token", data: { text: "Writing drafts now.", final: false } },
  {
    seq: 5,
    type: "tool_call",
    data: { id: "c1", tool: "write_content", input: { channel: "instagram_post" } },
  },
  {
    seq: 6,
    type: "research",
    data: { query: "q", sources: [{ title: "T", url: "https://example.in" }] },
  },
  {
    seq: 7,
    type: "item_created",
    data: { item_id: "i1", channel: "instagram_post", preview: "Hello", label: "A" },
  },
  {
    seq: 8,
    type: "tool_result",
    data: { id: "c1", tool: "write_content", ok: true, duration_ms: 1200, output: "{}" },
  },
  {
    seq: 9,
    type: "approval_required",
    data: {
      items: [{ item_id: "i1", channel: "instagram_post", preview: "Hello" }],
      final: "Done: A",
    },
  },
];

test("replays a run up to the approval pause", () => {
  const v = foldEvents(log);
  assert.equal(v.status, "awaiting_approval");
  assert.equal(v.lastSeq, 9);
  assert.equal(v.goal, "Launch");
  assert.deepEqual(
    v.tools.map((t) => [t.tool, t.status, t.durationMs]),
    [["write_content", "ok", 1200]],
  );
  assert.equal(v.drafts.length, 1);
  assert.equal(v.sources[0].sources[0].url, "https://example.in");
  assert.equal(v.approval?.[0].item_id, "i1");
  assert.equal(replyText(v), "Done: A");
});

test("ignores events it has already seen (replay + live overlap)", () => {
  const v = foldEvents(log);
  const again = applyEvent(v, "token", { text: "dupe" }, 4);
  assert.equal(again, v);
});

test("resume then finish clears the approval and records the summary", () => {
  let v = foldEvents(log);
  v = applyEvent(v, "approvals_applied", { approved: 1, rejected: 0, edited: 0, skipped: 0 }, 10);
  assert.equal(v.approval, undefined);
  v = applyEvent(v, "run_finished", { status: "finished", cost_usd: "0.0021", tokens: 900 }, 11);
  assert.equal(v.status, "finished");
  assert.equal(v.applied?.approved, 1);
  assert.equal(v.costUsd, "0.0021");
  assert.equal(v.costComplete, undefined);
  const unpriced = applyEvent(v, "run_finished", { status: "finished", cost_complete: false }, 12);
  assert.equal(unpriced.costComplete, false);
});

test("refusals and stop reasons become the reply", () => {
  const refused = applyEvent(emptyRun(), "plan", { refused: true, reply: "Can't help" }, 1);
  assert.equal(replyText(refused), "Can't help");
  let v = applyEvent(emptyRun(), "token", { text: "Checking the brand kit" }, 1);
  v = applyEvent(v, "run_finished", { status: "budget_exceeded", final: "Stopped: budget" }, 2);
  assert.equal(replyText(v), "Stopped: budget");
  assert.equal(v.outcome, "budget_exceeded");
});

test("a tool still running when the run ends is marked failed", () => {
  let v = applyEvent(emptyRun(), "tool_call", { id: "c", tool: "plan_campaign", input: {} }, 1);
  v = applyEvent(v, "run_finished", { status: "cancelled" }, 2);
  assert.equal(v.status, "cancelled");
  assert.equal(v.tools[0].status, "error");
});
