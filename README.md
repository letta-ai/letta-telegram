<h1 align="center">Letta Telegram Bot</h1>

<p align="center">
  Put a <a href="https://docs.letta.com/">Letta</a> agent in Telegram. It remembers people, learns over
  time, runs tools in its own sandbox, and answers in DMs, groups, forum topics, and voice notes.
</p>

<div align="center">
|
  <a href="#-features">Features</a> ·
  <a href="#%EF%B8%8F-quickstart">Quickstart</a> ·
  <a href="#-where-it-listens">Where it listens</a> ·
  <a href="#-tools-and-approvals">Tools</a> ·
  <a href="#%EF%B8%8F-configuration">Configuration</a> ·
  <a href="#-deploying">Deploying</a>
|
</div>

## ✨ Features

- 🧠 **An agent that remembers.** The bot is a stateful Letta agent, not a stateless chat
  completion. It carries memory across every chat, so it gets to know the people it talks to.
- 💬 **A conversation per chat.** Every DM, group, and forum topic gets its own conversation, so
  parallel chats stay separate while the agent's memory is shared.
- 🛠️ **Real tools, with you in charge.** The agent can run code and work with files in a Letta Cloud
  sandbox or on your own machine. Anything beyond reading waits for an admin to tap **Approve**.
- ⚡ **Live progress.** A typing indicator runs while the agent works. Replies can stream into
  Telegram as they are written, and tool calls can show up in a live progress message.
- 🎙️ **Voice notes.** Send a voice note and the bot transcribes it before the agent reads it, with
  nine providers to choose from, including OpenAI, Groq, Deepgram, and a self-hosted Whisper.
- 🖼️ **Photos, albums, and files.** Photos go straight to the model, albums arrive as one message,
  and other files land in the sandbox for the agent to open. It can send files back.
- 🔐 **Your token, your rules.** You run the bot, so the Telegram token never leaves your process.
  Nothing in Telegram can change the agent's model, permissions, or tools, and strangers cannot
  add the bot to their groups and spend your credits.
- 🩺 **A setup doctor.** `bun run doctor` checks every credential and setting before you go live,
  and tells you exactly what to fix.

## 🧩 How it works

```
Telegram  <-->  this bot (you run it)  <-->  your Letta agent
                                               |
                                               +-- tools run in a Letta Cloud sandbox,
                                                   or on a computer you connect
```

