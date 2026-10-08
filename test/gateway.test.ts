import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";
import { RouteStore } from "../src/letta/store.ts";
import { startTelegram } from "../src/telegram/gateway.ts";
import type { AgentBridge, InboundMessage, RouteKey } from "../src/types.ts";
class FakeBot {
  botInfo = { id: 99, is_bot: true, first_name: "Bot", username: "mybot" };
  handlers = new Map<string, (ctx: any) => Promise<void>>();
  stopped = false;
  api = {
    setMyCommands: async () => {},
    sendMessage: async () => ({ message_id: 1 }),
    editMessageText: async () => {},
    answerCallbackQuery: async () => {},
    sendChatAction: async () => {},
    setMessageReaction: async () => {},
    getFile: async () => ({ file_path: "unused" }),
  };
  async init() {}
  on(name: string, fn: (ctx: any) => Promise<void>) {
    this.handlers.set(name, fn);
    return this;
  }
  catch() {}
  async start() {}
  async stop() {
    this.stopped = true;
  }
  async message(m: any) {
    await this.handlers.get("message")!({ message: m });
  }
}
const cfg = (debounce = "20") =>
  loadConfig({
    TELEGRAM_BOT_TOKEN: "token",
    LETTA_API_KEY: "key",
    LETTA_AGENT_ID: "agent-1",
    TELEGRAM_GROUP_IDS: "-100",
    TELEGRAM_OPEN_CHAT_IDS: "-100",
    DEBOUNCE_MS: debounce,
    REGISTER_COMMANDS: "false",
    HEALTH_PORT: "0",
  });
function bridge() {
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
const m = (id: number, over: Record<string, unknown> = {}) => ({
  message_id: id,
  date: 1,
  chat: { id: -100, type: "supergroup" },
  from: { id: 7, is_bot: false, first_name: "A" },
  text: `m${id}`,
  ...over,
});
describe("Telegram gateway", () => {
  test("deduplicates and debounces by route plus author", async () => {
    const bot = new FakeBot(),
      x = bridge(),
      store = new RouteStore(":memory:");
    const runtime = await startTelegram(cfg(), x.b, store, bot as never);
    await bot.message(m(1));
    await bot.message(m(1));
    await bot.message(m(2));
    await Bun.sleep(35);
    expect(x.batches).toHaveLength(1);
    expect(x.batches[0]!.map((v) => v.messageId)).toEqual(["1", "2"]);
    await runtime.stop();
    store.close();
  });
  test("albums reset the 300 ms timer and dispatch as one batch", async () => {
    const bot = new FakeBot(),
      x = bridge(),
      store = new RouteStore(":memory:");
    const runtime = await startTelegram(cfg("0"), x.b, store, bot as never);
    await bot.message(m(1, { media_group_id: "album" }));
    await Bun.sleep(180);
    await bot.message(m(2, { media_group_id: "album" }));
    await Bun.sleep(180);
    expect(x.batches).toHaveLength(0);
    await Bun.sleep(150);
    expect(x.batches).toHaveLength(1);
    expect(x.batches[0]!.map((v) => v.messageId)).toEqual(["1", "2"]);
    await runtime.stop();
    store.close();
  });
  test("shutdown drops pending debounce and albums", async () => {
    const bot = new FakeBot(),
      x = bridge(),
      store = new RouteStore(":memory:");
    const runtime = await startTelegram(cfg("100"), x.b, store, bot as never);
    await bot.message(m(1));
    await bot.message(m(2, { media_group_id: "album" }));
    await runtime.stop();
    await Bun.sleep(330);
    expect(x.batches).toHaveLength(0);
    expect(bot.stopped).toBe(true);
    store.close();
  });
  test("group migration renames base, topic, and pinned keys", async () => {
    const bot = new FakeBot(),
      x = bridge(),
      store = new RouteStore(":memory:");
    store.set("-100:-", "conv-a");
    store.set("-100:8", "conv-b");
    store.touchPinned("-100:9");
    const runtime = await startTelegram(cfg("0"), x.b, store, bot as never);
    await bot.message(m(3, { text: undefined, migrate_to_chat_id: -200, from: undefined }));
    expect(store.get("-200:-")?.conversationId).toBe("conv-a");
    expect(store.get("-200:8")?.conversationId).toBe("conv-b");
    expect(store.pinnedLastActive("-200:9")).toBeTruthy();
    expect(x.batches).toHaveLength(0);
    await runtime.stop();
    store.close();
  });
});
