# Letta Telegram

Your Letta agent, available in Telegram.

[Quickstart](#-quickstart) · [Listening](#-where-it-listens) · [Tools](#-tools-and-approvals) · [Deploying](docs/deploying.md)

## ✨ Features

One operator-owned agent works in DMs, groups, and forum topics. It supports mention and reply activation, open chats, images, files, voice transcription, albums, streaming edits, progress cards, reactions, inline approvals, and durable conversations.

## 🚀 Quickstart

1. Ask BotFather for a bot with `/newbot` and save its token.
2. Copy your Letta API key and agent ID.
3. Find your numeric user ID with `@userinfobot`, or from this bot's access refusal or logs.
4. Copy `.env.example` to `.env`, fill the four required values, then run:

```bash
npm ci
npm run doctor
npm start
```

Use BotFather `/setjoingroups` to control group installation. Mentioned messages work with privacy enabled. Open groups require `/setprivacy` to disable privacy mode and their ID in `TELEGRAM_OPEN_CHAT_IDS`.

## 🧭 How it works

```text
Telegram long polling → access and batching → Letta Agent SDK → Telegram HTML
                              ↕
                     SQLite + agent sandbox
```

Each chat has a conversation. Each real forum topic is separate. A routing file can pin chats and topics to existing conversations.

## 📍 Where it listens

- DMs follow `DM_POLICY`; the default allows configured users and admins.
- Groups follow `GROUP_POLICY`; the default accepts only `TELEGRAM_GROUP_IDS`, then answers mentions, replies to the bot, and commands.
- Open chats pass every visible message to the agent and require BotFather privacy mode off.
- Bots, service messages, channel posts, and edited messages are ignored.

## 🛠 Tools and approvals

`telegram_react`, `telegram_send_file`, and open-chat `telegram_send_message` are scoped to the current chat and topic. Telegram has no history tool. Approval policy can deny, ask admins, ask the requester or an admin, or allow. Buttons resolve once and expire. See [Tools and permissions](docs/tools-and-permissions.md).

## 💬 Commands

`/start`, `/help`, `/new`, `/cancel`, and `/status`. Admins see conversation and model details in status.

## 🎙 Voice, images, and files

The largest eligible photo is multimodal. Other media is streamed with a timeout and hard cap, then uploaded to the sandbox. Telegram file URLs contain the token and are never logged or shown to the agent. Configure a transcription provider for voice and audio.

<details>
<summary>Configuration</summary>

| Variable | Default | Purpose |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN`, `LETTA_API_KEY`, `LETTA_AGENT_ID` | required | Credentials and agent |
| `TELEGRAM_ADMIN_USER_IDS` | empty | Operators, strongly recommended |
| `TELEGRAM_ALLOWED_USER_IDS` | empty | Allowed people |
| `DM_POLICY`, `GROUP_POLICY` | `allowlist` | `off`, `allowlist`, or `open` |
| `TELEGRAM_GROUP_IDS`, `TELEGRAM_OPEN_CHAT_IDS` | empty | Group and open-chat IDs |
| `OPEN_CHAT_REPLY_MODE` | `relay` | `relay` or `tool` |
| `ROUTES_FILE` | empty | Routing and per-route policy JSON |
| `APPROVAL_MODE` | `admins` | `deny`, `admins`, `requester`, or `allow` |
| `ENABLE_TELEGRAM_TOOLS` | `true` | Reaction and file tools |
| `STREAM_EDITS`, `SHOW_TOOL_CALLS`, `SHOW_REASONING` | `false` | Rendering options |
| `MAX_IMAGE_BYTES`, `MAX_FILE_BYTES` | 5 MiB, 20 MiB | Download limits |
| `DATA_DIR` | `./data` | SQLite state |

See [.env.example](.env.example) for all SDK, policy, transcription, session, storage, and logging settings.
</details>

## 📦 Deploying

Run exactly one process per token. Competing pollers receive Telegram `409 Conflict`. Docker, Compose, systemd, and Fly examples are in [Deploying](docs/deploying.md).

## 🔐 Security

Access is checked before commands, callbacks, downloads, or turns. Use group allowlists to prevent unexpected credit use. Keep tokens out of logs and use restrictive policies in open chats.

## Coming from the old Modal version

This version is self-hosted, uses one configured agent, and has no `/login` or switching. Long polling removes the old Modal webhook automatically. Stop the old deployment first.

## License

MIT. See [LICENSE](LICENSE).
