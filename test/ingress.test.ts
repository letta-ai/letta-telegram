import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";
import {
  addressed,
  gate,
  routeFor,
  stripMention,
  type TelegramMessageLike,
} from "../src/telegram/ingress.ts";
const config = (extra: Record<string, string> = {}) =>
  loadConfig({
    TELEGRAM_BOT_TOKEN: "x",
    LETTA_API_KEY: "y",
    LETTA_AGENT_ID: "agent-1",
    TELEGRAM_ADMIN_USER_IDS: "1",
    TELEGRAM_GROUP_IDS: "-100",
    ...extra,
  });
const msg = (over: Partial<TelegramMessageLike> = {}): TelegramMessageLike => ({
  message_id: 1,
  date: 1,
  chat: { id: -100, type: "supergroup" },
  from: { id: 2, is_bot: false, first_name: "A" },
  text: "hi",
  ...over,
});
describe("Telegram ingress", () => {
  test("routes private chats, groups, and only real forum topics", () => {
    expect(routeFor(msg({ chat: { id: 2, type: "private" } }))).toEqual({
      chatId: "2",
      topicId: null,
      userId: "2",
    });
    expect(routeFor(msg({ message_thread_id: 7, is_topic_message: false }))).toEqual({
      chatId: "-100",
      topicId: null,
    });
    expect(routeFor(msg({ message_thread_id: 7, is_topic_message: true }))).toEqual({
      chatId: "-100",
      topicId: "7",
    });
  });
  test("mention handles Telegram UTF-16 offsets", () => {
    const text = "😀 hi @MyBot";
    const m = msg({ text, entities: [{ type: "mention", offset: 6, length: 6 }] });
    expect(addressed(m, "9", "mybot")).toBe(true);
    expect(stripMention(text, m.entities, "mybot")).toBe("😀 hi");
  });
  test("text mention, reply, and addressed commands", () => {
    expect(
      addressed(
        msg({ entities: [{ type: "text_mention", offset: 0, length: 2, user: { id: 9 } }] }),
        "9",
        "mybot",
      ),
    ).toBe(true);
    expect(
      addressed(
        msg({ reply_to_message: msg({ from: { id: 9, is_bot: true, first_name: "B" } }) }),
        "9",
        "mybot",
      ),
    ).toBe(true);
    expect(addressed(msg({ text: "/status@MyBot" }), "9", "mybot")).toBe(true);
    expect(addressed(msg({ text: "/status@Other" }), "9", "mybot")).toBe(false);
  });
  test("DM and group policies precede addressing", () => {
    expect(gate(config(), msg({ chat: { id: 2, type: "private" } }), "9", "mybot")).toMatchObject({
      accept: false,
      refuse: true,
    });
    expect(
      gate(config({ DM_POLICY: "open" }), msg({ chat: { id: 2, type: "private" } }), "9", "mybot"),
    ).toMatchObject({ accept: true });
    expect(
      gate(
        config(),
        msg({
          chat: { id: -200, type: "group" },
          text: "@mybot hi",
          entities: [{ type: "mention", offset: 0, length: 6 }],
        }),
        "9",
        "mybot",
      ),
    ).toMatchObject({ accept: false });
    expect(
      gate(
        config({ GROUP_POLICY: "open" }),
        msg({
          chat: { id: -200, type: "group" },
          text: "@mybot hi",
          entities: [{ type: "mention", offset: 0, length: 6 }],
        }),
        "9",
        "mybot",
      ),
    ).toMatchObject({ accept: true });
  });
  test("bots are ignored", () =>
    expect(
      gate(
        config({ GROUP_POLICY: "open" }),
        msg({ from: { id: 3, is_bot: true, first_name: "bot" } }),
        "9",
        "mybot",
      ),
    ).toMatchObject({ accept: false, reason: "bot" }));
});
