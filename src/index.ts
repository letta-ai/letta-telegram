import { InputFile } from "grammy";
import { loadConfig } from "./config.ts";
import { startHealthServer } from "./health.ts";
import { createAgentBridge } from "./letta/bridge.ts";
import { RouteStore } from "./letta/store.ts";
import { log, setLogLevel } from "./log.ts";
import { loadRoutingTable, pinnedConversations } from "./routing.ts";
import { createTelegramBot, startTelegram } from "./telegram/gateway.ts";
import { createTelegramToolFactory } from "./telegram/tools.ts";

async function main() {
  const config = loadConfig();
  setLogLevel(config.LOG_LEVEL);
  if (config.APPROVAL_MODE === "admins" && !config.TELEGRAM_ADMIN_USER_IDS.length)
    log.warn("APPROVAL_MODE=admins but no Telegram admins are configured");
  const routes = loadRoutingTable(config.ROUTES_FILE);
  if (routes)
    log.info("routing table loaded", {
      file: config.ROUTES_FILE,
      rules: routes.routes.length,
      conversations: pinnedConversations(routes),
    });
  const store = new RouteStore(config.DATA_DIR);
  const bot = createTelegramBot(config.TELEGRAM_BOT_TOKEN);
  const bridge = createAgentBridge(config, {
    store,
    routes,
    toolFactory: createTelegramToolFactory({
      api: bot.api as never,
      config,
      makeInputFile: (data, name) => new InputFile(data, name),
    }),
  });
  const telegram = await startTelegram(config, bridge, store, bot);
  const health = startHealthServer(config.HEALTH_PORT, {
    telegramReady: () => telegram.ready(),
    routes: () => store.count(),
  });
  let stopping = false;
  const shutdown = async (signal: string) => {
    if (stopping) return;
    stopping = true;
    log.info("shutting down", { signal });
    const force = setTimeout(() => process.exit(1), 15_000);
    force.unref?.();
    await telegram.stop().catch((e) => log.warn("Telegram stop failed", { err: String(e) }));
    await bridge.shutdown().catch((e) => log.warn("bridge shutdown failed", { err: String(e) }));
    health?.stop();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}
main().catch((e) => {
  log.error("fatal", { err: e instanceof Error ? e.message : String(e) });
  process.exit(1);
});
