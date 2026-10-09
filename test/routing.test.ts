import { describe, expect, test } from "bun:test";
import { parseRoutingTable, pinnedConversations, policyFor, resolveRoute } from "../src/routing.ts";
import type { RouteKey } from "../src/types.ts";
const table = parseRoutingTable(
  JSON.stringify({
    routes: [
      { chat: "-100", topic: "12", conversation: "conv-topic" },
      { chat: "-100", conversation: "conv-chat" },
      { chat: "-200", conversation: "auto" },
      { user: "7", conversation: "default" },
    ],
  }),
);
const r = (chatId: string, topicId: string | null = null, userId?: string): RouteKey => ({
  chatId,
  topicId,
  ...(userId ? { userId } : {}),
});
describe("routing", () => {
  test("topic then chat then user specificity", () => {
    expect(resolveRoute(table, r("-100", "12"))).toEqual({
      kind: "pinned",
      conversationId: "conv-topic",
      rule: "topic:-100:12",
    });
    expect(resolveRoute(table, r("-100"))).toMatchObject({ conversationId: "conv-chat" });
    expect(resolveRoute(table, r("7", null, "7"))).toMatchObject({ conversationId: "default" });
  });
  test("auto and fallback", () => {
    expect(resolveRoute(table, r("-200"))).toEqual({ kind: "auto" });
    const f = parseRoutingTable(JSON.stringify({ fallback: "default" }));
    expect(resolveRoute(f, r("1"))).toMatchObject({ conversationId: "default" });
    expect(resolveRoute(null, r("1"))).toEqual({ kind: "auto" });
  });
  test("lists pins", () =>
    expect(pinnedConversations(table)).toEqual(["conv-topic", "conv-chat", "default"]));
  test("validates Telegram ids, duplicates and shape", () => {
    expect(() =>
      parseRoutingTable(JSON.stringify({ routes: [{ chat: "abc", conversation: "default" }] })),
    ).toThrow(/Telegram id/);
    expect(() =>
      parseRoutingTable(
        JSON.stringify({
          routes: [
            { chat: "1", conversation: "default" },
            { chat: "1", conversation: "default" },
          ],
        }),
      ),
    ).toThrow(/duplicate chat/);
    expect(() =>
      parseRoutingTable(JSON.stringify({ routes: [{ topic: "1", conversation: "default" }] })),
    ).toThrow();
  });
});
describe("policy", () => {
  const env = {
    ALLOWED_TOOLS: [] as string[],
    TOOLSET_BASE: undefined,
    PERMISSION_MODE: "unrestricted" as const,
    APPROVAL_MODE: "allow" as const,
  };
  const t = parseRoutingTable(
    JSON.stringify({
      policy: { permissionMode: "standard" },
      routes: [
        { chat: "-100", policy: { toolset: "none", approvalMode: "requester" } },
        { chat: "-100", topic: "12", policy: { allowedTools: ["Read"] } },
        { user: "7", policy: { permissionMode: "strict" } },
      ],
    }),
  );
  test("layers fields independently", () =>
    expect(policyFor(env, t, r("-100", "12"))).toEqual({
      allowedTools: ["Read"],
      toolset: "none",
      permissionMode: "standard",
      approvalMode: "requester",
    }));
  test("user policies apply to private routes", () =>
    expect(policyFor(env, t, r("7", null, "7"))).toMatchObject({ permissionMode: "strict" }));
});
