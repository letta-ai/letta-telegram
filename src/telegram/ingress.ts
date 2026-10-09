import type { Config } from "../config.ts";
import type { InboundMessage, ReplyTarget, RouteKey } from "../types.ts";
import { COMMANDS } from "./commands.ts";

export interface TelegramMessageLike {
  message_id: number;
  date: number;
  message_thread_id?: number;
  is_topic_message?: boolean;
  media_group_id?: string;
  text?: string;
  caption?: string;
  quote?: { text?: string };
  chat: { id: number; type: string; title?: string };
  from?: { id: number; is_bot: boolean; username?: string; first_name: string; last_name?: string };
  entities?: { type: string; offset: number; length: number; user?: { id: number } }[];
  caption_entities?: TelegramMessageLike["entities"];
  reply_to_message?: TelegramMessageLike;
  migrate_to_chat_id?: number;
  forum_topic_created?: unknown;
}
export type GateDecision =
  { accept: true; route: RouteKey; mentioned: boolean } | { accept: false; reason: string; refuse?: boolean };

export const isPrivate = (m: TelegramMessageLike) => m.chat.type === "private";
export function routeFor(m: TelegramMessageLike): RouteKey {
  return {
    chatId: String(m.chat.id),
    topicId: m.is_topic_message && m.message_thread_id !== undefined ? String(m.message_thread_id) : null,
    ...(isPrivate(m) && m.from ? { userId: String(m.from.id) } : {}),
  };
}
export function isAdminUser(c: Config, id: string) {
  return c.TELEGRAM_ADMIN_USER_IDS.includes(id);
}
export function surfaceDenial(c: Config, m: TelegramMessageLike): string | null {
  const uid = String(m.from?.id ?? "");
  if (isPrivate(m)) {
    if (c.DM_POLICY === "off") return "dm-off";
    if (c.DM_POLICY === "allowlist" && !isAdminUser(c, uid) && !c.TELEGRAM_ALLOWED_USER_IDS.includes(uid))
      return "dm-not-allowlisted";
  } else {
    if (c.GROUP_POLICY === "off") return "group-off";
    if (c.GROUP_POLICY === "allowlist" && !c.TELEGRAM_GROUP_IDS.includes(String(m.chat.id)))
      return "group-not-allowlisted";
    if (
      !isAdminUser(c, uid) &&
      c.TELEGRAM_ALLOWED_USER_IDS.length &&
      !c.TELEGRAM_ALLOWED_USER_IDS.includes(uid)
    )
      return "user-not-allowed";
  }
  return null;
}
/** Telegram entity offsets are UTF-16 code units, exactly matching JavaScript string indices. */
function entityText(text: string, e: { offset: number; length: number }) {
  return text.slice(e.offset, e.offset + e.length);
}
/**
 * The message this one replies to, ignoring the implicit reply Telegram adds
 * to every forum-topic message (it points at the topic's creation message).
 */
export function explicitReply(m: TelegramMessageLike): TelegramMessageLike | undefined {
  const r = m.reply_to_message;
  if (!r) return undefined;
  if (r.forum_topic_created !== undefined) return undefined;
  if (m.is_topic_message && r.message_id === m.message_thread_id) return undefined;
  return r;
}

const OWN_COMMANDS = new Set(COMMANDS.map((c) => c.command));

/**
 * A leading bot command addressed to this bot: `/anything@thisbot`, or a bare
 * `/command` that this bot defines. Bare unknown commands belong to other bots.
 */
export function commandForBot(text: string, username: string): { name: string; explicit: boolean } | null {
  const match = /^\/([a-z0-9_]+)(?:@([a-z0-9_]+))?(?:\s|$)/i.exec(text);
  if (!match) return null;
  const name = match[1]!.toLowerCase();
  const target = match[2]?.toLowerCase();
  if (target) return target === username.toLowerCase() ? { name, explicit: true } : null;
  return OWN_COMMANDS.has(name) ? { name, explicit: false } : null;
}

