import { mkdir, rm, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { LettaAgentClient } from "@letta-ai/letta-agent-sdk";
import { loadConfig, type Config } from "./config.ts";
import { parseRoutingTable, pinnedConversations, type RoutingTable } from "./routing.ts";

export type CheckStatus = "PASS" | "WARN" | "FAIL";
export interface CheckResult {
  status: CheckStatus;
  check: string;
  message: string;
  hint: string;
}
export type DoctorFetch = typeof fetch;
const result = (status: CheckStatus, check: string, message: string, hint: string): CheckResult => ({
  status,
  check,
  message,
  hint,
});
const safe = (v: unknown, fallback: string) =>
  (typeof v === "string" && v.replace(/[\r\n]+/g, " ").trim()) || fallback;
async function json<T>(r: Response): Promise<T | undefined> {
  try {
    return (await r.json()) as T;
  } catch {
    return;
  }
}
function api(token: string, method: string) {
  return `https://api.telegram.org/bot${token}/${method}`;
}
interface TelegramMe {
  id: number;
  is_bot: boolean;
  username?: string;
  can_join_groups?: boolean;
  can_read_all_group_messages?: boolean;
}
interface ApiResult<T> {
  ok: boolean;
  result?: T;
  description?: string;
}
export async function checkTelegramToken(
  fetchImpl: DoctorFetch,
  token: string,
  openChats: string[] = [],
): Promise<{ checks: CheckResult[]; bot?: TelegramMe }> {
  try {
    const response = await fetchImpl(api(token, "getMe"));
    const body = await json<ApiResult<TelegramMe>>(response);
    if (!response.ok || !body?.ok || !body.result?.id)
      return {
        checks: [
          result(
            "FAIL",
            "Telegram token",
            `Telegram rejected the bot credentials (HTTP ${response.status})`,
            "Create a new token with BotFather and update TELEGRAM_BOT_TOKEN.",
          ),
        ],
      };
    const bot = body.result,
      checks = [
        result(
          "PASS",
          "Telegram token",
          `authenticated as @${safe(bot.username, "bot")}`,
          "No action needed.",
        ),
        bot.can_join_groups === false
          ? result(
              "WARN",
              "Group access",
              "BotFather prevents this bot from joining groups",
              "Use /setjoingroups in BotFather if group use is intended.",
            )
          : result("PASS", "Group access", "the bot may join groups", "No action needed."),
      ];
    if (openChats.length)
      checks.push(
        bot.can_read_all_group_messages
          ? result("PASS", "Group privacy", "privacy mode is off, as open chats require", "No action needed.")
          : result(
              "FAIL",
              "Group privacy",
              "privacy mode hides ordinary group messages but open chats are configured",
              "Use /setprivacy in BotFather and disable privacy mode.",
            ),
      );
    return { checks, bot };
  } catch {
    return {
      checks: [
        result(
          "FAIL",
          "Telegram token",
          "could not reach the Telegram API",
          "Check network access to api.telegram.org.",
        ),
      ],
    };
  }
}
export async function checkWebhook(fetchImpl: DoctorFetch, token: string): Promise<CheckResult> {
  try {
    const response = await fetchImpl(api(token, "getWebhookInfo"));
    const body = await json<ApiResult<{ url?: string }>>(response);
    if (!response.ok || !body?.ok)
      return result(
        "FAIL",
        "Telegram webhook",
        `could not inspect webhook (HTTP ${response.status})`,
        "Check TELEGRAM_BOT_TOKEN.",
      );
    return body.result?.url
      ? result(
          "WARN",
          "Telegram webhook",
          "a webhook is currently configured",
          "Starting this long-polling bot removes it automatically. Stop the old deployment first.",
        )
      : result("PASS", "Telegram webhook", "no webhook is configured", "No action needed.");
  } catch {
    return result(
      "FAIL",
      "Telegram webhook",
      "could not reach the Telegram API",
      "Check network access to api.telegram.org.",
    );
  }
}
export function checkAccess(config: Config): CheckResult[] {
  const out: CheckResult[] = [];
  out.push(
    config.TELEGRAM_ADMIN_USER_IDS.length
      ? result(
          "PASS",
          "Telegram admins",
          `${config.TELEGRAM_ADMIN_USER_IDS.length} admin user(s) configured`,
          "No action needed.",
        )
      : result(
          "WARN",
          "Telegram admins",
          "no admin users are configured",
          "Set TELEGRAM_ADMIN_USER_IDS so approvals and detailed status work.",
        ),
  );
  if (config.GROUP_POLICY === "allowlist" && !config.TELEGRAM_GROUP_IDS.length)
    out.push(
      result(
        "WARN",
        "Group allowlist",
        "GROUP_POLICY=allowlist but no groups are configured",
        "Set TELEGRAM_GROUP_IDS or choose GROUP_POLICY=off/open.",
      ),
    );
  return out;
}
export function checkApprovers(config: Config): CheckResult {
  if (config.APPROVAL_MODE === "admins" && !config.TELEGRAM_ADMIN_USER_IDS.length)
    return result(
      "WARN",
      "Approvals",
      `APPROVAL_MODE=admins with no admin users: calls not auto-allowed by PERMISSION_MODE=${config.PERMISSION_MODE} are denied`,
      "Set TELEGRAM_ADMIN_USER_IDS or choose another APPROVAL_MODE.",
    );
  return result(
    "PASS",
    "Approvals",
    `APPROVAL_MODE=${config.APPROVAL_MODE}`,
    config.APPROVAL_MODE === "allow"
      ? "Use admins or requester if untrusted people can reach the bot."
      : "No action needed.",
  );
}
function lettaBase(c: Config) {
  return (c.LETTA_BASE_URL ?? "https://api.letta.com").replace(/\/+$/, "");
}
export async function checkLetta(fetchImpl: DoctorFetch, c: Config): Promise<CheckResult> {
  try {
    const r = await fetchImpl(`${lettaBase(c)}/v1/agents/${encodeURIComponent(c.LETTA_AGENT_ID)}`, {
      headers: { Authorization: `Bearer ${c.LETTA_API_KEY}` },
    });
    if (r.status === 401 || r.status === 403)
      return result(
        "FAIL",
        "Letta agent",
        `authentication failed (HTTP ${r.status})`,
        `Replace LETTA_API_KEY with a valid key.`,
      );
    if (r.status === 404)
      return result(
        "FAIL",
        "Letta agent",
        "agent was not found (HTTP 404)",
        "Check LETTA_AGENT_ID and project access.",
      );
    if (!r.ok)
      return result(
        "FAIL",
        "Letta agent",
        `request failed (HTTP ${r.status})`,
        "Check LETTA_BASE_URL and service availability.",
      );
    const a = (await json<Record<string, unknown>>(r)) ?? {},
      llm = a.llm_config && typeof a.llm_config === "object" ? (a.llm_config as Record<string, unknown>) : {};
    return result(
      "PASS",
      "Letta agent",
      `${safe(a.name, c.LETTA_AGENT_ID)} (${safe(typeof a.model === "string" ? a.model : llm.model, "model not reported")})`,
      "No action needed.",
    );
  } catch {
    return result(
      "FAIL",
      "Letta agent",
      "could not reach the Letta API",
      "Check LETTA_BASE_URL and network access.",
    );
  }
}
function describeRule(e: RoutingTable["routes"][number]) {
  if ("topic" in e) return `topic:${e.chat}:${e.topic}`;
  if ("chat" in e) return `chat:${e.chat}`;
  return `user:${e.user}`;
}
export async function checkRoutingTable(
  fetchImpl: DoctorFetch,
  c: Config,
  readFile = (p: string) => readFileSync(p, "utf8"),
): Promise<CheckResult[]> {
  if (!c.ROUTES_FILE) return [];
  let table: RoutingTable;
  try {
    table = parseRoutingTable(readFile(c.ROUTES_FILE), c.ROUTES_FILE);
  } catch (error) {
    return [
      result(
        "FAIL",
        "Routing table",
        error instanceof Error ? error.message.replace(/\n/g, " ") : String(error),
        "Fix ROUTES_FILE.",
      ),
    ];
  }
  const out = [
    result(
      "PASS",
      "Routing table",
      `${table.routes.length} rule(s), fallback ${table.fallback ?? "auto"}`,
      "No action needed.",
    ),
  ];
  for (const e of table.routes)
    if (e.policy)
      out.push(
        result(
          "PASS",
          `Tool policy ${describeRule(e)}`,
          Object.entries(e.policy)
            .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(",") : v}`)
            .join(", "),
          "No action needed.",
        ),
      );
  for (const id of pinnedConversations(table)) {
    if (id === "default") {
      out.push(result("PASS", "Pinned default", "the agent's default conversation", "No action needed."));
      continue;
    }
    try {
      const r = await fetchImpl(`${lettaBase(c)}/v1/conversations/${encodeURIComponent(id)}`, {
        headers: { Authorization: `Bearer ${c.LETTA_API_KEY}` },
      });
      if (!r.ok) {
        out.push(
          result(
            "FAIL",
            `Pinned ${id}`,
            `request failed (HTTP ${r.status})`,
            "Fix the conversation id or project access.",
          ),
        );
        continue;
      }
      const conv = await json<{ agent_id?: string }>(r);
      out.push(
        conv?.agent_id && conv.agent_id !== c.LETTA_AGENT_ID
          ? result(
              "FAIL",
              `Pinned ${id}`,
              `belongs to ${conv.agent_id}, not LETTA_AGENT_ID`,
              `Pin only this agent's conversations.`,
            )
          : result("PASS", `Pinned ${id}`, "conversation exists", "No action needed."),
      );
    } catch {
      out.push(result("FAIL", `Pinned ${id}`, "could not reach the Letta API", "Check network access."));
    }
  }
  return out;
}
export interface ComputerResolution {
  name?: string;
  status?: string;
}
export type ComputerResolver = (name: string, c: Config) => Promise<ComputerResolution>;
export async function checkComputer(c: Config, resolver?: ComputerResolver): Promise<CheckResult> {
  if (!c.LETTA_COMPUTER)
    return result("PASS", "Letta computer", "using SDK-managed Cloud sandboxes", "No action needed.");
  if (!resolver)
    return result("WARN", "Letta computer", `${c.LETTA_COMPUTER} was not verified`, `Verify it is online.`);
  try {
    const x = await resolver(c.LETTA_COMPUTER, c),
      status = safe(x.status, "status unknown");
    return status === "online"
      ? result("PASS", "Letta computer", `${safe(x.name, c.LETTA_COMPUTER)} is online`, "No action needed.")
      : result(
          "WARN",
          "Letta computer",
          `${safe(x.name, c.LETTA_COMPUTER)} is ${status}`,
          "Bring it online.",
        );
  } catch {
    return result(
      "FAIL",
      "Letta computer",
      "configured computer could not be resolved",
      "Check LETTA_COMPUTER.",
    );
  }
}
export async function checkTranscription(fetchImpl: DoctorFetch, c: Config): Promise<CheckResult> {
  const p = c.TRANSCRIBE_PROVIDER;
  if (p === "none") return result("PASS", "Transcription", "disabled", "No action needed.");
  const bases: Record<string, string> = {
    openai: "https://api.openai.com/v1/models",
    groq: "https://api.groq.com/openai/v1/models",
    deepgram: "https://api.deepgram.com/v1/projects",
  };
  const url = c.TRANSCRIBE_BASE_URL
    ? `${c.TRANSCRIBE_BASE_URL.replace(/\/+$/, "")}/${p === "deepgram" ? "projects" : "models"}`
    : bases[p];
  if (!url)
    return result(
      "WARN",
      "Transcription",
      `${p} credentials were not verified without uploading audio`,
      "Test with a short voice message.",
    );
  try {
    const r = await fetchImpl(url, {
      headers: { Authorization: `${p === "deepgram" ? "Token" : "Bearer"} ${c.TRANSCRIBE_API_KEY}` },
    });
    return r.ok
      ? result("PASS", "Transcription", `${p} credentials accepted`, "No action needed.")
      : result(
          "FAIL",
          "Transcription",
          `${p} credential check failed (HTTP ${r.status})`,
          "Check transcription credentials.",
        );
  } catch {
    return result("FAIL", "Transcription", `could not reach ${p}`, "Check network access.");
  }
}
export async function checkDataDir(dir: string): Promise<CheckResult> {
  const directory = resolve(dir),
    path = join(directory, `.doctor-${randomUUID()}.tmp`);
  try {
    await mkdir(directory, { recursive: true });
    await writeFile(path, "doctor", { flag: "wx" });
    await rm(path);
    return result("PASS", "DATA_DIR", "directory is writable", "No action needed.");
  } catch {
    await rm(path, { force: true }).catch(() => {});
    return result("FAIL", "DATA_DIR", "directory is not writable", "Create it and grant write permission.");
  }
}
export interface DoctorOptions {
  fetch?: DoctorFetch;
  env?: Record<string, string | undefined>;
  computerResolver?: ComputerResolver;
}
function redact(results: CheckResult[], env: Record<string, string | undefined>) {
  const secrets = Object.entries(env)
    .filter(([k, v]) => v && /(TOKEN|API_KEY|SECRET|PASSWORD)/i.test(k))
    .map(([, v]) => v!);
  const clean = (s: string) => secrets.reduce((x, k) => x.split(k).join("[REDACTED]"), s);
  return results.map((x) => ({
    ...x,
    check: clean(x.check),
    message: clean(x.message),
    hint: clean(x.hint),
  }));
}
export async function runDoctor(options: DoctorOptions = {}): Promise<CheckResult[]> {
  const env = options.env ?? process.env,
    fetchImpl = options.fetch ?? fetch;
  let c: Config;
  try {
    c = loadConfig(env);
  } catch (error) {
    const lines = (error instanceof Error ? error.message : "Invalid configuration").split("\n").slice(1);
    return redact(
      (lines.length ? lines : ["configuration is invalid"]).map((x) =>
        result("FAIL", "Config", x.replace(/^\s*-\s*/, ""), "Correct this variable and retry."),
      ),
      env,
    );
  }
  const out = [
    result("PASS", "Config", "configuration is valid", "No action needed."),
    checkApprovers(c),
    ...checkAccess(c),
  ];
  const telegram = await checkTelegramToken(fetchImpl, c.TELEGRAM_BOT_TOKEN, c.TELEGRAM_OPEN_CHAT_IDS);
  out.push(...telegram.checks, await checkWebhook(fetchImpl, c.TELEGRAM_BOT_TOKEN));
  const letta = await checkLetta(fetchImpl, c);
  out.push(letta);
  const authFailed = letta.status === "FAIL" && letta.message.startsWith("authentication failed");
  out.push(
    authFailed && c.LETTA_COMPUTER
      ? result("FAIL", "Letta computer", "could not be checked without a valid API key", "Fix LETTA_API_KEY.")
      : await checkComputer(c, options.computerResolver),
  );
  if (!authFailed) out.push(...(await checkRoutingTable(fetchImpl, c)));
  out.push(await checkTranscription(fetchImpl, c), await checkDataDir(c.DATA_DIR));
  return redact(out, env);
}
export const formatCheck = (c: CheckResult) => `${c.status} ${c.check}: ${c.message}. Hint: ${c.hint}`;
async function sdkResolver(name: string, c: Config) {
  const client = new LettaAgentClient({
    backend: "cloud",
    apiKey: c.LETTA_API_KEY,
    ...(c.LETTA_BASE_URL ? { apiBaseUrl: c.LETTA_BASE_URL } : {}),
  });
  try {
    const r = await client.computers.resolve(name);
    return { name: r.computer?.name ?? name, status: r.computer?.status ?? "online" };
  } finally {
    await client.close();
  }
}
if (import.meta.main) {
  const checks = await runDoctor({ computerResolver: sdkResolver });
  for (const c of checks) console.log(formatCheck(c));
  if (checks.some((c) => c.status === "FAIL")) process.exitCode = 1;
}