The bot is a small [Bun](https://bun.sh/) process built on the
[Letta Agent SDK](https://docs.letta.com/agent-sdk/) and [grammY](https://grammy.dev/). It turns
Telegram messages into turns for your agent and posts the agent's replies back, converting its
Markdown into Telegram formatting. The agent itself, with its memory and model, lives in Letta, so
you can talk to the same agent from Telegram, the Letta app, or anywhere else.

The bot receives messages by long polling, so it needs no public URL, open port, or webhook.

## ⚡️ Quickstart

### 📋 What you need

- A [Letta](https://app.letta.com) account, an agent, and an API key.
- A Telegram account.
- [Bun](https://bun.sh/) and [Node.js](https://nodejs.org/).

### 🤖 Create your bot

1. Open a chat with [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Pick a display name and a username ending in `bot`.
3. Copy the token BotFather sends back.

### 🔗 Connect your agent

```bash
git clone https://github.com/letta-ai/letta-telegram.git
cd letta-telegram
cp .env.example .env
```

Fill in four values in `.env`:

| Variable | Where to find it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The token from BotFather. |
| `LETTA_API_KEY` | Your API key from [app.letta.com](https://app.letta.com). |
| `LETTA_AGENT_ID` | Your agent's ID, starting with `agent-`. |
| `TELEGRAM_ADMIN_USER_IDS` | Your numeric Telegram user ID. Not sure what it is? Leave it empty, start the bot, and send it a DM: it replies with your ID. |

You are now the bot's admin: you approve the agent's tool calls, and you can DM the bot. Never
commit `.env`.

### 🩺 Check your setup

```bash
npm ci
bun run doctor
```

The doctor checks your configuration, the bot token, the Letta agent, where tools will run, and
local storage, without sending anything to Telegram. Dependencies install with npm; Bun runs the
bot.

### 🚀 Say hello

```bash
bun run start
```

Open a DM with your bot and say hi.

## 📍 Where it listens

| Where | What the bot does |
|---|---|
| **DMs** | Answers admins and anyone in `TELEGRAM_ALLOWED_USER_IDS`. Others get a short refusal that includes their user ID, so you can add them. `DM_POLICY=open` answers everyone. |
| **Groups** | Works only in groups listed in `TELEGRAM_GROUP_IDS`, and ignores the rest. Inside a group it answers when someone @mentions it, replies to one of its messages, or sends one of its commands. |
| **Forum topics** | Each topic in a forum group is its own conversation. |
| **Open chats** | Groups in `TELEGRAM_OPEN_CHAT_IDS` send every message to the agent, so it can follow along and join in. |

To add the bot to a group, invite it and @mention it once. The bot logs that it is ignoring the
group, with the group's ID (a negative number, often starting with `-100`). Add that ID to
`TELEGRAM_GROUP_IDS` and restart.

<details>
<summary>📣 Open chats and privacy mode</summary>

Telegram bots run in privacy mode by default: in groups they only see commands, @mentions, and
replies to their own messages. That is all the bot needs for normal groups.

An open chat needs to see everything, so turn privacy mode off: send `/setprivacy` to BotFather,
choose your bot, and pick **Disable**. Then remove the bot from the group and add it again, since
Telegram applies the change on rejoin. The doctor warns when open chats are configured while
privacy mode is still on.

By default the agent's reply is posted in open chats like anywhere else. With
`OPEN_CHAT_REPLY_MODE=tool` the agent stays quiet unless it calls `telegram_send_message`, so it
can read along without answering every message.

Use BotFather's `/setjoingroups` to stop anyone from adding the bot to groups at all.

</details>

## 🛠 Tools and approvals

Out of the box the agent can read files, search, and run read-only commands on its own. Anything
else, like editing a file or running a script, sends an approval message with **Approve** and
**Deny** buttons, and only admins can decide. Anything not decided within
`APPROVAL_TIMEOUT_SECONDS` (five minutes) is denied.

| `APPROVAL_MODE` | Who can approve |
|---|---|
| `admins` (default) | People in `TELEGRAM_ADMIN_USER_IDS`. |
| `requester` | The person who sent the message, or an admin. |
| `deny` | Nobody. Tools that need approval are refused. |
| `allow` | No approval. Every tool runs. |

The agent also gets Telegram tools that act only in the current chat: `telegram_react` adds a
reaction and `telegram_send_file` sends a file from its sandbox as a photo or document. See
[Tools and permissions](docs/tools-and-permissions.md) for permission modes, tool allowlists, and
running tools on your own computer.

## 💬 Commands

| Command | What it does |
|---|---|
| `/new` | Start a fresh conversation in this chat. The agent keeps its memory. |
| `/cancel` | Stop the agent's current reply. |
| `/status` | Show whether the agent is busy. Admins also see the conversation ID and model. |
| `/help`, `/start` | Show how to use the bot. |

Any other slash command goes to the agent as a normal message.

## 🎙 Voice, photos, and files

- **Voice notes and audio** are transcribed when you set `TRANSCRIBE_PROVIDER` and its API key.
  Without one, the audio file still reaches the agent's sandbox.
- **Photos** go to the model as images, using the largest size under `MAX_IMAGE_BYTES`.
- **Documents, video, and stickers** are downloaded with a size cap and uploaded to the agent's
  sandbox. Telegram limits bot downloads to 20 MB.
- **Replies and quotes** are passed along, so the agent knows which message you mean.

## ⚙️ Configuration

Everything is set with environment variables. `.env.example` lists them all with comments.

<details>
<summary>All settings</summary>

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | required | Bot token from BotFather. |
| `LETTA_API_KEY` | required | Letta API key. |
| `LETTA_AGENT_ID` | required | The agent to put in Telegram. |
| `LETTA_BASE_URL` | Letta Cloud | Point at a self-hosted Letta server. |
| `LETTA_COMPUTER` | Cloud sandbox | Run tools on a connected computer instead. |
| `TELEGRAM_ADMIN_USER_IDS` | empty | Comma-separated user IDs who approve tools and can always use the bot. |
| `TELEGRAM_ALLOWED_USER_IDS` | empty | Who else may use the bot. In groups, empty means everyone. |
| `TELEGRAM_GROUP_IDS` | empty | Groups the bot works in. |
| `TELEGRAM_OPEN_CHAT_IDS` | empty | Groups where every message goes to the agent. |
| `DM_POLICY` | `allowlist` | `allowlist`, `open`, or `off`. |
| `GROUP_POLICY` | `allowlist` | `allowlist`, `open` (any group), or `off`. |
| `OPEN_CHAT_REPLY_MODE` | `relay` | `relay` posts replies; `tool` posts only through `telegram_send_message`. |
| `PERMISSION_MODE` | `standard` | `strict`, `standard`, `acceptEdits`, or `unrestricted`. |
| `APPROVAL_MODE` | `admins` | `admins`, `requester`, `deny`, or `allow`. |
| `APPROVAL_TIMEOUT_SECONDS` | `300` | Undecided approvals are denied after this. |
| `ALLOWED_TOOLS` | default set | Comma-separated tool allowlist. |
| `ENABLE_TELEGRAM_TOOLS` | `true` | Give the agent `telegram_react` and `telegram_send_file`. |
| `ROUTES_FILE` | none | JSON file that pins chats or topics to existing conversations. See `routes.example.json`. |
| `CONVERSATION_MODEL` | agent default | Model for new conversations. |
| `STREAM_EDITS` | `false` | Stream replies by editing the message as it is written. |
| `STREAM_EDIT_INTERVAL_MS` | `1500` | Minimum time between streamed edits. |
| `SHOW_TOOL_CALLS` | `false` | Show a live list of tool calls. |
| `SHOW_REASONING` | `false` | Show the agent's reasoning while it thinks. |
| `LIFECYCLE_REACTIONS` | `false` | React to your message when a reply finishes, fails, or is cancelled. |
| `DEBOUNCE_MS` | `1500` | Wait this long to batch quick consecutive messages. |
| `MAX_IMAGE_BYTES` | 5 MB | Largest photo sent to the model. |
| `MAX_FILE_BYTES` | 20 MB | Largest file downloaded. |
| `TRANSCRIBE_PROVIDER` | `none` | Voice transcription provider. |
| `TRANSCRIBE_API_KEY` | none | Key for the transcription provider. |
| `REGISTER_COMMANDS` | `true` | Register the command menu with Telegram on start. |
| `TURN_TIMEOUT_SECONDS` | `900` | Longest a single reply may take. |
| `DATA_DIR` | `./data` | Where the bot keeps its small SQLite database. |
| `HEALTH_PORT` | `8080` | `/healthz` returns 200 once connected to Telegram. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warn`, or `error`. |

</details>

## 🚢 Deploying

Run exactly one copy of the bot per token. Two copies polling the same token fight over updates,
and Telegram answers the loser with `409 Conflict`. The bot keeps a small SQLite database in
`DATA_DIR` that maps chats to conversations, so give it a persistent volume.

[Deploying](docs/deploying.md) covers Docker Compose, systemd, and Fly.io.

## 🔁 Coming from the hosted version

Earlier versions of this repository ran on Modal, used a webhook, and let each user log in with
their own Letta API key and pick an agent. This version is a bot you run yourself for one agent:

- There is no `/login`, `/agent`, or `/project`. The agent and API key come from `.env`.
- The webhook is removed automatically when the bot starts polling.
- The agent no longer needs a `notify_via_telegram` tool or a bot token in its environment. When
  the agent speaks on its own, for example after a background task finishes, the bot posts it to
  the chat the conversation belongs to.

## 📄 License

[MIT](LICENSE)
