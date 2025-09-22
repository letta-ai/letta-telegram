---
title: Using the Letta Telegram Bot
subtitle: Connect your Letta agents to Telegram for conversations anywhere
slug: guides/telegram-bot
---

The Letta Telegram Bot (@letta_ai_bot) lets you chat with your Letta agents directly through Telegram, bringing persistent memory and intelligent conversations to your favorite messaging app.

Communications with Letta agents using the Telegram bot will modify the agent's state everywhere that Letta agents are available -- for example, you will see the Telegram messages appear in Letta's ADE.

## Getting Started

### Step 1: Find the Bot

Open Telegram and search for **@letta_ai_bot** or visit [t.me/letta_ai_bot](https://t.me/letta_ai_bot) directly.

### Step 2: Start Your First Conversation

Send `/start` to the bot. You'll receive an interactive welcome with buttons to guide you through setup.

### Step 3: Connect Your Letta Account

You'll need a Letta API key to use the bot:

1. **Get Your API Key**:
   - Go to [app.letta.com](https://app.letta.com)
   - Sign in or create a free account
   - Navigate to Settings → API Keys
   - Create a new API key and copy it

2. **Login to the Bot**:
   ```
   /login sk-your-api-key-here
   ```
   The bot will immediately delete your message for security and confirm successful authentication.

### Step 4: Select an Agent

View your available agents:
```
/agents
```

Select an agent to chat with:
```
/agent agent-id-here
```

### Step 5: Start Chatting

Once you've selected an agent, just send any message to start your conversation.

## Essential Commands - Complete Reference

### Authentication Commands

#### `/start` - Welcome and Setup Guide
Opens the interactive setup wizard for new and returning users.

**Behavior:**
- For new users: Shows welcome message with link to get API key
- For authenticated users: Shows welcome back message

**Example Output (New User):**
```
(hey sarah, welcome to letta)

looks like you're new here. want help getting started?

[sure] [i know what i'm doing]
```

**Example Output (Returning User with Agent):**
```
(welcome back sarah. you're chatting with research helper)

[switch agent] [view tools] [just chat]
```

**Example Output (Returning User, No Agent):**
```
(welcome back sarah. want to pick an agent?)

[show my agents]
[research helper] [personal assistant]
[maybe later]
```

#### `/login <api_key>` - Authenticate with Letta
Connects your Letta account to the Telegram bot. Your API key is immediately deleted from chat history for security.

**What it does:**
1. Validates your API key with Letta's servers
2. Encrypts and stores your credentials securely
3. Deletes the message containing your API key
4. Confirms successful authentication

**Example Command:**
```
/login sk-1234567890abcdef...
```

**Expected Output (Success, Has Agents):**
```
(all set. welcome sarah)

want to pick an agent?

[show my agents]
[research helper] [personal assistant]
[maybe later]
```

**Expected Output (Success, No Agents):**
```
(all set. welcome sarah)

looks like you need an agent. want to create one?

[ion (recommended)]
[research helper]
[personal assistant]
[creative buddy]
[study partner]
[show all templates]
```

**Expected Output (Invalid Key):**
```
❌ Authentication failed

The API key appears to be invalid. Please check:
1. You copied the complete key
2. The key hasn't expired
3. You're using the correct key

Get your API key at: https://app.letta.com
```

#### `/logout` - Remove Stored Credentials
Completely removes your stored API key and preferences from the bot.

**What it does:**
1. Deletes your encrypted credentials
2. Clears your agent selections
3. Removes all stored preferences

**Expected Output:**
```
✅ Logout successful

Your credentials have been removed.
Use /login <api_key> to authenticate again.
```

#### `/status` - Check Authentication Status
Shows your current authentication status and configuration.

**Expected Output (Authenticated):**
```
✅ Authentication Status

Authenticated: Yes
API URL: https://api.letta.com
Last Updated: 2024-01-15 10:30:00

You're ready to chat with your agents!
```

**Expected Output (Not Authenticated):**
```
❌ Not authenticated

Please use /login <api_key> to authenticate.
Get your API key at: https://app.letta.com
```

### Agent Management Commands

#### `/agents` - List Available Agents
Shows all agents in your current project with their IDs.

**Expected Output:**
```
(your agents)

currently using: research assistant

available (3):
• research assistant
  `agent-abc123def456`
• personal helper
  `agent-xyz789ghi012`
• code reviewer
  `agent-mno345pqr678`

[use personal helper]
[use code reviewer]
[← prev] [next →]
```

#### `/agent` - Show Current Agent
Displays information about your currently selected agent.

**Expected Output (Agent Selected):**
```
**Current Agent**

Name: Research Assistant
ID: `agent-abc123def456`
Model: gpt-4
Created: 2024-01-10

Memory Blocks:
• human (2000 chars)
• persona (2000 chars)
• archival_memory (10000 chars)

Use /ade to edit this agent in the web interface.
```

**Expected Output (No Agent):**
```
❌ No agent selected

Use /agents to see available agents
Use /agent <agent_id> to select one
```

#### `/agent <id>` - Select an Agent
Switches to a specific agent for your conversation.

**Example Command:**
```
/agent agent-xyz789ghi012
```

**Expected Output (Success):**
```
✅ Agent selected successfully!

Now chatting with: Personal Helper

This agent will be used for all messages in this chat.
```

**Expected Output (Not Found):**
```
❌ Agent not found: agent-invalid123

This agent doesn't exist or you don't have access to it.
Use /agents to see your available agents.
```

#### `/ade` - Agent Development Environment
Provides a direct link to edit your current agent in Letta's web interface.

**Expected Output:**
```
🔗 Agent Development Environment

Agent: Research Assistant
Link: https://app.letta.com/agents/agent-abc123def456

Click the link to edit your agent's:
• System prompts and personality
• Memory blocks
• Tool configuration
• Model settings
```

### Project Management Commands

#### `/projects` - List All Projects
Shows all projects in your Letta workspace.

**Expected Output:**
```
(projects)

currently using: main workspace
`project-123abc`

available (3):
• main workspace (3 agents)
  `project-123abc`
• development (5 agents)
  `project-456def`
• personal (2 agents)
  `project-789ghi`

[use development]
[use personal]
[← prev] [next →]
```

#### `/project` - Show Current Project
Displays information about your current project.

**Expected Output:**
```
**Current Project**

Name: Main Workspace
ID: `project-123abc`
Agents: 3
Created: 2024-01-01

Use /projects to see all projects
Use /project <id> to switch projects
```

#### `/project <id>` - Switch Project
Changes to a different project, which changes the available agents.

**Example Command:**
```
/project project-456def
```

**Expected Output:**
```
✅ Project switched successfully!

Now using: Development
5 agents available

Note: Your previous agent selection has been cleared.
Use /agents to see agents in this project.
```

### Tool Management Commands

#### `/tool` - Interactive Tool Management
Opens an interactive menu for managing tools attached to your agent.

**Expected Output:**
```
(tools for research assistant)

attached tools (3):
• web_search
• calculator
• send_telegram_message

[attach new tools]
[detach tools]
[back to main menu]
```

**Attach Menu (with pagination):**
Selecting "attach new tools" shows available tools with navigation:
```
(available tools - page 1/3)

[web_search]
[calculator]
[code_interpreter]
[wikipedia_search]
[weather_api]
[news_api]
[translator]
[file_processor]

[← prev] [next →] [back]
```

**Detach Menu:**
Selecting "detach tools" shows all attached tools:
```
(remove tools - 3 attached)

[web_search]
[calculator]
[send_telegram_message]

[back to tools]
```

#### `/tool attach <name>` - Direct Tool Attachment
Directly attaches a tool without using the interactive menu.

**Example Command:**
```
/tool attach code_interpreter
```

**Expected Output (Success):**
```
(tool attached)

code_interpreter is now available to your agent

execute python code in a sandbox environment for data analysis and computation
```

**Expected Output (Already Attached):**
```
(already attached)

code_interpreter is already available to this agent
```

**Expected Output (Not Found):**
```
(tool not found)

invalid_tool doesn't exist. use /tool to see available options
```

#### `/tool detach <name>` - Direct Tool Removal
Directly removes a tool without using the interactive menu.

**Example Command:**
```
/tool detach calculator
```

**Expected Output:**
```
(tool detached)

calculator has been removed from your agent
```

### Shortcut Commands

#### `/shortcut` - List Saved Shortcuts
Shows all your quick-access shortcuts.

**Expected Output:**
```
**Your Shortcuts**

work → Research Assistant
`agent-abc123def456`

personal → Personal Helper
`agent-xyz789ghi012`

code → Code Reviewer
`agent-mno345pqr678`

**Usage:**
• `/switch <name>` to quickly switch agents
• `/shortcut <name> <agent_id>` to create new
• `/shortcut delete <name>` to remove
```

#### `/shortcut <name> <agent_id>` - Create Shortcut
Creates a quick-access shortcut for an agent.

**Example Command:**
```
/shortcut research agent-abc123def456
```

**Expected Output:**
```
✅ **Shortcut Created**

`research` → Research Assistant

Now you can use `/switch research` to quickly select this agent.
```

#### `/switch <name>` - Quick Switch
Instantly switches to an agent using its shortcut.

**Example Command:**
```
/switch work
```

**Expected Output:**
```
✅ **Switched via shortcut**

Now chatting with: Research Assistant
(shortcut: work)
```

#### `/shortcut delete <name>` - Remove Shortcut
Deletes a saved shortcut.

**Example Command:**
```
/shortcut delete old_agent
```

**Expected Output:**
```
✅ **Shortcut Deleted**

Shortcut `old_agent` has been removed.
```

### Help Commands

#### `/help` - Command Reference
Shows a concise list of all available commands.

**Expected Output:**
```
Commands:
/start - Setup guide
/login <api_key> - Authenticate
/logout - Remove credentials
/status - Check authentication
/project - Show/switch project
/projects - List projects
/agent - Show/switch agent
/agents - List agents
/ade - Get agent web link
/tool - Manage tools
/shortcut - Manage shortcuts
/switch <name> - Quick switch
/help - Show this help

Send any other message to chat with your selected agent.
```

## Bot Design Philosophy

### Professional Yet Approachable

The Letta Telegram Bot provides a balance of professionalism and friendliness:
- Messages are clear and conversational, never overwhelming
- Responses feel natural and helpful
- Button interactions are clean and intuitive
- Error messages are informative, not harsh

### Interactive Yet Simple

**Buttons When Helpful**: Interactive buttons appear for common actions, but you can always type commands directly.

**Smart Defaults**: The bot anticipates your needs:
- Shows relevant agents as buttons after login
- Offers templates for quick agent creation
- Provides navigation shortcuts in menus

**Gentle Guidance**: Instead of overwhelming you with options, the bot guides you step-by-step through setup and usage.

## Understanding Your Agents

### What Are Letta Agents?

Letta agents are AI assistants with persistent memory. Unlike regular chatbots, they:
- **Remember Everything**: Your conversation history is preserved across sessions
- **Maintain Context**: They understand references to previous discussions
- **Use Tools**: Can search the web, run calculations, and more
- **Have Personalities**: Each agent can have unique traits and knowledge

### Managing Multiple Agents

You can create different agents for different purposes:
- **Personal Assistant**: General help and task management
- **Research Agent**: Specialized in finding and analyzing information
- **Creative Partner**: Focused on brainstorming and creative work
- **Study Buddy**: Helps with learning and retention

Switch between agents anytime with `/agent <id>` or use shortcuts for quick access.

## Agent Templates

When you first connect your Letta account or need to create new agents, the bot offers quick-start templates to get you up and running immediately.

### Available Templates

**Ion (Recommended)**: Advanced AI assistant with sophisticated memory architecture
- Features 6 specialized memory blocks for comprehensive understanding
- Adapts to your communication style and remembers preferences over time
- Professional yet conversational, matching your energy level
- Includes memory management tools for continuous learning
- Perfect for users who want an intelligent, adaptive assistant

**Research Helper**: Specialized in finding information, web searches, and analysis
- Pre-configured with web search and calculator tools
- Optimized persona for research tasks
- Great for fact-checking and data gathering

**Personal Assistant**: All-purpose helper for daily tasks and organization
- Includes scheduling, reminders, and general assistance capabilities
- Balanced tool set for versatile use
- Maintains context across personal conversations

**Creative Buddy**: Focused on brainstorming and creative projects
- Enhanced for ideation and creative problem solving
- Specialized prompts for artistic and creative tasks
- Helpful for writing, design, and innovation

**Study Partner**: Designed for learning and educational support
- Optimized for explaining concepts and testing knowledge
- Patient, encouraging personality for learning environments
- Great for students and continuous learners

### Using Templates

Templates appear as buttons when you first login or when you have no agents:
```
(all set. welcome sarah)

looks like you need an agent. want to create one?

[ion (recommended)]
[research helper]
[personal assistant]
[creative buddy]
[study partner]
[show all templates]
```

Simply tap a template button to instantly create and configure a new agent with that specialization. Ion is recommended for most users due to its advanced memory capabilities and adaptive personality.

### Ion's Advanced Memory System

Ion features a sophisticated 6-block memory architecture that enables deeper, more contextual conversations:

**Core Memory Blocks:**
1. **Persona**: Ion's adaptive personality that evolves to complement your communication style
2. **User Profile**: Dynamic profile that learns your preferences, interests, and patterns
3. **Memory Directives**: Guidelines for how Ion manages and updates its memory
4. **Interaction Patterns**: Tracks your communication preferences and response styles
5. **Knowledge Graph**: Builds semantic connections between topics you discuss
6. **Temporal Context**: Understands time-based patterns and routines in your life

**Key Features:**
- Proactive memory management using specialized tools
- Natural learning through conversation without interrogation
- Cross-conversation context retention
- Adaptive personality that matches your energy level
- Professional communication without excessive enthusiasm

Ion is designed to be your intelligent, adaptive assistant that gets better at helping you over time.

## Advanced Features

### Interactive Navigation

The bot uses interactive buttons throughout for easier navigation:
- **Command responses** include relevant action buttons
- **Menu systems** for tools, agents, and projects
- **Pagination controls** for long lists
- **Quick actions** accessible without typing commands

Example interactive flow:
```
/start → [sure] → /login key → [research helper] → ready to chat
```

### Using Tools

Your agents can use various tools to help you:

**Web Search**: Agents can search the internet for current information
```
User: What's the weather like in San Francisco today?
Agent: Let me search for current weather information... [searches web]
```

**View Available Tools**:
```
/tool
```

**Attach New Tools**:
```
/tool attach web_search
/tool attach calculator
```

### Navigation and Pagination

The bot automatically handles large lists with pagination:

**Agent Lists**: Shows 5 agents per page with next/previous buttons
**Tool Attachment**: Shows 8 tools per page when attaching
**Tool Detachment**: Shows all attached tools (no pagination)
**Projects**: Paginated display for multiple projects

### Creating Shortcuts

Save time with shortcuts for frequently used agents:

**Create a Shortcut**:
```
/shortcut work agent-abc123
/shortcut personal agent-xyz789
```

**Use Shortcuts**:
```
/switch work
/switch personal
```

### Working with Projects

Organize your agents by project:

**List Projects**:
```
/projects
```

**Switch Projects**:
```
/project project-id-here
```

## Tips for Better Conversations

### Be Specific
Your agent performs better with clear, specific requests:
- ❌ "Help me with that thing we discussed"
- ✅ "Help me refine the marketing strategy we discussed last Tuesday"

### Use Context
Reference previous conversations naturally:
- "Remember when we talked about the budget?"
- "Let's continue our discussion about the project timeline"

### Manage Long Conversations
For complex topics:
- Break down into smaller questions
- Ask for summaries periodically
- Use "Let's focus on..." to guide the conversation

### Leverage Memory
Your agent remembers everything:
- Personal preferences you've shared
- Project details and decisions
- Previous solutions and approaches

## Privacy and Security

### Your Data Is Protected

- **Encrypted Storage**: Your API key is encrypted with a unique key
- **Isolated Access**: You can only see your own agents and data
- **Secure Communication**: All messages are transmitted securely
- **No Sharing**: Your conversations are private to your account

### Best Practices

1. **Protect Your API Key**: Never share it with others
2. **Use `/logout`**: Always logout on shared devices
3. **Regular Checks**: Use `/status` to verify your session
4. **Report Issues**: Contact support if you notice anything unusual

## Troubleshooting

### Bot Not Responding

If the bot doesn't respond:
1. Check your internet connection
2. Verify you're logged in with `/status`
3. Try selecting an agent again with `/agent <id>`
4. Send `/help` to reset the conversation

### Authentication Issues

If you can't login:
1. Verify your API key at [app.letta.com](https://app.letta.com)
2. Make sure you're copying the entire key
3. Try generating a new API key
4. Use `/logout` first if you're having issues

### Agent Not Working

If your agent isn't responding properly:
1. Check that an agent is selected with `/agent`
2. Verify the agent exists with `/agents`
3. Try switching to another agent and back
4. Visit the ADE with `/ade` to check agent status

### Message Errors

If you see error messages:
- **"Authentication required"**: Use `/login` with your API key
- **"No agent selected"**: Choose an agent with `/agent <id>`
- **"Agent not found"**: The agent may have been deleted; use `/agents` to see available ones
- **"Timeout"**: Complex requests may take time; try again or simplify your request

## Common Use Cases

### Daily Planning
```
You: Good morning! What's on my schedule today?
Agent: Good morning! Based on our previous discussions, you have:
1. Team meeting at 10 AM about the Q4 roadmap
2. Lunch with Sarah to discuss the marketing campaign
3. Code review for the new feature at 3 PM
```

### Research Assistant
```
You: I need recent information about sustainable packaging trends
Agent: Let me search for the latest developments... [searches web]
Here are the key trends in sustainable packaging for 2024...
```

### Learning Partner
```
You: Can you quiz me on the Python concepts we studied yesterday?
Agent: Of course! Let's start with the list comprehensions we covered...
```

### Creative Brainstorming
```
You: Help me come up with names for my new coffee shop
Agent: Based on the vibe you described (cozy, bookish, vintage), here are some suggestions...
```

## Practical Examples and Edge Cases

### Setting Up Multiple Agents for Different Purposes

**Scenario:** You want different agents for work and personal use.

```
# First, create shortcuts for easy switching
/shortcut work agent-abc123
/shortcut personal agent-xyz789

# During work hours
/switch work
"Can you review the quarterly report I mentioned yesterday?"

# After work
/switch personal
"What ingredients did we decide on for the dinner party?"
```

### Handling Authentication Issues

**Edge Case:** Your API key expires or becomes invalid.

```
You: Hello, are you there?
Bot: ❌ Authentication error

Your stored credentials appear to be invalid.
Please try /logout then /login <new_api_key>

# Solution:
/logout
/login sk-new-api-key-here
```

### Managing Tools for Specific Tasks

**Scenario:** You need web search for a research project.

```
# Check current tools interactively
/tool

# Select "attach new tools" button
# Navigate to web_search and select it
# Or use direct command:
/tool attach web_search

You: What are the latest developments in quantum computing?
Agent: Let me search for recent information... [uses web_search tool]
```

### Working with Large Agent Lists

**Edge Case:** You have many agents and can't remember IDs.

```
# Use shortcuts for frequently used agents
/shortcut main agent-abc123def456

# Search projects if agents are organized by project
/projects research
/project project-research-001
/agents

# Use descriptive shortcut names
/shortcut research-quantum agent-qnt789
/shortcut research-climate agent-clm456
```

### Recovering from Errors

**Scenario:** Bot stops responding mid-conversation.

```
# First, check your status
/status

# If authenticated, check agent selection
/agent

# If no agent selected, reselect
/agents
/agent agent-abc123

# If issues persist, refresh credentials
/logout
/login sk-your-api-key
```

### Switching Context Quickly

**Scenario:** Multiple ongoing projects with different agents.

```
# Morning standup prep
/switch work
"Summarize yesterday's progress on the API integration"

# Client meeting
/switch client-project
"What were the three main concerns from our last meeting?"

# Personal reminder
/switch personal
"What time did I say I'd pick up the kids?"
```

### Tool Conflicts and Resolution

**Edge Case:** Multiple tools with similar names.

```
/tool attach search

Bot: (ambiguous tool name)

multiple tools match 'search':
• web_search - search the internet
• doc_search - search documents
• code_search - search codebases

try being more specific

# Solution:
/tool attach web_search
```

### Memory Continuity Across Sessions

**Example:** Continuing a complex discussion.

```
# Monday
You: Let's plan the product launch for next month
Agent: I'll help you plan the launch. Let's start with...

# Wednesday
You: Where did we leave off with the launch plan?
Agent: On Monday, we outlined the timeline and identified three key milestones...
```

### Handling Network Issues

**Edge Case:** Slow or interrupted connections.

```
You: [Sends message]
[No response for 30 seconds]

# Bot will show typing indicator if processing
# If timeout occurs:
Bot: (please wait)

that took longer than expected. the query might be complex - try breaking it into smaller parts
```

### Project and Agent Coordination

**Scenario:** Organizing agents across multiple projects.

```
# View all projects
/projects

# Switch to development project
/project project-dev-123

# See dev-specific agents
/agents

# Create shortcuts for cross-project access
/shortcut dev-backend agent-backend-456
/shortcut dev-frontend agent-frontend-789
```

## Getting Help

### Quick Help
- Send `/help` for a command reference
- Send `/start` for the setup guide

### Documentation
- [Letta Documentation](https://docs.letta.com) - Learn more about Letta agents
- [API Documentation](https://docs.letta.com/api-reference) - Advanced API features

### Support
- Visit [letta.com/support](https://letta.com/support) for help
- Join the [Letta Discord](https://discord.gg/letta) community
- Report issues on [GitHub](https://github.com/letta-ai/letta-telegram/issues)

## Frequently Asked Questions

**Q: Is the bot free to use?**
A: The bot itself is free, but you need a Letta account. Letta offers free tiers with usage limits.

**Q: Can I use multiple agents in the same chat?**
A: Yes! Switch between agents anytime with `/agent <id>` or shortcuts.

**Q: Will my agent remember conversations from other platforms?**
A: Yes, if you're using the same agent, it maintains memory across all platforms.

**Q: How long are conversations stored?**
A: Your agent's memory persists indefinitely as part of your Letta account.

**Q: Can I share my agent with others?**
A: Each user needs their own Letta account and API key to use the bot.

**Q: What happens if I delete an agent?**
A: The agent and all its memories are permanently removed from your Letta account.

**Q: Can I use the bot in group chats?**
A: The bot is designed for individual use. Each user needs their own authentication.

## Quick Reference Card

```
Essential Commands:
/start              - Setup guide
/login <key>        - Connect account
/agents             - List agents
/agent <id>         - Select agent
/help               - Command list

Quick Actions:
/switch <name>      - Use shortcut
/ade                - Edit agent
/status             - Check status
/logout             - Disconnect

Management:
/projects           - List projects
/tool               - Manage tools
/shortcut           - Manage shortcuts
```

Start chatting with your intelligent, memory-equipped AI agents today at [t.me/letta_ai_bot](https://t.me/letta_ai_bot)!
