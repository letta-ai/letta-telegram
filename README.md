# Letta-Telegram Bot

A serverless Telegram bot that exposes your Letta agents to Telegram, enabling intelligent conversations with persistent memory and context awareness.

From an agent running on Telegram for a while:

> Letta Telegram Plugin
>
> Connect your Letta agents to Telegram for persistent, multi-platform conversations. This plugin enables seamless interaction with your stateful agents through Telegram's messaging interface.
>
> What is this?
>
> The Letta Telegram plugin bridges Letta's memory-native AI agents with Telegram's messaging platform. Your agents maintain full context and memory across conversations, whether you're chatting through the desktop app, web interface, or now Telegram.
>
> Perfect for:
> - On-the-go conversations with your personal AI assistant
> - Sharing agent access with team members via Telegram groups
> - Building conversational AI experiences that persist across platforms
> - Demonstrating Letta's stateful capabilities in a familiar messaging environment

## What This Does

This bot creates a bridge between Telegram and [Letta](https://letta.com) (formerly MemGPT), allowing you to:
- **Multi-tenant authentication** - Each user brings their own Letta API key
- Chat with stateful AI agents through Telegram
- Maintain conversation history and context across sessions
- **Switch between different agents per chat** using the `/agent` command
- **Persistent agent preferences** that survive deployments
- **Secure per-user credential storage** with encryption
- Deploy scalably on Modal's serverless infrastructure
- Handle both user-initiated and agent-initiated messages

## Quick Start

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

# Optional: Twilio SMS/WhatsApp credentials
modal secret create twilio \
  TWILIO_ACCOUNT_SID=$TWILIO_ACCOUNT_SID \
  TWILIO_AUTH_TOKEN=$TWILIO_AUTH_TOKEN \
  TWILIO_MESSAGING_SERVICE_SID=$TWILIO_MESSAGING_SERVICE_SID \
  TWILIO_SMS_FROM=$TWILIO_SMS_FROM \
  TWILIO_WHATSAPP_FROM=$TWILIO_WHATSAPP_FROM \
  TWILIO_VALIDATE_SIGNATURE=true

# Optional: Letta OAuth for "Sign in with Letta" (instead of API keys)
modal secret create letta-oauth \
  LETTA_OAUTH_CLIENT_ID=your_oauth_client_id \
  LETTA_OAUTH_CLIENT_SECRET=your_oauth_client_secret \
  LETTA_OAUTH_CALLBACK_URL=https://your-workspace--letta-telegram-bot-oauth-callback.modal.run

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

### 6. (Optional) Configure Twilio Webhook

Point your Twilio Messaging webhook(s) to your deployed Twilio endpoint:

- SMS/WhatsApp webhook: `POST https://your-app--twilio-webhook.modal.run`

In Twilio Console:
- For phone numbers: set the Messaging “A MESSAGE COMES IN” webhook to the URL above
- For WhatsApp: configure the Sandbox or WhatsApp-enabled number with the same webhook

Signature verification is supported when `TWILIO_VALIDATE_SIGNATURE=true` and `TWILIO_AUTH_TOKEN` are set.

RCS senders
- Recommended: Use a Messaging Service and attach your RCS sender; set `TWILIO_MESSAGING_SERVICE_SID`.
- Fallback: Set `TWILIO_RCS_FROM=rcs:your_rcs_sender` to send without a Messaging Service (only needed if you cannot use a Messaging Service). The app will also reuse the inbound `To` as the `From` when replying to incoming RCS, ensuring channel match.
```

## User Authentication

### For Bot Users

Once the bot is deployed, users interact with it through these commands:

```bash
# Get started
/start                   # Complete setup walkthrough for new users
/help                    # See all available commands

# Authentication (two options)
/login                   # Sign in with Letta account (OAuth - recommended)
/login sk-abc123...      # Authenticate with API key (legacy method)
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

# Memory & Preferences
/blocks                  # View agent's memory blocks
/block persona           # View specific memory block
/reasoning disable       # Hide agent reasoning messages

# Then just chat normally!
Hello, how are you?      # Regular conversation with your selected agent
```

For Twilio (SMS/WhatsApp), use the same commands in plain text:

```
/login              # Get a sign-in link (OAuth)
/login <api_key>    # Or authenticate with API key
/status
/agents
/agent <id>
/logout
```
Then chat normally by texting your message.

### Security Features

- **Per-User Encryption**: Each user's API key is encrypted with a unique key derived from their Telegram user ID
- **Automatic Message Deletion**: `/login` messages containing API keys are immediately deleted from chat history
- **Credential Isolation**: Users can only access their own Letta agents and data
- **Persistent Storage**: Credentials are securely stored and persist across bot restarts
- **Twilio Signature Validation**: Optional verification of incoming requests when enabled

### User Flow

1. **First Time**: User sends `/start` → Gets complete setup walkthrough
2. **Login**: User taps "Sign in with Letta" button → Authorizes in browser → Automatically connected
   - **Alternative**: User sends `/login <their_api_key>` → API key validated and stored
3. **Agent Selection**: User runs `/agent` → Sees their agents, selects one
4. **Chat**: User can now chat normally with their selected agent
5. **Management**: User can switch agents, check status, or logout anytime

**Alternative**: Users can send any message → Gets "Authentication Required" prompt with `/start` suggestion

### OAuth Setup (Optional but Recommended)

OAuth allows users to sign in with their Letta account instead of manually copying API keys. This provides a better user experience, especially on mobile.

**To enable OAuth:**

1. Create an OAuth app in the Letta admin panel at app.letta.com
2. Note your `client_id` and `client_secret`
3. Create the Modal secret:
   ```bash
   modal secret create letta-oauth \
     LETTA_OAUTH_CLIENT_ID=your_client_id \
     LETTA_OAUTH_CLIENT_SECRET=your_client_secret \
     LETTA_OAUTH_CALLBACK_URL=https://your-workspace--letta-telegram-bot-oauth-callback.modal.run
   ```
4. Register the callback URL in your Letta OAuth app settings:
   - The URL format is: `https://<workspace>--letta-telegram-bot-oauth-callback.modal.run`
   - Find your workspace name in the Modal dashboard

Once configured, users will see a "Sign in with Letta" button when they run `/start` or `/login`.

## Configuration Reference

### Modal Secrets Structure

Your bot credentials are stored as a Modal secret:

**`telegram-bot` secret:**
- `TELEGRAM_BOT_TOKEN`: Bot token from [@BotFather](https://t.me/botfather)
- `TELEGRAM_WEBHOOK_SECRET`: (Optional but recommended) Security token for webhook validation - must match the `secret_token` used when registering webhook
- `ENCRYPTION_MASTER_KEY`: Master key for encrypting user API keys (32+ characters)

**User credentials are stored separately and encrypted per-user in Modal Volumes.**

**`openai` secret (optional):**
- `OPENAI_API_KEY`: Enables audio transcription of voice and audio messages
- Optional: `OPENAI_TRANSCRIBE_MODEL` to override the default (`gpt-4o-mini-transcribe`)

When the OpenAI key is not provided, the bot will still work but will not transcribe audio messages.

**`letta-oauth` secret (optional but recommended):**
- `LETTA_OAUTH_CLIENT_ID`: OAuth client ID from your Letta OAuth app
- `LETTA_OAUTH_CLIENT_SECRET`: OAuth client secret
- `LETTA_OAUTH_CALLBACK_URL`: Full callback URL (must be registered in Letta OAuth app settings)

When OAuth is configured, users can sign in with their Letta account instead of manually entering API keys.

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

For Twilio (SMS/WhatsApp):

```
User Message → Twilio → Webhook → Authentication Check → User's Letta Agent → Response → Twilio (SMS/WhatsApp)
```

## Development & Testing

### Local Development

Test your bot locally before deployment:

```bash
modal serve main.py
```

This creates temporary endpoints you can use for testing.

### Available Endpoints

- `POST /telegram_webhook` - Receives Telegram messages
- `POST /twilio_webhook` - Receives Twilio SMS/WhatsApp messages
  - Also supports RCS when using a Messaging Service with an attached RCS sender
- `GET /oauth_callback` - OAuth callback for "Sign in with Letta" flow
- `GET /health_check` - Service health status

### Key Features

- **Real-time Streaming**: Messages stream from Letta agents in real-time
- **Agent Management**: Switch between different agents per chat with persistent storage
- **Error Handling**: Automatic retries with exponential backoff for 500 errors
- **Message Formatting**: Automatic conversion to Telegram MarkdownV2 format
- **Tool Visualization**: Shows when agents use tools like web search
- **Long Message Support**: Handles messages up to Telegram's 4,096 character limit
- **SMS & WhatsApp**: Optional Twilio integration for SMS and WhatsApp
  - RCS supported via Twilio Messaging Service (or `TWILIO_RCS_FROM`)

## Agent Management

### Commands

**Getting Started:**
- **`/start`** - Complete setup walkthrough for new users
- **`/help`** - Show available commands

**Authentication:**
- **`/login`** - Sign in with your Letta account (OAuth)
- **`/login <api_key>`** - Authenticate with API key (legacy method)
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
- **`/template ion`** - Create Ion agent (adaptive AI with advanced memory)
- **`/make-default-agent`** - Create a simple default agent
- **`/ade`** - Get web interface link for current agent
- **`/refresh`** - Update cached agent name if changed externally

**Memory Inspection:**
- **`/blocks`** - List all memory blocks for current agent
- **`/block <label>`** - View specific memory block content

**Tool Management:**
- **`/tool`** or **`/tool list`** - List attached and available tools
- **`/tool attach <name>`** - Attach a tool to your agent
- **`/tool detach <name>`** - Detach a tool from your agent
- **`/telegram-notify`** - Attach the notify_via_telegram tool to current agent (see note below)

**Shortcuts:**
- **`/shortcut`** - List your saved shortcuts
- **`/shortcut <name> <agent_id>`** - Create shortcut for quick switching
- **`/shortcut delete <name>`** - Delete a shortcut
- **`/switch <name>`** - Quickly switch to agent using shortcut (shows buttons for existing shortcuts)

**Preferences:**
- **`/reasoning enable|disable`** - Toggle agent reasoning message visibility
- **`/clear-preferences`** - Reset all user preferences (debug command)

### How It Works

1. **User Authentication**: Each user must authenticate with their own Letta API key using `/login`
2. **Persistent Storage**: Both credentials and agent selections are stored using Modal Volumes
3. **Per-User Isolation**: Each user sees only their own agents and data
4. **Per-Chat Settings**: Each chat can have its own agent selection per authenticated user
5. **Automatic Discovery**: The bot lists all agents from the authenticated user's Letta account
6. **Validation**: Agent IDs are validated against the user's Letta account before saving
7. **Security**: All user credentials are encrypted with per-user unique encryption keys
8. **Agent Templates**: Currently only Ion template is available - a sophisticated agent with advanced memory
9. **Interactive Shortcuts**: `/switch` command shows inline buttons for existing shortcuts
10. **Memory Inspection**: View agent memory blocks to understand internal state
11. **Reasoning Visibility**: Toggle agent thinking messages with `/reasoning` command

### Storage Structure

```
/data/
├── users/
│   └── {telegram_user_id}/
│       ├── credentials.json    # Encrypted API key or OAuth tokens + metadata
│       ├── shortcuts.json      # User's agent shortcuts
│       └── preferences.json    # User preferences (reasoning visibility, etc.)
├── chats/
│   └── {chat_id}/
│       ├── agent.json          # {"agent_id": "...", "agent_name": "...", "updated_at": "..."}
│       └── project.json        # {"project_id": "...", "project_name": "...", "project_slug": "..."}
└── oauth_pending/
    └── {state}.json            # Temporary OAuth state (expires after 10 minutes)
```

- **User credentials** are stored per Telegram user ID with encryption (supports both API keys and OAuth tokens)
- **Agent selections** are stored per chat ID
- **OAuth pending states** are temporary and auto-expire
- This structure provides both security isolation and functionality

### Message Processing Features

- **Async Processing**: Prevents Telegram webhook timeouts
- **Typing Indicators**: Shows bot is processing messages
- **Error Handling**: Robust error messages and retry logic
- **Context Preservation**: Includes user info in agent context
- **Polling System**: Waits for agent processing completion (up to 4 minutes)

## Advanced Features

### Memory Block Inspection

View and inspect your agent's memory blocks to understand their internal state:

```bash
# List all memory blocks
/blocks

# View specific block content
/block persona
/block human
/block working_theories  # For Ion agents
```

This is especially useful for understanding how Ion agents develop theories about you and track conversation context.

### Reasoning Message Control

Toggle visibility of agent reasoning/thinking messages:

```bash
/reasoning enable   # Show agent's internal thoughts
/reasoning disable  # Hide reasoning messages
```

Reasoning messages show the agent's internal monologue before they respond, giving insight into their thought process.

### Ion Agent Template

Ion is the only available agent template - a sophisticated AI companion with advanced memory architecture:

- **Adaptive Memory**: Develops theories about how you think and communicate
- **Persistent Context**: Remembers everything from previous conversations
- **Dynamic Learning**: Updates memory blocks based on interactions
- **Advanced Memory Blocks**: Includes `working_theories`, `notes_to_self`, and `active_questions`

Create Ion with: `/template ion`

### Proactive Notifications with telegram-notify

The `/telegram-notify` command attaches a `notify_via_telegram` tool to your agent, allowing it to send you messages. However, note:

- The agent must decide when to use this tool based on your instructions
- It won't automatically trigger in the background without external prompting
- You need to tell your agent when and why to notify you (e.g., "notify me when X happens")

For scheduled or event-driven notifications, consider using [Letta's Zapier integration](https://zapier.com/apps/letta/integrations) to:
- Schedule regular messages to your agent
- Trigger agent responses based on external events
- Create automated workflows that prompt your agent to check things and notify you

## Additional Resources

For detailed Letta usage and API documentation, visit:
- [Letta Documentation](https://docs.letta.com) - Official documentation
- [Letta API Reference](https://docs.letta.com/api-reference/overview) - API endpoints and examples
- [Letta GitHub](https://github.com/letta-ai/letta) - Source code and examples

## Troubleshooting

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

## Project Structure

```
letta-telegram/
├── main.py           # Main bot application with webhook handlers
├── requirements.txt  # Python dependencies
└── README.md        # This file

Twilio support is implemented in `main.py` with the `POST /twilio_webhook` endpoint and shares the same storage and Letta logic.
```

## Contributing

This project is part of the Letta AI ecosystem. For questions or contributions, please visit the [Letta-Telegram GitHub repository](https://github.com/letta-ai/letta-telegram).

## License

This project follows the same license as the main Letta project. See the [Letta repository](https://github.com/letta-ai/letta) for license details.
