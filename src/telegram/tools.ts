import type { AnyAgentTool } from "@letta-ai/letta-agent-sdk";
import { posix as path } from "node:path";
import { replyModeFor, type Config } from "../config.ts";
import type { ToolFactory } from "../types.ts";
import { sendFormatted, type TelegramApiLike } from "./renderer.ts";

export const ALLOWED_REACTIONS = new Set([
  "👍",
  "👎",
  "❤",
  "🔥",
  "🥰",
  "👏",
  "😁",
  "🤔",
  "🤯",
  "😱",
  "🤬",
  "😢",
  "🎉",
  "🤩",
  "🤮",
  "💩",
  "🙏",
  "👌",
  "🕊",
  "🤡",
  "🥱",
  "🥴",
  "😍",
  "🐳",
  "❤‍🔥",
  "🌚",
  "🌭",
  "💯",
  "🤣",
  "⚡",
  "🍌",
  "🏆",
  "💔",
  "🤨",
  "😐",
  "🍓",
  "🍾",
  "💋",
  "🖕",
  "😈",
  "😴",
  "😭",
  "🤓",
  "👻",
  "👨‍💻",
  "👀",
  "🎃",
  "🙈",
  "😇",
  "😨",
  "🤝",
  "✍",
  "🤗",
  "🫡",
  "🎅",
  "🎄",
  "☃",
  "💅",
  "🤪",
  "🗿",
  "🆒",
  "💘",
  "🙉",
  "🦄",
  "😘",
  "💊",
  "🙊",
  "😎",
  "👾",
  "🤷",
  "🤷‍♂",
  "🤷‍♀",
  "😡",
]);

export interface ToolApi extends TelegramApiLike {
  sendDocument(chatId: string, file: unknown, options?: Record<string, unknown>): Promise<unknown>;
  sendPhoto(chatId: string, file: unknown, options?: Record<string, unknown>): Promise<unknown>;
  setMessageReaction(
    chatId: string,
    messageId: number,
    reactions: { type: "emoji"; emoji: string }[],
  ): Promise<unknown>;
}

const DESCRIPTION_PARAM = {
  type: "string",
  description:
    "Clear, concise description of what this call does, in active voice (5-10 words). Shown to people in Telegram.",
} as const;
const textResult = (text: string, isError = false) => ({
  content: [{ type: "text" as const, text }],
  ...(isError ? { isError: true } : {}),
});
const errResult = (error: unknown) =>
  textResult(error instanceof Error ? error.message : String(error), true);
function args(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid tool arguments.");
  return value as Record<string, unknown>;
}
function str(a: Record<string, unknown>, key: string, required = false): string | undefined {
  const v = a[key];
  if (v === undefined && !required) return;
  if (typeof v !== "string" || (required && !v)) throw new Error(`Invalid ${key}.`);
  return v;
}
function photoMime(data: Uint8Array): string | null {
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return "image/jpeg";
  if (data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47) return "image/png";
  if (
    String.fromCharCode(...data.slice(0, 4)) === "RIFF" &&
    String.fromCharCode(...data.slice(8, 12)) === "WEBP"
  )
    return "image/webp";
  return null;
}

export function createTelegramToolFactory(deps: {
  api: ToolApi;
  config: Config;
  makeInputFile(data: Uint8Array, name: string): unknown;
}): ToolFactory {
  return (initialRoute, currentTurn, sandbox): AnyAgentTool[] => {
    const route = () => currentTurn()?.route ?? initialRoute;
    const react: AnyAgentTool = {
      name: "telegram_react",
      label: "React in Telegram",
      description: "Add an allowed Telegram reaction to a message in this conversation.",
      parameters: {
        type: "object",
        properties: {
          description: DESCRIPTION_PARAM,
          message_id: { type: "string" },
          emoji: { type: "string" },
        },
        required: ["description", "emoji"],
        additionalProperties: false,
      },
      async execute(_id, raw) {
        try {
          const a = args(raw),
            // Telegram lists reactions without the variation selector that models usually add.
            emoji = str(a, "emoji", true)!.replace(/\uFE0F/g, "");
          if (!ALLOWED_REACTIONS.has(emoji)) throw new Error("That reaction is not supported by Telegram.");
          const id = str(a, "message_id") ?? currentTurn()?.triggerMessageId;
          if (!id || !/^\d+$/.test(id)) throw new Error("A valid message_id is required.");
          const r = route();
          await deps.api.setMessageReaction(r.chatId, Number(id), [{ type: "emoji", emoji }]);
          return textResult("Reaction added.");
        } catch (e) {
          return errResult(e);
        }
      },
    };
    const send: AnyAgentTool = {
      name: "telegram_send_message",
      label: "Send Telegram message",
      description: "Post a message in this Telegram chat. In tool reply mode this is the only way to speak.",
      parameters: {
        type: "object",
        properties: { description: DESCRIPTION_PARAM, text: { type: "string" } },
        required: ["description", "text"],
        additionalProperties: false,
      },
      async execute(_id, raw) {
        try {
          const a = args(raw),
            text = str(a, "text", true)!;
          const sent = await sendFormatted(deps.api, route(), text);
          if (!sent.length) throw new Error("Telegram did not accept the message.");
          return textResult("Message sent.");
        } catch (e) {
          return errResult(e);
        }
      },
    };
    const tools: AnyAgentTool[] = [react, send];
    if (sandbox)
      tools.push({
        name: "telegram_send_file",
        label: "Send file to Telegram",
        description: "Send a file from /root/downloads to this Telegram chat.",
        parameters: {
          type: "object",
          properties: {
            description: DESCRIPTION_PARAM,
            path: { type: "string" },
            caption: { type: "string" },
          },
          required: ["description", "path"],
          additionalProperties: false,
        },
        async execute(_id, raw) {
          try {
            const a = args(raw),
              p = str(a, "path", true)!,
              caption = str(a, "caption");
            const normalized = path.normalize(p);
            if (
              !path.isAbsolute(p) ||
              normalized !== p ||
              !p.startsWith("/root/downloads/") ||
              path.basename(p) === ""
            )
              throw new Error("File path must be a normalized path under /root/downloads/.");
            const data = await sandbox.downloadFile(p);
            if (data.byteLength > deps.config.MAX_FILE_BYTES)
              throw new Error(`File is too large (maximum ${deps.config.MAX_FILE_BYTES} bytes).`);
            const r = route(),
              file = deps.makeInputFile(data, path.basename(p));
            const options = {
              ...(caption ? { caption } : {}),
              ...(r.topicId ? { message_thread_id: Number(r.topicId) } : {}),
            };
            if (photoMime(data)) await deps.api.sendPhoto(r.chatId, file, options);
            else await deps.api.sendDocument(r.chatId, file, options);
            return textResult("File sent.");
          } catch (e) {
            return errResult(e);
          }
        },
      });
    const toolMode = replyModeFor(deps.config, initialRoute) === "tool";
    return tools.filter((t) =>
      t.name === "telegram_send_message" ? toolMode : deps.config.ENABLE_TELEGRAM_TOOLS,
    );
  };
}
