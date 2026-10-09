import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";
import { createRenderer, sendFormatted, type TelegramApiLike } from "../src/telegram/renderer.ts";
function fake(parseError = false) {
  const sends: any[] = [],
    edits: any[] = [],
    actions: any[] = [],
    reactions: any[] = [];
  let n = 0;
  const api: TelegramApiLike = {
    async sendMessage(...a: any[]) {
      sends.push(a);
      if (parseError && a[2]?.parse_mode) throw new Error("400 can't parse entities");
      return { message_id: ++n };
    },
    async editMessageText(...a: any[]) {
      edits.push(a);
    },
    async sendChatAction(...a: any[]) {
      actions.push(a);
    },
    async setMessageReaction(...a: any[]) {
      reactions.push(a);
    },
  };
  return { api, sends, edits, actions, reactions };
}
const route = { chatId: "-100", topicId: "8" };
const config = (extra: Record<string, string> = {}) =>
  loadConfig({ TELEGRAM_BOT_TOKEN: "x", LETTA_API_KEY: "y", LETTA_AGENT_ID: "agent-1", ...extra });
describe("renderer", () => {
  test("parse errors retry as plain text without parse_mode", async () => {
    const f = fake(true);
    await sendFormatted(f.api, route, "**hello**", "3");
    expect(f.sends).toHaveLength(2);
    expect(f.sends[0][2].parse_mode).toBe("HTML");
    expect(f.sends[1][2].parse_mode).toBeUndefined();
    expect(f.sends[1][1]).toBe("**hello**");
  });
  test("passes topic and reply parameters", async () => {
    const f = fake();
    await sendFormatted(f.api, route, "hello", "3");
    expect(f.sends[0][2]).toMatchObject({
      message_thread_id: 8,
      reply_parameters: { message_id: 3, allow_sending_without_reply: true },
    });
  });
  test("renders tool progress and lifecycle", async () => {
    const f = fake(),
      r = createRenderer(f.api, config({ SHOW_TOOL_CALLS: "true", LIFECYCLE_REACTIONS: "true" }), route, "3");
    await r({ kind: "started", conversationId: "c", createdConversation: false });
    await r({ kind: "tool_call", toolCallId: "t", toolName: "Bash", summary: "Run tests" });
    await r({ kind: "tool_result", toolCallId: "t", isError: false });
    await r({ kind: "assistant_delta", text: "done" });
    await r({ kind: "done", success: true, durationMs: 1 });
    expect(f.actions.length).toBeGreaterThan(0);
    expect(f.sends.some((x) => String(x[1]).includes("Run tests"))).toBe(true);
    expect(f.edits.some((x) => String(x[2]).includes("✓"))).toBe(true);
    expect(f.reactions[0][2][0].emoji).toBe("👌");
  });
});
