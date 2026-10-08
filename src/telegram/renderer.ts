import type { Config, ReplyMode } from "../config.ts";
import { log } from "../log.ts";
import type { RouteKey, TurnEvent } from "../types.ts";
import { markdownToHtml, splitMarkdown } from "./format.ts";
const LIFECYCLE_EMOJI = new Set(["👌", "💔", "🤷"]);

export interface TelegramApiLike {
  sendMessage(chat: string, text: string, options?: Record<string, unknown>): Promise<{ message_id: number }>;
  editMessageText(
    chat: string,
    id: number,
    text: string,
    options?: Record<string, unknown>,
  ): Promise<unknown>;
  sendChatAction(chat: string, action: "typing", options?: Record<string, unknown>): Promise<unknown>;
  setMessageReaction?(
    chat: string,
    id: number,
    reactions: { type: "emoji"; emoji: string }[],
  ): Promise<unknown>;
  deleteMessage?(chat: string, id: number): Promise<unknown>;
}
const blocked = new Set<string>();
async function safe<T>(chat: string, action: () => Promise<T>): Promise<T | undefined> {
  try {
    return await action();
  } catch (error) {
    const text = String(error);
    if (/403|blocked|kicked/i.test(text)) {
      if (!blocked.has(chat)) {
        blocked.add(chat);
        log.warn("Telegram delivery unavailable", { chat });
      }
      return;
    }
    throw error;
  }
}
export async function sendFormatted(
  api: TelegramApiLike,
  route: RouteKey,
  text: string,
  reply?: string,
): Promise<{ message_id: number }[]> {
  const sent: { message_id: number }[] = [];
  let first = true;
  for (const source of splitMarkdown(text)) {
    const options: Record<string, unknown> = {
      parse_mode: "HTML",
      ...(route.topicId ? { message_thread_id: Number(route.topicId) } : {}),
      ...(first && reply
        ? { reply_parameters: { message_id: Number(reply), allow_sending_without_reply: true } }
        : {}),
    };
    try {
      const m = await safe(route.chatId, () =>
        api.sendMessage(route.chatId, markdownToHtml(source), { ...options }),
      );
      if (m) sent.push(m);
    } catch (error) {
      if (/can't parse entities|parse entities/i.test(String(error))) {
        delete options.parse_mode;
        const m = await safe(route.chatId, () => api.sendMessage(route.chatId, source, options));
        if (m) sent.push(m);
      } else {
        log.warn("Telegram send failed", { chat: route.chatId, err: String(error) });
      }
    }
    first = false;
  }
  return sent;
}
function plain(text: string) {
  return text.replace(/\s+/g, " ").trim().slice(-180);
}

