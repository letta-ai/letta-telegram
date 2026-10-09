# Architecture

One process connects one Telegram bot to one Letta agent through the Agent SDK.

```text
grammY long polling
  -> telegram/ingress.ts   access, routing, normalization, dedupe, debounce
  -> letta/bridge.ts       conversations, serialized lanes, SDK stream
  -> telegram/renderer.ts  HTML, splitting, progress, reactions
```

`src/types.ts` is the platform boundary; the core never imports grammY. A route is `{ chatId, topicId, userId? }`, stored as `chatId:topicId-or--`. Private user IDs are only routing selectors.

Automatic routes create `telegram:<route>` conversations. Routes pinned to one conversation share a serialized lane. One pump owns each SDK session stream. Cancellation has a grace close. Shutdown drops pending debounces and albums.

Access runs before commands, callbacks, downloads, or turns. Topics split only when `is_topic_message` is true. Media is streamed with limits, and token-bearing file URLs never enter the core. The renderer creates balanced Telegram HTML and retries parse failures as plain text. Background runs use the same renderer without a reply target.

SQLite stores route mappings and pinned activity. Group migration rewrites the base chat and topic keys. Exactly one long poller may use a token.
