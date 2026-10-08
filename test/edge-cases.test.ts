import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";
import { RouteStore } from "../src/letta/store.ts";
import { startTelegram } from "../src/telegram/gateway.ts";
import { addressed, normalizeText, routeFor, type TelegramMessageLike } from "../src/telegram/ingress.ts";
import { createRenderer, type TelegramApiLike } from "../src/telegram/renderer.ts";
import type { AgentBridge, InboundMessage } from "../src/types.ts";

const BOT_ID = "99";

const cfg = (extra: Record<string, string> = {}) =>
  loadConfig({
    TELEGRAM_BOT_TOKEN: "token",
    LETTA_API_KEY: "key",
    LETTA_AGENT_ID: "agent-1",
    TELEGRAM_ADMIN_USER_IDS: "7",
    TELEGRAM_GROUP_IDS: "-100",
    DEBOUNCE_MS: "0",
    REGISTER_COMMANDS: "false",
    HEALTH_PORT: "0",
    ...extra,
  });

class FakeBot {
  botInfo = { id: 99, is_bot: true, first_name: "Bot", username: "mybot" };
  handlers = new Map<string, (ctx: any) => Promise<void>>();
  sent: any[] = [];
  getFile: () => Promise<{ file_path: string }> = async () => ({ file_path: "f" });
  api = {
    setMyCommands: async () => {},
    sendMessage: async (...a: any[]) => {
      this.sent.push(a);
      return { message_id: 1 };
    },
    editMessageText: async () => {},
    answerCallbackQuery: async () => {},
    sendChatAction: async () => {},
    setMessageReaction: async () => {},
    getFile: () => this.getFile(),
  };
  async init() {}
  on(name: string, fn: (ctx: any) => Promise<void>) {
    this.handlers.set(name, fn);
    return this;
  }
  catch() {}
  async start() {}
  async stop() {}
  message(m: any) {
    return this.handlers.get("message")!({ message: m });
  }
}

function fakeBridge() {
  const batches: InboundMessage[][] = [];
  const b: AgentBridge = {
    async submit(batch) {
      batches.push(batch);
    },
    async cancel() {
      return false;
    },
    async reset() {
      return "reset";
    },
    async status() {
      return { busy: false, queued: 0, hasConversation: false };
    },
    onBackground() {},
    async shutdown() {},
  };
  return { b, batches };
}

const group = (over: Record<string, unknown> = {}): TelegramMessageLike =>
  ({
    message_id: 50,
    date: 1,
    chat: { id: -100, type: "supergroup" },
    from: { id: 7, is_bot: false, first_name: "A" },
    text: "hello",
    ...over,
  }) as TelegramMessageLike;

describe("forum topics", () => {
  // Telegram sets reply_to_message on every topic message, pointing at the
  // forum_topic_created service message that opened the topic.
  const topicRoot = {
    message_id: 12,
    date: 1,
    chat: { id: -100, type: "supergroup" },
    from: { id: 99, is_bot: true, first_name: "Bot" },
    forum_topic_created: { name: "Ideas", icon_color: 1 },
  };
  const inTopic = group({ message_thread_id: 12, is_topic_message: true, reply_to_message: topicRoot });

  test("the implicit topic-root reply is not a reply to the bot", () => {
    expect(addressed(inTopic, BOT_ID, "mybot")).toBe(false);
  });

  test("the implicit topic-root reply adds no reply context", () => {
    const inbound = normalizeText(inTopic, routeFor(inTopic), BOT_ID, "mybot");
    expect(inbound.replyTo).toBeUndefined();
    expect(inbound.replyToMessageId).toBeUndefined();
  });

  test("a real reply to the bot inside a topic still counts", () => {
    const real = group({
      message_thread_id: 12,
      is_topic_message: true,
      reply_to_message: { ...topicRoot, message_id: 40, forum_topic_created: undefined, text: "earlier" },
    });
    expect(addressed(real, BOT_ID, "mybot")).toBe(true);
  });
});

describe("commands in groups", () => {
  test("only this bot's own commands address it", () => {
    expect(addressed(group({ text: "/shrug" }), BOT_ID, "mybot")).toBe(false);
    expect(addressed(group({ text: "/new@otherbot" }), BOT_ID, "mybot")).toBe(false);
    expect(addressed(group({ text: "/new" }), BOT_ID, "mybot")).toBe(true);
    expect(addressed(group({ text: "/status@MyBot" }), BOT_ID, "mybot")).toBe(true);
  });
});

describe("gateway", () => {
  test("an unknown slash command in a DM reaches the agent", async () => {
    const bot = new FakeBot(),
      x = fakeBridge();
    await startTelegram(cfg(), x.b, new RouteStore(":memory:"), bot as never);
    await bot.message({ ...group({ text: "/summarize this" }), chat: { id: 7, type: "private" } });
    await Bun.sleep(10);
    expect(x.batches.flat().map((m) => m.text)).toEqual(["/summarize this"]);
    expect(bot.sent).toHaveLength(0);
  });

  test("group migration renames routes even when the actor is not on the user allowlist", async () => {
    const bot = new FakeBot(),
      store = new RouteStore(":memory:");
    store.set("-100:-", "conv-1");
    await startTelegram(cfg({ TELEGRAM_ALLOWED_USER_IDS: "1" }), fakeBridge().b, store, bot as never);
    await bot.message(
      group({ text: undefined, migrate_to_chat_id: -1009, from: { id: 8, is_bot: false, first_name: "B" } }),
    );
    expect(store.get("-1009:-")?.conversationId).toBe("conv-1");
    expect(store.get("-100:-")).toBeNull();
  });

  test("a slow media download does not hold the update loop", async () => {
    const bot = new FakeBot();
    let release!: () => void;
    bot.getFile = () =>
      new Promise((resolve) => {
        release = () => resolve({ file_path: "f" });
      });
    await startTelegram(cfg(), fakeBridge().b, new RouteStore(":memory:"), bot as never);
    const handled = bot.message(
      group({
        text: undefined,
        caption: "@mybot look",
        caption_entities: [{ type: "mention", offset: 0, length: 6 }],
        document: { file_id: "d", file_size: 10 },
      }),
    );
    const outcome = await Promise.race([
      handled.then(() => "returned"),
      Bun.sleep(100).then(() => "blocked"),
    ]);
    release?.();
    expect(outcome).toBe("returned");
  });
});

describe("streaming renderer", () => {
  test("done during the first streamed send does not post the reply twice", async () => {
    const sends: any[] = [];
    let releaseFirst!: () => void;
    const api: TelegramApiLike = {
      async sendMessage(...a: any[]) {
        sends.push(a);
        if (sends.length === 1) await new Promise<void>((r) => (releaseFirst = r));
        return { message_id: sends.length };
      },
      async editMessageText() {},
      async sendChatAction() {},
    };
    const render = createRenderer(api, cfg({ STREAM_EDITS: "true" }), { chatId: "7", topicId: null }, "5");
    await render({ kind: "started" } as never);
    await render({ kind: "assistant_delta", text: "hello" } as never);
    await Bun.sleep(10); // the stream timer fires and the first send is now in flight
    const done = render({ kind: "done", success: true } as never);
    await Bun.sleep(10);
    releaseFirst();
    await done;
    await Bun.sleep(10);
    expect(sends).toHaveLength(1);
  });
});