export function createRenderer(
  api: TelegramApiLike,
  config: Config,
  route: RouteKey,
  trigger?: string,
  mode: ReplyMode = "relay",
) {
  let text = "",
    lastMessageId: string | undefined,
    reasoning = "",
    typing: ReturnType<typeof setInterval> | null = null,
    streamTimer: ReturnType<typeof setTimeout> | null = null,
    streamMessages: number[] = [],
    lastEdit = 0,
    ended = false;
  const tools = new Map<string, { label: string; state: "running" | "done" | "failed" }>();
  let toolMessage: number | null = null,
    toolSync = Promise.resolve(),
    reasoningMessage: number | null = null,
    reasoningTimer: ReturnType<typeof setTimeout> | null = null,
    // In-flight syncs; `done` awaits them so it never races a first send.
    streamSync: Promise<void> = Promise.resolve(),
    reasoningSync: Promise<void> = Promise.resolve(),
    events: Promise<void> = Promise.resolve();
  const opts = () => (route.topicId ? { message_thread_id: Number(route.topicId) } : {});
  const stopTyping = () => {
    if (typing) clearInterval(typing);
    typing = null;
  };
  const tick = () => void safe(route.chatId, () => api.sendChatAction(route.chatId, "typing", opts()));
  const toolText = () =>
    [...tools.values()]
      .slice(-20)
      .map((t) => `${t.state === "running" ? "◌" : t.state === "done" ? "✓" : "✗"} ${t.label}`)
      .join("\n");
  const syncTools = () => {
    if (!config.SHOW_TOOL_CALLS || mode === "tool") return;
    toolSync = toolSync
      .then(async () => {
        const body = toolText();
        if (!body) return;
        if (toolMessage === null) {
          const m = await safe(route.chatId, () => api.sendMessage(route.chatId, body, opts()));
          if (m) toolMessage = m.message_id;
        } else await safe(route.chatId, () => api.editMessageText(route.chatId, toolMessage!, body, opts()));
      })
      .catch(() => {});
  };
  const syncStream = async () => {
    if (mode === "tool" || !text) return;
    const chunks = splitMarkdown(text);
    for (let i = 0; i < chunks.length; i++) {
      const source = chunks[i]!,
        messageId = streamMessages[i];
      if (messageId === undefined) {
        const sent = await sendFormatted(api, route, source, i === 0 ? trigger : undefined);
        streamMessages.push(...sent.map((message) => message.message_id));
        continue;
      }
      try {
        await safe(route.chatId, () =>
          api.editMessageText(route.chatId, messageId, markdownToHtml(source), {
            parse_mode: "HTML",
            ...opts(),
          }),
        );
      } catch (error) {
        if (/can't parse entities|parse entities/i.test(String(error)))
          await safe(route.chatId, () => api.editMessageText(route.chatId, messageId, source, opts()));
        else if (!/message is not modified/i.test(String(error)))
          log.debug("Telegram stream edit failed", { err: String(error) });
      }
    }
    lastEdit = Date.now();
  };
  const scheduleStream = () => {
    if (!config.STREAM_EDITS || mode === "tool" || streamTimer) return;
    const wait = Math.max(0, lastEdit + config.STREAM_EDIT_INTERVAL_MS - Date.now());
    streamTimer = setTimeout(() => {
      streamTimer = null;
      if (!ended) streamSync = streamSync.then(syncStream).catch(() => {});
    }, wait);
  };
  const syncReasoning = async () => {
    const body = `Thinking: ${plain(reasoning)}`;
    if (!plain(reasoning)) return;
    if (reasoningMessage === null) {
      const message = await safe(route.chatId, () => api.sendMessage(route.chatId, body, opts()));
      if (message) reasoningMessage = message.message_id;
    } else await safe(route.chatId, () => api.editMessageText(route.chatId, reasoningMessage!, body, opts()));
  };
  const scheduleReasoning = () => {
    if (!config.SHOW_REASONING || mode === "tool" || reasoningTimer) return;
    reasoningTimer = setTimeout(
      () => {
        reasoningTimer = null;
        if (!ended) reasoningSync = reasoningSync.then(syncReasoning).catch(() => {});
      },
      Math.max(0, config.STREAM_EDIT_INTERVAL_MS),
    );
  };
  const handle = async (event: TurnEvent): Promise<void> => {
    try {
      switch (event.kind) {
        case "started":
          if (mode !== "tool") {
            tick();
            typing = setInterval(tick, 4000);
            typing.unref?.();
          }
          break;
        case "assistant_delta":
          // A new assistant message (such as after a tool call) starts a new paragraph.
          if (text && event.messageId && lastMessageId && event.messageId !== lastMessageId) text += "\n\n";
          if (event.messageId) lastMessageId = event.messageId;
          text += event.text;
          scheduleStream();
          break;
        case "reasoning_delta":
          reasoning += event.text;
          scheduleReasoning();
          break;
        case "tool_call":
          tools.set(event.toolCallId, { label: plain(event.summary || event.toolName), state: "running" });
          syncTools();
          break;
        case "tool_result": {
          const t = tools.get(event.toolCallId);
          if (t) t.state = event.isError ? "failed" : "done";
          syncTools();
          break;
        }
        case "retry":
          tools.set(`retry-${event.attempt}`, {
            label: `Retrying (${event.attempt}/${event.maxAttempts})`,
            state: "running",
          });
          syncTools();
          break;
        case "error":
          log.debug("Telegram turn error", { message: event.message });
          break;
        case "merged":
          ended = true;
          stopTyping();
          break;
        case "done":
          ended = true;
          stopTyping();
          if (streamTimer) clearTimeout(streamTimer);
          if (reasoningTimer) clearTimeout(reasoningTimer);
          await streamSync;
          await reasoningSync;
          if (mode !== "tool") {
            if (config.STREAM_EDITS && streamMessages.length > 0) await syncStream();
            else if (text) await sendFormatted(api, route, text, trigger);
            else if (!event.success && event.errorCode !== "interrupted")
              await sendFormatted(
                api,
                route,
                "Sorry, something went wrong while answering. Try again, or use /new.",
                trigger,
              );
            if (config.SHOW_REASONING && reasoning) {
              if (reasoningMessage !== null && text && api.deleteMessage)
                await safe(route.chatId, () => api.deleteMessage!(route.chatId, reasoningMessage!));
              else if (reasoningMessage === null) await syncReasoning();
            }
            if (config.LIFECYCLE_REACTIONS && trigger && api.setMessageReaction) {
              const emoji = event.errorCode === "interrupted" ? "🤷" : event.success ? "👌" : "💔";
              if (LIFECYCLE_EMOJI.has(emoji))
                await safe(route.chatId, () =>
                  api.setMessageReaction!(route.chatId, Number(trigger), [{ type: "emoji", emoji }]),
                );
            }
          }
          break;
      }
    } catch (error) {
      log.warn("Telegram renderer failed", { chat: route.chatId, err: String(error) });
    }
  };
  // Apply events strictly in arrival order.
  return (event: TurnEvent): Promise<void> => (events = events.then(() => handle(event)));
}
