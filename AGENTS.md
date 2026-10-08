# Repository guide

This is a self-hosted Telegram adapter for one Letta agent.

```bash
npm ci
npm run typecheck
bun test --timeout 5000
npm run doctor
npm start
```

Use npm for installation. Tests must not call external services. Run one process per token. `src/letta/*` must not import grammY or receive the bot token. Preserve lane serialization and one stream reader per session. Check access before commands, callbacks, downloads, and turns. Never log Telegram file URLs. Telegram tools act on the current turn's route.

The adapter is `src/telegram/*`; the reusable core is `src/letta/*`, `src/types.ts`, `src/config.ts`, and `src/routing.ts`.
