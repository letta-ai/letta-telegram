# Letta-Telegram Bot

A serverless Telegram bot that exposes your Letta agents to Telegram, enabling intelligent conversations with persistent memory and context awareness.

From an agent running on Telegram for a while:

> 📌 Letta Telegram Plugin
>
> Connect your Letta agents to Telegram for persistent, multi-platform conversations. This plugin enables seamless interaction with your stateful agents through Telegram's messaging interface.
>
> ✏ What is this?
>
> The Letta Telegram plugin bridges Letta's memory-native AI agents with Telegram's messaging platform. Your agents maintain full context and memory across conversations, whether you're chatting through the desktop app, web interface, or now Telegram.
>
> Perfect for:
> ⦁ On-the-go conversations with your personal AI assistant
> ⦁ Sharing agent access with team members via Telegram groups
> ⦁ Building conversational AI experiences that persist across platforms
> ⦁ Demonstrating Letta's stateful capabilities in a familiar messaging environment

## 🚀 What This Does

This bot creates a bridge between Telegram and [Letta](https://letta.com) (formerly MemGPT), allowing you to:
- **Multi-tenant authentication** - Each user brings their own Letta API key
- Chat with stateful AI agents through Telegram
- Maintain conversation history and context across sessions
- **Switch between different agents per chat** using the `/agent` command
- **Persistent agent preferences** that survive deployments
- **Secure per-user credential storage** with encryption
- Deploy scalably on Modal's serverless infrastructure
- Handle both user-initiated and agent-initiated messages

## ⚡ Quick Start

### Prerequisites

Before you begin, you'll need:
- [Modal](https://modal.com) account (for deployment)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- **Users will need their own [Letta](https://letta.com) accounts with API keys**

### 1. Clone and Install

```bash
git clone https://github.com/letta-ai/letta-telegram.git
cd letta-telegram
pip install -r requirements.txt
modal setup
```

### 2. Multi-Tenant Authentication

This bot uses **multi-tenant authentication** - each user authenticates with their own Letta API key:

1. **Bot Owner**: You only need to deploy the bot - no Letta credentials required
2. **Bot Users**: Each user gets their own API key from [Letta's platform](https://app.letta.com)
3. Users authenticate with `/login <api_key>` command
4. Each user sees and manages only their own agents

### 3. Configure Modal Secrets

Create a Modal secret with your bot credentials and encryption key:

```bash
# Generate a secure encryption key (32+ characters)
# Example: openssl rand -base64 32
export ENCRYPTION_MASTER_KEY="your-secure-32-char-random-string-here"

# Telegram bot credentials + encryption key
modal secret create telegram-bot \
  TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather \
  TELEGRAM_WEBHOOK_SECRET=optional_secret_for_security \
  ENCRYPTION_MASTER_KEY=$ENCRYPTION_MASTER_KEY

# Optional: OpenAI API key for audio transcription support
modal secret create openai \
  OPENAI_API_KEY=$OPENAI_API_KEY

# Or if you already have them in environment variables:
modal secret create telegram-bot \
  TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN \
  TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET \
  ENCRYPTION_MASTER_KEY=$ENCRYPTION_MASTER_KEY

# (optional) Create the OpenAI secret from an env var
modal secret create openai \
  OPENAI_API_KEY=$OPENAI_API_KEY
```

**Important**: 
- `ENCRYPTION_MASTER_KEY` is used to encrypt user API keys with per-user unique keys
- Generate a secure random string (32+ characters) for this key
- Keep this key secure - losing it means losing access to stored user credentials

Audio transcription is enabled automatically when `OPENAI_API_KEY` is present via the `openai` secret.

### 4. Deploy to Modal

```bash
modal deploy main.py
```

Save the webhook URL from the deployment output (looks like `https://your-app--telegram-webhook.modal.run`).

### 5. Configure Telegram Webhook

Connect Telegram to your deployed bot with a simple curl command:

```bash
# Replace YOUR_BOT_TOKEN with your actual bot token
# Replace YOUR_WEBHOOK_URL with the URL from step 4
# Replace YOUR_WEBHOOK_SECRET with a secure random string (optional but recommended)
curl -X POST "https://api.telegram.org/bot{YOUR_BOT_TOKEN}/setWebhook" \
  -d "url={YOUR_WEBHOOK_URL}" \
  -d "secret_token={YOUR_WEBHOOK_SECRET}"
```

**Example:**
```bash
curl -X POST "https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/setWebhook" \
  -d "url=https://your-app--telegram-webhook.modal.run" \
  -d "secret_token=MySecureRandomString123"
```

## 🔐 User Authentication

### For Bot Users

Once the bot is deployed, users interact with it through these commands:

```bash
# Get started
/start                   # Complete setup walkthrough for new users
/help                    # See all available commands

# Authentication
/login sk-abc123...      # Authenticate with your Letta API key
/status                  # Check authentication status  
/logout                  # Remove stored credentials

# Project & Agent Management
/projects                # List available projects
/project project_id      # Switch to a specific project  
/agents                  # List your available agents
/agent agent_id_here     # Select an agent to chat with
/ade                     # Get web interface link for current agent

# Tools & Shortcuts
/tool                    # List available tools
/tool attach calculator  # Attach a tool to your agent
/shortcut                # List your shortcuts
/switch herald           # Quick switch using shortcut

# Then just chat normally!
Hello, how are you?      # Regular conversation with your selected agent
```

### Security Features

- **Per-User Encryption**: Each user's API key is encrypted with a unique key derived from their Telegram user ID
- **Automatic Message Deletion**: `/login` messages containing API keys are immediately deleted from chat history
- **Credential Isolation**: Users can only access their own Letta agents and data
- **Persistent Storage**: Credentials are securely stored and persist across bot restarts

### User Flow

1. **First Time**: User sends `/start` → Gets complete setup walkthrough
2. **Login**: User sends `/login <their_api_key>` → API key validated and stored
3. **Agent Selection**: User runs `/agent` → Sees their agents, selects one
4. **Chat**: User can now chat normally with their selected agent
5. **Management**: User can switch agents, check status, or logout anytime

**Alternative**: Users can send any message → Gets "Authentication Required" prompt with `/start` suggestion

## 🔧 Configuration Reference

### Modal Secrets Structure

Your bot credentials are stored as a Modal secret:

**`telegram-bot` secret:**
- `TELEGRAM_BOT_TOKEN`: Bot token from [@BotFather](https://t.me/botfather)
- `TELEGRAM_WEBHOOK_SECRET`: (Required for security) Security token for webhook validation - must match the `secret_token` used when registering webhook
- `ENCRYPTION_MASTER_KEY`: Master key for encrypting user API keys (32+ characters)

**User credentials are stored separately and encrypted per-user in Modal Volumes.**

**`openai` secret (optional):**
- `OPENAI_API_KEY`: Enables audio transcription of voice and audio messages
- Optional: `OPENAI_TRANSCRIBE_MODEL` to override the default (`gpt-4o-mini-transcribe`)

When the OpenAI key is not provided, the bot will still work but will not transcribe audio messages.

### Audio Messages

- Send voice notes or audio files to the bot, and they will be transcribed and sent to your Letta agent as text.
- Supported formats: `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, `webm` (Telegram voice notes are `ogg/opus`; these are automatically converted with ffmpeg).
- File size limit: up to 25 MB for transcription.

### Message Flow

```
User Message → Telegram → Webhook → Authentication Check → User's Letta Agent → Response → Telegram
```

1. User sends message to your Telegram bot
2. Telegram forwards via webhook to Modal endpoint  
3. Modal checks user authentication (requires `/login` first)
4. Modal retrieves user's encrypted API key and decrypts it
5. Message sent to user's specific Letta agent with user context
6. Agent response streamed back to Telegram in real-time

## 🛠️ Development & Testing

### Local Development

Test your bot locally before deployment:

```bash
modal serve main.py
```

This creates temporary endpoints you can use for testing.

### Available Endpoints

- `POST /telegram_webhook` - Receives Telegram messages  
- `GET /health_check` - Service health status
- `send_proactive_message()` - Function for agent-initiated messages

### Key Features

- **Real-time Streaming**: Messages stream from Letta agents in real-time
- **Agent Management**: Switch between different agents per chat with persistent storage
- **Error Handling**: Automatic retries with exponential backoff for 500 errors
- **Message Formatting**: Automatic conversion to Telegram MarkdownV2 format
- **Tool Visualization**: Shows when agents use tools like web search
- **Long Message Support**: Handles messages up to Telegram's 4,096 character limit

## 🤖 Agent Management

### Commands

**Getting Started:**
- **`/start`** - Complete setup walkthrough for new users
- **`/help`** - Show available commands

**Authentication:**
- **`/login <api_key>`** - Authenticate with your Letta API key
- **`/logout`** - Remove your stored credentials  
- **`/status`** - Check your authentication status

**Project Management:**
- **`/project`** - Show current project information
- **`/project <id>`** - Switch to a specific project
- **`/projects`** - List all available projects
- **`/projects <name>`** - Search projects by name

**Agent Management:**
- **`/agent`** - Show current agent information
- **`/agent <id>`** - Switch to a specific agent
- **`/agents`** - List all available agents
- **`/ade`** - Get web interface link for current agent

**Tool Management:**
- **`/tool`** or **`/tool list`** - List attached and available tools
- **`/tool attach <name>`** - Attach a tool to your agent
- **`/tool detach <name>`** - Detach a tool from your agent

**Shortcuts:**
- **`/shortcut`** - List your saved shortcuts
- **`/shortcut <name> <agent_id>`** - Create shortcut for quick switching
- **`/shortcut delete <name>`** - Delete a shortcut
- **`/switch <name>`** - Quickly switch to agent using shortcut

### How It Works

1. **User Authentication**: Each user must authenticate with their own Letta API key using `/login`
2. **Persistent Storage**: Both credentials and agent selections are stored using Modal Volumes
3. **Per-User Isolation**: Each user sees only their own agents and data
4. **Per-Chat Settings**: Each chat can have its own agent selection per authenticated user
5. **Automatic Discovery**: The bot lists all agents from the authenticated user's Letta account
6. **Validation**: Agent IDs are validated against the user's Letta account before saving
7. **Security**: All user credentials are encrypted with per-user unique encryption keys

### Storage Structure

```
/data/
├── users/
│   ├── {telegram_user_id_1}/
│   │   └── credentials.json    # Encrypted API key + metadata
│   ├── {telegram_user_id_2}/
│   │   └── credentials.json
└── chats/
    ├── {chat_id_1}/
    │   └── agent.json         # {"agent_id": "...", "agent_name": "...", "updated_at": "..."}
    ├── {chat_id_2}/
    │   └── agent.json
```

- **User credentials** are stored per Telegram user ID with encryption
- **Agent selections** are stored per chat ID
- This structure provides both security isolation and functionality

### Message Processing Features

- **Async Processing**: Prevents Telegram webhook timeouts
- **Typing Indicators**: Shows bot is processing messages
- **Error Handling**: Robust error messages and retry logic
- **Context Preservation**: Includes user info in agent context
- **Polling System**: Waits for agent processing completion (up to 4 minutes)

## 📚 Additional Resources

For detailed Letta usage and API documentation, visit:
- [Letta Documentation](https://docs.letta.com) - Official documentation
- [Letta API Reference](https://docs.letta.com/api-reference/overview) - API endpoints and examples
- [Letta GitHub](https://github.com/letta-ai/letta) - Source code and examples

## 🔍 Troubleshooting

**Bot not responding?**
- Check Modal deployment logs: `modal logs`
- Verify webhook URL is correct
- Ensure telegram-bot secret is properly configured with all required fields

**Authentication issues?**
- Verify user has valid Letta API key from https://app.letta.com
- Check that `ENCRYPTION_MASTER_KEY` is set in telegram-bot secret
- User may need to `/logout` and `/login` again if credentials are corrupted
- Run `/status` to check authentication state

**Letta API errors?**
- Each user must use their own valid API key
- Confirm user's API key has access to agents they're trying to use
- Check Letta service status at https://status.letta.com
- User can run `/status` to validate their stored credentials

**Deployment issues?**
- Run `modal setup` to verify authentication
- Ensure `ENCRYPTION_MASTER_KEY` is a secure 32+ character string
- Check that only `telegram-bot` secret exists (no `letta-api` secret needed)
- Verify all dependencies in requirements.txt are available

## 📝 Project Structure

```
letta-telegram/
├── main.py           # Main bot application with webhook handlers
├── requirements.txt  # Python dependencies
└── README.md        # This file
```

## 🤝 Contributing

This project is part of the Letta AI ecosystem. For questions or contributions, please visit the [Letta-Telegram GitHub repository](https://github.com/letta-ai/letta-telegram).

## 📜 License

This project follows the same license as the main Letta project. See the [Letta repository](https://github.com/letta-ai/letta) for license details.
