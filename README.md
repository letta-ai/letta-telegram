# Letta-Telegram Bot

A serverless Telegram bot that connects your Telegram chats to Letta AI agents, enabling intelligent conversations with persistent memory and context awareness.

## 🚀 What This Does

This bot creates a bridge between Telegram and [Letta](https://letta.com) (formerly MemGPT), allowing you to:
- Chat with stateful AI agents through Telegram
- Maintain conversation history and context across sessions
- Deploy scalably on Modal's serverless infrastructure
- Handle both user-initiated and agent-initiated messages

## ⚡ Quick Start

### Prerequisites

Before you begin, you'll need:
- [Modal](https://modal.com) account (for deployment)
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- [Letta](https://letta.com) account with API access

### 1. Clone and Install

```bash
git clone <your-repo>
cd letta-telegram
pip install -r requirements.txt
modal setup
```

### 2. Set Up Your Letta Agent

First, create and configure a Letta agent:
1. Visit [Letta's platform](https://letta.com) and create an agent
2. Note your API key, agent ID, and API URL
3. See `cheatsheets/` directory for Letta usage guides

### 3. Configure Modal Secrets

Create two Modal secrets with your credentials:

```bash
# Telegram bot credentials
modal secret create telegram-bot \
  TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather \
  TELEGRAM_WEBHOOK_SECRET=optional_secret_for_security

# Letta API credentials  
modal secret create letta-api \
  LETTA_API_KEY=your_letta_api_key \
  LETTA_API_URL=https://api.letta.com \
  LETTA_AGENT_ID=your_agent_id
```

### 4. Deploy to Modal

```bash
modal deploy main.py
```

Save the webhook URL from the deployment output (looks like `https://your-app--telegram-webhook.modal.run`).

### 5. Configure Telegram Webhook

Run the setup script to connect Telegram to your deployed bot:

```bash
python setup.py
```

The script will prompt for your webhook URL and configure everything automatically.

## 🔧 Configuration Reference

### Modal Secrets Structure

Your credentials are stored as Modal secrets:

**`telegram-bot` secret:**
- `TELEGRAM_BOT_TOKEN`: Bot token from [@BotFather](https://t.me/botfather)
- `TELEGRAM_WEBHOOK_SECRET`: (Optional) Security token for webhook validation

**`letta-api` secret:**
- `LETTA_API_KEY`: Your Letta API authentication key
- `LETTA_API_URL`: API endpoint (default: `https://api.letta.com`)
- `LETTA_AGENT_ID`: Unique ID of your Letta agent

### Message Flow

```
User Message → Telegram → Webhook → Modal Function → Letta Agent → Response → Telegram
```

1. User sends message to your Telegram bot
2. Telegram forwards via webhook to Modal endpoint
3. Modal processes message asynchronously to avoid timeouts
4. Message sent to Letta agent with user context
5. Agent response polled and returned to Telegram

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

### Message Processing Features

- **Async Processing**: Prevents Telegram webhook timeouts
- **Typing Indicators**: Shows bot is processing messages
- **Error Handling**: Robust error messages and retry logic
- **Context Preservation**: Includes user info in agent context
- **Polling System**: Waits for agent processing completion (up to 4 minutes)

## 📚 Additional Resources

The `cheatsheets/` directory contains helpful guides:
- `letta-cheatsheet.md` - Core Letta concepts and API usage
- `letta-agent-management.md` - Creating and managing agents
- `letta-memory-management.md` - Working with agent memory
- `letta-messages-conversations.md` - Message handling patterns
- Additional specialized guides for advanced features

## 🔍 Troubleshooting

**Bot not responding?**
- Check Modal deployment logs: `modal logs`
- Verify webhook URL is correct
- Ensure secrets are properly configured

**Letta API errors?**
- Confirm API key and agent ID are valid
- Check Letta service status
- Review agent configuration and permissions

**Deployment issues?**
- Run `modal setup` to verify authentication
- Check requirements.txt dependencies
- Ensure Modal app name is unique