export function addressed(m: TelegramMessageLike, botId: string, username: string): boolean {
  const text = m.text ?? m.caption ?? "";
  const entities = m.entities ?? m.caption_entities ?? [];
  if (
    entities.some(
      (e) => e.type === "mention" && entityText(text, e).toLowerCase() === `@${username.toLowerCase()}`,
    )
  )
    return true;
  if (entities.some((e) => e.type === "text_mention" && String(e.user?.id) === botId)) return true;
  if (String(explicitReply(m)?.from?.id ?? "") === botId) return true;
  return commandForBot(text, username) !== null;
}
export function gate(c: Config, m: TelegramMessageLike, botId: string, username: string): GateDecision {
  if (!m.from || m.from.is_bot || String(m.from.id) === botId) return { accept: false, reason: "bot" };
  const denial = surfaceDenial(c, m);
  if (denial) return { accept: false, reason: denial, refuse: isPrivate(m) };
  const mentioned = addressed(m, botId, username);
  if (!isPrivate(m) && !c.TELEGRAM_OPEN_CHAT_IDS.includes(String(m.chat.id)) && !mentioned)
    return { accept: false, reason: "not-addressed" };
  return { accept: true, route: routeFor(m), mentioned };
}
export function stripMention(
  text: string,
  entities: TelegramMessageLike["entities"],
  username: string,
): string {
  const own = (entities ?? [])
    .filter((e) => e.type === "mention" && entityText(text, e).toLowerCase() === `@${username.toLowerCase()}`)
    .sort((a, b) => b.offset - a.offset);
  let result = text;
  for (const e of own) result = result.slice(0, e.offset) + result.slice(e.offset + e.length);
  return result.trim();
}
function replyTarget(m: TelegramMessageLike, botId: string): ReplyTarget | undefined {
  const r = explicitReply(m);
  if (!r?.from) return undefined;
  let text = (r.text ?? r.caption ?? mediaPlaceholder(r)).replace(/\s+/g, " ").slice(0, 600);
  if (m.quote?.text) text = `Quote: ${m.quote.text.slice(0, 300)}\n${text}`;
  return {
    messageId: String(r.message_id),
    authorId: String(r.from.id),
    authorName: [r.from.first_name, r.from.last_name].filter(Boolean).join(" "),
    authorIsBot: r.from.is_bot,
    own: String(r.from.id) === botId,
    text,
  };
}
function mediaPlaceholder(m: TelegramMessageLike) {
  return Object.keys(m).some((k) =>
    ["photo", "document", "audio", "video", "voice", "animation", "sticker"].includes(k),
  )
    ? "[media]"
    : "";
}
export function normalizeText(
  m: TelegramMessageLike,
  route: RouteKey,
  botId: string,
  username: string,
): InboundMessage {
  const from = m.from!;
  const raw = m.text ?? m.caption ?? "";
  const reply = replyTarget(m, botId);
  return {
    route,
    messageId: String(m.message_id),
    authorId: String(from.id),
    authorName:
      [from.first_name, from.last_name].filter(Boolean).join(" ") || from.username || String(from.id),
    authorIsBot: false,
    text: stripMention(raw, m.entities ?? m.caption_entities, username),
    createdAt: new Date(m.date * 1000).toISOString(),
    ...(explicitReply(m) ? { replyToMessageId: String(explicitReply(m)!.message_id) } : {}),
    ...(reply ? { replyTo: reply } : {}),
    images: [],
    files: [],
  };
}
export class Deduper {
  private seen = new Map<string, number>();
  constructor(private ttl = 60_000) {}
  firstTime(id: string, now = Date.now()) {
    for (const [k, t] of this.seen) if (now - t > this.ttl) this.seen.delete(k);
    if (this.seen.has(id)) return false;
    this.seen.set(id, now);
    return true;
  }
  forget(id: string) {
    this.seen.delete(id);
  }
}
export class Debouncer<T> {
  private p = new Map<string, { v: T[]; t: ReturnType<typeof setTimeout> }>();
  constructor(
    private ms: number,
    private flush: (k: string, v: T[]) => void,
  ) {}
  push(k: string, v: T) {
    if (this.ms <= 0) return this.flush(k, [v]);
    const x = this.p.get(k);
    if (x) {
      clearTimeout(x.t);
      x.v.push(v);
      x.t = setTimeout(() => this.fire(k), this.ms);
    } else this.p.set(k, { v: [v], t: setTimeout(() => this.fire(k), this.ms) });
  }
  private fire(k: string) {
    const x = this.p.get(k);
    if (x) {
      this.p.delete(k);
      this.flush(k, x.v);
    }
  }
  clear() {
    let n = 0;
    for (const x of this.p.values()) {
      clearTimeout(x.t);
      n += x.v.length;
    }
    this.p.clear();
    return n;
  }
}
