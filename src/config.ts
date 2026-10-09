import { z } from "zod";
import { TRANSCRIBE_PROVIDERS } from "./transcribe/index.ts";
import type { RouteKey } from "./types.ts";

const csv = z
  .string()
  .optional()
  .transform((v) =>
    (v ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );

const bool = (def: boolean) =>
  z
    .string()
    .optional()
    .transform((v) => (v === undefined || v === "" ? def : /^(1|true|yes|on)$/i.test(v)));

const int = (def: number) =>
  z
    .string()
    .optional()
    .transform((v) => (v === undefined || v === "" ? def : Number.parseInt(v, 10)))
    .pipe(z.number().int().nonnegative());

export const PermissionModeSchema = z.enum(["strict", "standard", "acceptEdits", "unrestricted"]);
export const ToolsetBaseSchema = z.enum(["auto", "default", "codex", "gemini", "none"]);
export const ApprovalModeSchema = z.enum(["deny", "admins", "requester", "allow"]);
export type PermissionMode = z.infer<typeof PermissionModeSchema>;
export type ToolsetBase = z.infer<typeof ToolsetBaseSchema>;
export type ApprovalMode = z.infer<typeof ApprovalModeSchema>;

export const ConfigSchema = z
  .object({
    // Required credentials and target
    TELEGRAM_BOT_TOKEN: z.string().min(1, "TELEGRAM_BOT_TOKEN is required"),
    LETTA_API_KEY: z.string().min(1, "LETTA_API_KEY is required"),
    LETTA_AGENT_ID: z.string().regex(/^agent-/, "LETTA_AGENT_ID must look like agent-..."),
    LETTA_BASE_URL: z.string().url().optional(),

    // Execution target. Empty = SDK-managed Cloud sandbox per conversation.
    LETTA_COMPUTER: z.string().optional(),
    SANDBOX_TTL_MINUTES: int(30),

    // Agent policy (operator-owned, never changeable from Telegram)
    // Defaults for every route. A routing table entry can override them per route (see src/routing.ts).
    PERMISSION_MODE: PermissionModeSchema.default("standard"),
    ALLOWED_TOOLS: csv, // empty = harness default toolset
    TOOLSET_BASE: ToolsetBaseSchema.optional(),
    CONVERSATION_MODEL: z.string().optional(), // pinned at conversation create
    ROUTES_FILE: z.string().optional(), // JSON routing table pinning Telegram surfaces to existing conversations
    APPROVAL_MODE: ApprovalModeSchema.default("admins"),
    APPROVAL_TIMEOUT_SECONDS: int(300),
    TURN_TIMEOUT_SECONDS: int(900), // whole turn, including approval waits
    ENABLE_TELEGRAM_TOOLS: bool(true),

    TELEGRAM_GROUP_IDS: csv,
    TELEGRAM_OPEN_CHAT_IDS: csv,
    OPEN_CHAT_REPLY_MODE: z.enum(["relay", "tool"]).default("relay"),
    TELEGRAM_ALLOWED_USER_IDS: csv,
    TELEGRAM_ADMIN_USER_IDS: csv,
    DM_POLICY: z.enum(["off", "allowlist", "open"]).default("allowlist"),
    GROUP_POLICY: z.enum(["off", "allowlist", "open"]).default("allowlist"),
    REGISTER_COMMANDS: bool(true),

    // UX
    STREAM_EDITS: bool(false),
    STREAM_EDIT_INTERVAL_MS: int(1500),
    SHOW_TOOL_CALLS: bool(false), // post tool-call lines between replies
    SHOW_REASONING: bool(false),
    LIFECYCLE_REACTIONS: bool(false),
    DEBOUNCE_MS: int(1500),
    MAX_IMAGE_BYTES: int(5 * 1024 * 1024),
    MAX_FILE_BYTES: int(20 * 1024 * 1024),
    DOWNLOAD_TIMEOUT_SECONDS: int(30),
    // When turns run on a named computer that shares this filesystem (no managed
    // sandbox), save attachments here and hand the agent the local path.
    LOCAL_ATTACHMENT_DIR: z.string().optional(),

    // Voice/audio transcription (off unless a provider is set)
    TRANSCRIBE_PROVIDER: z.enum(["none", ...TRANSCRIBE_PROVIDERS]).default("none"),
    TRANSCRIBE_API_KEY: z.string().optional(),
    TRANSCRIBE_MODEL: z.string().optional(),
    TRANSCRIBE_BASE_URL: z.string().url().optional(),
    TRANSCRIBE_LANGUAGE: z.string().optional(),
    TRANSCRIBE_TIMEOUT_SECONDS: int(60),

    // Runtime
    DATA_DIR: z.string().default("./data"),
    HEALTH_PORT: int(8080),
    SESSION_IDLE_MINUTES: int(15),
    LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),
  })
  .superRefine((c, ctx) => {
    if (
      c.TURN_TIMEOUT_SECONDS <= 0 ||
      (c.APPROVAL_MODE !== "allow" &&
        c.APPROVAL_MODE !== "deny" &&
        c.TURN_TIMEOUT_SECONDS <= c.APPROVAL_TIMEOUT_SECONDS)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["TURN_TIMEOUT_SECONDS"],
        message: "must be positive and longer than APPROVAL_TIMEOUT_SECONDS",
      });
    }
    const p = c.TRANSCRIBE_PROVIDER;
    if (p !== "none" && p !== "openai-compatible" && !c.TRANSCRIBE_API_KEY) {
      ctx.addIssue({
        code: "custom",
        path: ["TRANSCRIBE_API_KEY"],
        message: `required when TRANSCRIBE_PROVIDER=${p}`,
      });
    }
    if (p === "openai-compatible" && !c.TRANSCRIBE_BASE_URL) {
      ctx.addIssue({
        code: "custom",
        path: ["TRANSCRIBE_BASE_URL"],
        message: "required when TRANSCRIBE_PROVIDER=openai-compatible",
      });
    }
  });

export type Config = z.infer<typeof ConfigSchema>;

export function loadConfig(env: Record<string, string | undefined> = process.env): Config {
  // An empty value (`LETTA_BASE_URL=`) means unset, so a copied .env.example parses.
  const cleaned = Object.fromEntries(
    Object.entries(env).filter(([, v]) => v !== undefined && v.trim() !== ""),
  );
  const parsed = ConfigSchema.safeParse(cleaned);
  if (!parsed.success) {
    const issues = parsed.error.issues.map((i) => `  - ${i.path.join(".")}: ${i.message}`).join("\n");
    throw new Error(`Invalid configuration:\n${issues}`);
  }
  return parsed.data;
}

export type ReplyMode = "relay" | "tool";

/**
 * How replies reach Telegram on a route. Tool mode applies only to open chats.
 */
export function replyModeFor(
  config: Pick<Config, "TELEGRAM_OPEN_CHAT_IDS" | "OPEN_CHAT_REPLY_MODE">,
  route: RouteKey,
): ReplyMode {
  return config.OPEN_CHAT_REPLY_MODE === "tool" && config.TELEGRAM_OPEN_CHAT_IDS.includes(route.chatId)
    ? "tool"
    : "relay";
}
