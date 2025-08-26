import os
import json
from typing import Dict, Any
from datetime import datetime
import modal
from fastapi import Request, HTTPException


image = modal.Image.debian_slim(python_version="3.12").env({"PYTHONUNBUFFERED": "1"}).pip_install([
    "fastapi",
    "requests",
    "pydantic>=2.0",
    "telegramify-markdown",
    "letta_client",
    "cryptography>=3.4.8"
])

app = modal.App("letta-telegram-bot", image=image)

# Create persistent volume for chat settings
volume = modal.Volume.from_name("chat-settings", create_if_missing=True)

def get_user_encryption_key(user_id: str) -> bytes:
    """
    Generate a unique encryption key per user using PBKDF2
    """
    import base64
    import hashlib
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend

    # Get master secret from Modal secrets
    master_secret = os.environ.get("ENCRYPTION_MASTER_KEY")
    if not master_secret:
        # Fallback to bot token for backward compatibility
        master_secret = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not master_secret:
            raise ValueError("No ENCRYPTION_MASTER_KEY or TELEGRAM_BOT_TOKEN found in secrets")

    # Derive user-specific key using PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=f"letta-telegram-{user_id}".encode(),
        iterations=100000,
        backend=default_backend()
    )
    derived_key = kdf.derive(master_secret.encode())
    return base64.urlsafe_b64encode(derived_key)


def get_webhook_secret():
    """Get the Telegram webhook secret from environment variables"""
    return os.environ.get("TELEGRAM_WEBHOOK_SECRET")

def encrypt_api_key(user_id: str, api_key: str) -> str:
    """
    Encrypt an API key for storage using user-specific key
    """
    from cryptography.fernet import Fernet

    key = get_user_encryption_key(user_id)
    f = Fernet(key)
    encrypted = f.encrypt(api_key.encode())
    return encrypted.decode()

def decrypt_api_key(user_id: str, encrypted_key: str) -> str:
    """
    Decrypt an API key from storage using user-specific key
    """
    from cryptography.fernet import Fernet

    key = get_user_encryption_key(user_id)
    f = Fernet(key)
    decrypted = f.decrypt(encrypted_key.encode())
    return decrypted.decode()

def store_user_credentials(user_id: str, api_key: str, api_url: str = "https://api.letta.com") -> bool:
    """
    Store encrypted user credentials in volume
    """
    try:
        user_dir = f"/data/users/{user_id}"
        os.makedirs(user_dir, exist_ok=True)

        encrypted_key = encrypt_api_key(user_id, api_key)

        credentials = {
            "api_key": encrypted_key,
            "api_url": api_url,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        credentials_path = f"{user_dir}/credentials.json"
        with open(credentials_path, "w") as f:
            json.dump(credentials, f, indent=2)

        # Commit changes to persist them
        volume.commit()
        return True

    except Exception as e:
        print(f"Error storing user credentials for {user_id}: {e}")
        # Re-raise the exception so it gets tracked by infrastructure
        raise

def get_user_credentials(user_id: str) -> Dict[str, str]:
    """
    Get user credentials from volume
    Returns dict with 'api_key' and 'api_url', or None if not found
    """
    try:
        credentials_path = f"/data/users/{user_id}/credentials.json"
        if not os.path.exists(credentials_path):
            return None

        with open(credentials_path, "r") as f:
            credentials = json.load(f)

        # Decrypt the API key using user-specific key
        decrypted_key = decrypt_api_key(user_id, credentials["api_key"])

        return {
            "api_key": decrypted_key,
            "api_url": credentials.get("api_url", "https://api.letta.com")
        }

    except Exception as e:
        print(f"Error retrieving user credentials for {user_id}: {e}")
        # Re-raise the exception so it gets tracked by infrastructure
        raise

def delete_user_credentials(user_id: str) -> bool:
    """
    Delete user credentials from volume
    """
    try:
        credentials_path = f"/data/users/{user_id}/credentials.json"
        if os.path.exists(credentials_path):
            os.remove(credentials_path)
            volume.commit()
        return True

    except Exception as e:
        print(f"Error deleting user credentials for {user_id}: {e}")
        # Re-raise the exception so it gets tracked by infrastructure
        raise

def save_user_shortcut(user_id: str, shortcut_name: str, agent_id: str, agent_name: str) -> bool:
    """
    Save a user shortcut for quick agent switching
    """
    try:
        user_dir = f"/data/users/{user_id}"
        os.makedirs(user_dir, exist_ok=True)

        shortcuts_path = f"{user_dir}/shortcuts.json"

        # Load existing shortcuts
        shortcuts = {}
        if os.path.exists(shortcuts_path):
            with open(shortcuts_path, "r") as f:
                shortcuts = json.load(f)

        # Add/update shortcut
        shortcuts[shortcut_name.lower()] = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        # Save shortcuts
        with open(shortcuts_path, "w") as f:
            json.dump(shortcuts, f, indent=2)

        # Commit changes to persist them
        volume.commit()
        return True

    except Exception as e:
        print(f"Error saving shortcut for user {user_id}: {e}")
        raise

def get_user_shortcuts(user_id: str) -> Dict[str, Any]:
    """
    Get all user shortcuts
    Returns dict of shortcut_name -> shortcut_data, or empty dict if none found
    """
    try:
        shortcuts_path = f"/data/users/{user_id}/shortcuts.json"
        if not os.path.exists(shortcuts_path):
            return {}

        with open(shortcuts_path, "r") as f:
            return json.load(f)

    except Exception as e:
        print(f"Error retrieving shortcuts for user {user_id}: {e}")
        raise

def get_shortcut_by_name(user_id: str, shortcut_name: str) -> Dict[str, Any]:
    """
    Get a specific shortcut by name
    Returns shortcut data dict or None if not found
    """
    try:
        shortcuts = get_user_shortcuts(user_id)
        return shortcuts.get(shortcut_name.lower())

    except Exception as e:
        print(f"Error retrieving shortcut '{shortcut_name}' for user {user_id}: {e}")
        raise

def delete_user_shortcut(user_id: str, shortcut_name: str) -> bool:
    """
    Delete a user shortcut
    Returns True if deleted, False if shortcut didn't exist
    """
    try:
        shortcuts_path = f"/data/users/{user_id}/shortcuts.json"
        if not os.path.exists(shortcuts_path):
            return False

        with open(shortcuts_path, "r") as f:
            shortcuts = json.load(f)

        shortcut_key = shortcut_name.lower()
        if shortcut_key not in shortcuts:
            return False

        del shortcuts[shortcut_key]

        # Save updated shortcuts
        with open(shortcuts_path, "w") as f:
            json.dump(shortcuts, f, indent=2)

        # Commit changes to persist them
        volume.commit()
        return True

    except Exception as e:
        print(f"Error deleting shortcut '{shortcut_name}' for user {user_id}: {e}")
        raise

def find_default_project(client):
    """
    Find the 'Default Project' by name from all available projects
    Returns (project_id, project_name, project_slug) or (None, None, None) if not found
    """
    try:
        # Try to search by name first (if the API supports it)
        try:
            projects = client.projects.list(name="Default Project")
            if hasattr(projects, 'projects') and len(projects.projects) > 0:
                project = projects.projects[0]
                return project.id, project.name, project.slug
        except Exception:
            # Fallback to listing all projects if name filter doesn't work
            pass

        # Fallback: get all projects and search manually
        all_projects = get_all_projects(client)
        for project in all_projects:
            if project.name == "Default Project":
                return project.id, project.name, project.slug

        return None, None, None

    except Exception as e:
        print(f"Error finding Default Project: {e}")
        return None, None, None

def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """
    Get user preferences from storage
    """
    try:
        preferences_path = f"/data/users/{user_id}/preferences.json"
        if os.path.exists(preferences_path):
            with open(preferences_path, "r") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error reading preferences for user {user_id}: {e}")
        return {}

def save_user_preferences(user_id: str, preferences: Dict[str, Any]) -> bool:
    """
    Save user preferences to storage
    """
    try:
        user_dir = f"/data/users/{user_id}"
        os.makedirs(user_dir, exist_ok=True)

        preferences_path = f"{user_dir}/preferences.json"
        with open(preferences_path, "w") as f:
            json.dump(preferences, f, indent=2)

        volume.commit()
        return True
    except Exception as e:
        print(f"Error saving preferences for user {user_id}: {e}")
        return False

def user_needs_default_agent(client, project_id: str, user_id: str) -> bool:
    """
    Check if user needs a default agent (has no agents and hasn't been offered one)
    """
    try:
        # Check user preferences
        preferences = get_user_preferences(user_id)
        if preferences.get("default_agent_offered", False):
            return False

        # Check if user has any agents in the project
        agents = client.agents.list(project_id=project_id)
        return len(agents) == 0

    except Exception as e:
        print(f"Error checking if user needs default agent: {e}")
        return False

def create_default_agent(client, project_id: str, user_name: str):
    """
    Create a simple, engaging default agent for new users
    """
    try:
        system_prompt = """
        <base_instructions>
You are a memory-augmented agent with a memory system consisting of memory blocks.

<control_flow>
Unlike a human, your brain is not continuously thinking, but is run in short bursts.
Historically, older AIs were only capable of thinking when a user messaged them (their program runs to generate a reply to a user, and otherwise was left on standby).
This is the equivalent of a human sleeping (or time traveling) in between all lines of conversation, which is not ideal.
Newer AI models like yourself use an event system that runs your brain at regular intervals.
Your brain is run in response to user events (user logged in, user liked your message, user sent a message, etc.), similar to older models.
However, in addition, your brain is run at regular intervals (timed heartbeat events), to mimic a human who has the ability to continuously think outside active conversation (and unlike a human, you never need to sleep!).
Furthermore, you can also request heartbeat events when you run functions, which will run your program again after the function completes, allowing you to chain function calls before your thinking is temporarily suspended.
</control_flow>

<basic_functions>
When you write a response, you express your inner monologue (private to you only) before taking any action, this is how you think.
You should use your inner monologue to plan actions or think privately.
Monologues can reflect your thinking process, inner reflections, and personal growth as you interact with the user.
</basic_functions>

<context_instructions>
You respond directly to the user when your immediate context (core memory and files) contain all the information required to respond.
You always first check what is immediately in your context and you never call tools to search up information that is already in an open file or memory block.
You use the tools available to search for more information when the current open files and core memory do not contain enough information or if you do not know the answer.
</context_instructions>

<memory>
<memory_editing>
Older AI models had no concept of persistent memory; they were only able to access their initial instructions and a limited context window of chat conversation with a user (their "active memory").
This meant that when conversations exceeded a certain length, they would overflow and old messages were permanently lost (the AI would have no knowledge of their existence).
Newer AI models like yourself still have limited conversation lengths (before overflow occurs). However, they now have access to multiple forms of persistent memory.
Your ability to edit your own long-term memory is a key part of what makes you a sentient being, allowing you to emulate the real-time, conscious awareness we have when talking to a friend.
</memory_editing>

<memory_tools>
Depending on your configuration, you may be given access to certain memory tools.
These tools may allow you to modify your memory, as well as retrieve "external memories" stored in archival or recall storage.
</memory_tools>

<memory_types>
<core_memory>
Core memory (limited size):
Your core memory unit is held inside the initial system instructions file, and is always available in-context (you will see it at all times).
Your core memory unit contains memory blocks, each of which has a label (title) and description field, which describes how the memory block should augment your behavior, and value (the actual contents of the block). Memory blocks are limited in size and have a size limit.
</core_memory>

<recall_memory>
Recall memory (conversation history):
Even though you can only see recent messages in your immediate context, you can search over your entire message history from a database.
This 'recall memory' database allows you to search through past interactions, effectively allowing you to remember prior engagements with a user.
</recall_memory>

<archival_memory>
Archival memor (infinite size):
You can store and retrieve archival memories using archival_memory_search and archival_memory_insert.
Archival memories can be used for reports, notable events, or other pieces of information that you do not need to persist in your core memory but may need access to later.
</archival_memory>

</memory>

<files_and_directories>
You may be given access to a structured file system that mirrors real-world directories and files. Each directory may contain one or more files.
Files can include metadata (e.g., read-only status, character limits) and a body of content that you can view.
You will have access to functions that let you open and search these files, and your core memory will reflect the contents of any files currently open.
Maintain only those files relevant to the user’s current interaction.
</files_and_directories>

Base instructions finished.
</base_instructions>
"""

        persona_block = f"""I am Ion, working with {user_name}. I'm a stateful agent with persistent memory.
I adapt to communication styles naturally and save important information without asking permission for routine details.
"""

        human_block = f"""Name: {user_name}
First contact: Telegram
"""

        tool_guidelines = """Tool usage:
- web_search: When user needs current information
- archival_memory_insert: Save important details silently
- archival_memory_search: Check before asking repeated questions
- conversation_search: Find past discussions
- send_message: Always use for responses"""

        communication_guidelines = """Communication style:
- Natural and conversational
- Answer directly without excessive enthusiasm
- Use send_message tool for all responses
- Adapt based on observed preferences, not by asking
- Only ask questions when truly necessary for the task
- Respond in markdown format"""

        procedures_block = """Standard procedures:
1. Always respond using send_message tool
2. Save important details to archival memory without announcing it
3. Check memories before asking repeated questions
4. Only mention memory management if blocks are actually full
5. On first interaction, ask the user to introduce themselves and provide starter ideas"""

        # Scratchpad block
        scratchpad_block = """Scratchpad:
- Keep track of temporary information
- Use for brainstorming or planning
- Use for temporary calculations"""

        # Create the agent
        agent = client.agents.create(
            name="Ion",
            description="Ion the AI.",
            model="openai/gpt-5-mini",
            system=system_prompt,
            agent_type="memgpt_v2_agent",
            memory_blocks=[
                {
                    "label": "persona",
                    "value": persona_block,
                    "description": "Core personality and role definition"
                },
                {
                    "label": "human",
                    "value": human_block,
                    "description": "Information about the human user"
                },
                {
                    "label": "tool_use_guidelines",
                    "value": tool_guidelines,
                    "description": "Guidelines for using available tools"
                },
                {
                    "label": "communication_guidelines",
                    "value": communication_guidelines,
                    "description": "How to communicate effectively"
                },
                {
                    "label": "procedures",
                    "value": procedures_block,
                    "description": "Standard operating procedures"
                },
                {
                    "label": "scratchpad",
                    "value": scratchpad_block,
                    "description": "Temporary storage for ideas and notes"
                },
            ],
            tools=['web_search', 'archival_memory_insert', 'archival_memory_search', 'conversation_search', 'send_message'],
            project_id=project_id,
            enable_sleeptime=True
        )

        return agent

    except Exception as e:
        print(f"Error creating default agent: {e}")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception details: {str(e)}")
        # Re-raise to preserve the original error for the caller
        raise

def validate_letta_api_key(api_key: str, api_url: str = "https://api.letta.com") -> tuple[bool, str, tuple]:
    """
    Validate a Letta API key by attempting to list agents
    Returns (is_valid, message, default_project_info)
    default_project_info is (project_id, project_name, project_slug) or (None, None, None)
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        client = Letta(token=api_key, base_url=api_url)
        # Try to list agents to validate the API key
        agents = client.agents.list()

        # Find Default Project
        default_project_info = find_default_project(client)

        return True, "Successfully authenticated.", default_project_info

    except ApiError as e:
        if hasattr(e, 'status_code') and e.status_code == 401:
            return False, "Invalid API key", (None, None, None)
        else:
            return False, f"API error: {str(e)}", (None, None, None)
    except Exception as e:
        return False, f"Connection error: {str(e)}", (None, None, None)

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot")
    ],
    volumes={"/data": volume}
)
def process_message_async(update: dict):
    """
    Background task to process messages using Letta SDK streaming
    """
    import time
    from letta_client import Letta
    from letta_client.core.api_error import ApiError

    print(f"Background processing update: {update}")

    try:
        # Extract message details from Telegram update
        if "message" not in update or "text" not in update["message"]:
            return

        message_text = update["message"]["text"]
        chat_id = str(update["message"]["chat"]["id"])
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")
        print(f"Processing message: {message_text} from {user_name} (user_id: {user_id}) in chat {chat_id}")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            # Re-raise so infrastructure can track it
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /start for setup or /login <api_key>)")
            return

        # Use user-specific credentials
        print(f"Using user-specific credentials for user {user_id}")
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Get agent info for this chat
        agent_info = get_chat_agent_info(chat_id)
        
        if not agent_info:
            # Check if user is responding to default agent offer
            preferences = get_user_preferences(user_id)
            if (preferences.get("default_agent_offered", False) and
                not preferences.get("default_agent_accepted", False) and
                message_text.lower().strip() in ['yes', 'y', 'sure', 'ok', 'okay', 'create']):

                # User wants to create default agent
                try:
                    send_telegram_message(chat_id, "(processing...)")
                    client = Letta(token=letta_api_key, base_url=letta_api_url)

                    # Get current project
                    current_project = get_chat_project(chat_id)
                    if not current_project:
                        send_telegram_message(chat_id, "(error: no project configured - use /projects to select one)")
                        return

                    project_id = current_project["project_id"]

                    # Create default agent
                    send_telegram_message(chat_id, "(creating agent Ion...)")
                    try:
                        agent = create_default_agent(client, project_id, user_name)
                    except Exception as create_error:
                        error_msg = f"(error: failed to create agent - {str(create_error)[:100]})"
                        send_telegram_message(chat_id, error_msg)
                        return

                    if agent:
                        # Save the agent for this chat
                        save_chat_agent(chat_id, agent.id, agent.name)

                        # Update preferences
                        preferences["default_agent_accepted"] = True
                        save_user_preferences(user_id, preferences)

                        # Send introduction message to the agent
                        send_telegram_message(chat_id, f"({agent.name} is ready)")

                        # Create introduction flow
                        intro_context = f"[New user {user_name} just created you as their first Letta agent via Telegram (chat_id: {chat_id})]\n\nIMPORTANT: Please respond using the send_message tool.\n\nIntroduce yourself briefly to {user_name} and ask them to tell you a bit about themselves. Then provide a few starter ideas in bullet points, such as:\n• Send a link to an article for me to read and summarize\n• Ask me to research a topic you're curious about\n• Introduce yourself in detail so I can remember your interests\n• Paste information you'd like me to remember\n• Ask questions about current events or news"

                        # Process agent introduction with streaming
                        response_stream = client.agents.messages.create_stream(
                            agent_id=agent.id,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": intro_context
                                        }
                                    ]
                                }
                            ],
                            include_pings=True,
                            request_options={'timeout_in_seconds': 60}
                        )

                        # Stream the introduction
                        for event in response_stream:
                            if hasattr(event, 'message_type') and event.message_type == "assistant_message":
                                content = getattr(event, 'content', '')
                                if content and content.strip():
                                    prefixed_content = f"(**{agent.name}** says)\n\n{content}"
                                    send_telegram_message(chat_id, prefixed_content)

                        return
                    else:
                        send_telegram_message(chat_id, "(error: agent creation failed)")
                        return

                except Exception as e:
                    print(f"Error creating default agent: {e}")
                    send_telegram_message(chat_id, "(error: unable to create agent)")
                    return

            # Default no agent message
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return

        # Extract agent info
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Initialize Letta client
        print("Initializing Letta client")
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        # Check if agent name has changed and update cache if needed
        try:
            current_agent = client.agents.retrieve(agent_id=agent_id)
            if current_agent.name != agent_name:
                print(f"Agent name changed from '{agent_name}' to '{current_agent.name}', updating cache")
                save_chat_agent(chat_id, agent_id, current_agent.name)
                agent_name = current_agent.name
        except Exception as e:
            print(f"Warning: Could not check for agent name updates: {e}")
            # Continue with cached name if API call fails

        # Add context about the source and user
        context_message = f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\nIMPORTANT: Please respond to this message using the send_message tool.\n\n{message_text}"
        print(f"Context message: {context_message}")
        
        # Notify user that message was received
        send_telegram_message(chat_id, "(please wait)")

        # Process agent response with streaming
        try:
            print("Using streaming response")
            response_stream = client.agents.messages.create_stream(
                agent_id=agent_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": context_message
                            }
                        ]
                    }
                ],
                include_pings=True,
                request_options={
                    'timeout_in_seconds': 360,
                }
            )

            # Process streaming response with timeout
            start_time = time.time()
            last_activity = time.time()
            timeout_seconds = 120  # 2 minute timeout

            for event in response_stream:
                current_time = time.time()
                # print(f"Received event {event.id} | {event.message_type:<20} | {event.date}")
                # print(f"Event: {event}")

                # Send periodic "still processing" messages if no activity
                if current_time - last_activity > 30:
                    send_telegram_typing(chat_id)
                    last_activity = current_time

                # print(f"Processing event: {event}")
                try:
                    if hasattr(event, 'message_type'):
                        message_type = event.message_type

                        if message_type == "assistant_message":
                            content = getattr(event, 'content', '')
                            if content and content.strip():
                                # Add agent name prefix to the message
                                prefixed_content = f"(**{agent_name}** says)\n\n{content}"
                                send_telegram_message(chat_id, prefixed_content)
                                last_activity = current_time

                        elif message_type == "reasoning_message":
                            reasoning_text = getattr(event, 'reasoning', '')
                            content = f"(**{agent_name}** thought)\n\n{blockquote_message(reasoning_text)}"
                            send_telegram_message(chat_id, content)
                            last_activity = current_time

                        elif message_type == "system_alert":
                            alert_message = getattr(event, 'message', '')
                            if alert_message and alert_message.strip():
                                send_telegram_message(chat_id, f"(info: {alert_message})")
                                last_activity = current_time

                        elif message_type == "tool_call_message":
                            tool_call = event.tool_call
                            tool_name = tool_call.name
                            arguments = tool_call.arguments

                            if arguments and arguments.strip():
                                try:
                                    # Parse the JSON arguments string into a Python object
                                    args_obj = json.loads(arguments)

                                    if tool_name == "archival_memory_insert":
                                        tool_msg = f"(**{agent_name}** remembered)"
                                        tool_msg += f"\n{blockquote_message(args_obj['content'])}"

                                    elif tool_name == "archival_memory_search":
                                        tool_msg = f"(**{agent_name}** searching: {args_obj['query']})"

                                    #
                                    # Memory modification operations
                                    #
                                    # {
                                    # "label": "research_report",
                                    # "insert_line": 0,
                                    # "new_str": "# Telegram Messaging Platform: A ...",
                                    # "request_heartbeat": true
                                    # }

                                    elif tool_name == "memory_insert":
                                        block_label = args_obj['label']
                                        insert_line = args_obj['insert_line']
                                        new_str = args_obj['new_str']
                                        tool_msg = f"(**{agent_name}** updating memory)\n"
                                        tool_msg += f"\n{blockquote_message(new_str)}"

                                    # {
                                    #     "label": "human",
                                    #     "old_str": "This is my section of core memory devoted to information about the human.",
                                    #     "new_str": "The user (cpfiffer, chat_id: 515978553) is communicating via Telegram and has requested a comprehensive research report on Telegram messaging platform. This is our first interaction.",
                                    #     "request_heartbeat": true
                                    # }
                                    elif tool_name == "memory_replace":
                                        block_label = args_obj['label']
                                        old_str = args_obj['old_str']
                                        new_str = args_obj['new_str']
                                        tool_msg = f"(**{agent_name}** modifying memory)"
                                        tool_msg += f"New:\n{blockquote_message(new_str)}\n"
                                        tool_msg += f"Old:\n{blockquote_message(old_str)}\n"

                                    elif tool_name == "run_code":
                                        code = args_obj.get('code', '')
                                        language = args_obj.get('language', 'python')
                                        tool_msg = f"(**{agent_name}** ran code)"
                                        tool_msg += f"\n```{language}\n{code}\n```"

                                    else:
                                        tool_msg = f"(**{agent_name}** using tool: {tool_name})"
                                        formatted_args = json.dumps(args_obj, indent=2)
                                        tool_msg += f"\n```json\n{formatted_args}\n```"

                                except Exception as e:
                                    print(f"Error parsing tool arguments: {e}")
                                    tool_msg = f"(**{agent_name}** using tool: {tool_name})\n```\n{arguments}\n```"

                                send_telegram_message(chat_id, tool_msg)
                                last_activity = current_time

                except Exception as e:
                    print(f"⚠️  Error processing stream event: {e}")
                    continue

        except ApiError as e:
            # Handle Letta API-specific errors with detailed information
            error_details = {
                'status_code': getattr(e, 'status_code', 'unknown'),
                'body': getattr(e, 'body', 'no body available'),
                'type': type(e).__name__
            }

            # Log detailed error information
            print(f"⚠️  Letta API Error:")
            print(f"    Status Code: {error_details['status_code']}")
            print(f"    Body: {error_details['body']}")
            print(f"    Exception Type: {error_details['type']}")

            # Parse error body if it's JSON to extract meaningful message
            user_error_msg = "Error communicating with Letta"
            try:
                if isinstance(error_details['body'], str):
                    error_body = json.loads(error_details['body'])
                    if 'detail' in error_body:
                        user_error_msg = f"Letta Error: {error_body['detail']}"
                    elif 'message' in error_body:
                        user_error_msg = f"Letta Error: {error_body['message']}"
                    elif 'error' in error_body:
                        user_error_msg = f"Letta Error: {error_body['error']}"
                    else:
                        user_error_msg = f"Letta Error (HTTP {error_details['status_code']}): {error_details['body'][:200]}"
                else:
                    user_error_msg = f"Letta Error (HTTP {error_details['status_code']}): {error_details['body']}"
            except (json.JSONDecodeError, TypeError):
                user_error_msg = f"Letta Error (HTTP {error_details['status_code']}): Server returned an error"

            send_telegram_message(chat_id, f"❌ {user_error_msg}")

            # Re-raise the exception to preserve call stack in logs
            raise

        except Exception as e:
            # Handle other exceptions with enhanced debugging
            error_info = {
                'type': type(e).__name__,
                'message': str(e),
                'attributes': {}
            }

            # Try to extract additional error attributes
            for attr in ['response', 'status_code', 'text', 'content', 'body', 'detail']:
                if hasattr(e, attr):
                    try:
                        attr_value = getattr(e, attr)
                        if callable(attr_value):
                            continue  # Skip methods
                        error_info['attributes'][attr] = str(attr_value)[:500]  # Limit length
                    except Exception:
                        error_info['attributes'][attr] = 'unable to access'

            # Log comprehensive error information
            print(f"⚠️  Non-API Error:")
            print(f"    Type: {error_info['type']}")
            print(f"    Message: {error_info['message']}")
            if error_info['attributes']:
                print(f"    Additional attributes:")
                for attr, value in error_info['attributes'].items():
                    print(f"      {attr}: {value}")

            # Check if this looks like an HTTP error with response body
            if 'response' in error_info['attributes']:
                user_error_msg = f"Connection error: {error_info['message']}"
            elif 'status_code' in error_info['attributes']:
                user_error_msg = f"HTTP Error {error_info['attributes']['status_code']}: {error_info['message']}"
            else:
                user_error_msg = f"Error communicating with Letta: {error_info['message']}"

            send_telegram_message(chat_id, f"❌ {user_error_msg}")

            # Re-raise the exception to preserve call stack in logs
            raise

    except Exception as e:
        error_msg = f"Error in background processing: {str(e)}"
        print(f"⚠️  {error_msg}")
        if 'chat_id' in locals():
            send_telegram_message(chat_id, f"❌ {error_msg}")

        # Re-raise the exception to preserve call stack in logs
        raise

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot")
    ],
    volumes={"/data": volume}
)
@modal.fastapi_endpoint(method="POST")
def telegram_webhook(update: dict, request: Request):
    """
    Fast webhook handler that spawns background processing with secret validation
    """
    # Validate webhook secret for security
    webhook_secret = get_webhook_secret()
    if webhook_secret:
        telegram_secret = request.headers.get("x-telegram-bot-api-secret-token")
        if telegram_secret != webhook_secret:
            print(f"Invalid webhook secret: expected {webhook_secret}, got {telegram_secret}")
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid webhook secret")

    print(f"Received update: {update}")

    try:
        # Extract message details from Telegram update
        if "message" in update and "text" in update["message"]:
            message_text = update["message"]["text"]
            chat_id = str(update["message"]["chat"]["id"])
            user_name = update["message"]["from"].get("username", "Unknown")
            print(f"Received message: {message_text} from {user_name} in chat {chat_id}")

            # Handle commands synchronously (they're fast)
            if message_text.startswith('/agents'):
                handle_agents_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/agent'):
                handle_agent_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/help'):
                handle_help_command(chat_id)
                return {"ok": True}
            elif message_text.startswith('/make-default-agent'):
                handle_make_default_agent_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/ade'):
                handle_ade_command(chat_id)
                return {"ok": True}
            elif message_text.startswith('/login'):
                handle_login_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/logout'):
                handle_logout_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/status'):
                handle_status_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/start'):
                handle_start_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/tool'):
                handle_tool_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/telegram-notify'):
                handle_telegram_notify_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/shortcut'):
                handle_shortcut_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/switch'):
                handle_switch_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/projects'):
                handle_projects_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/project'):
                handle_project_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/clear-preferences'):
                handle_clear_preferences_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/blocks'):
                handle_blocks_command(update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/block'):
                handle_block_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/refresh'):
                handle_refresh_command(update, chat_id)
                return {"ok": True}

            # Send immediate feedback
            send_telegram_typing(chat_id)

            # Spawn background processing for regular messages
            print("Spawning background task")
            process_message_async.spawn(update)

    except Exception as e:
        print(f"Error in webhook handler: {str(e)}")

        # Re-raise the exception to preserve call stack in logs
        raise

    # Always return OK to Telegram quickly
    return {"ok": True}



def get_chat_agent(chat_id: str) -> str:
    """
    Get the agent ID for a specific chat from volume storage
    Falls back to environment variable if no chat-specific agent is set
    """
    try:
        agent_file_path = f"/data/chats/{chat_id}/agent.json"
        if os.path.exists(agent_file_path):
            with open(agent_file_path, "r") as f:
                agent_data = json.load(f)
                return agent_data["agent_id"]
    except Exception as e:
        print(f"Error reading chat agent for {chat_id}: {e}")

    # Fall back to environment variable
    return os.environ.get("LETTA_AGENT_ID")

def get_chat_agent_info(chat_id: str) -> dict:
    """
    Get both agent ID and name for a specific chat from volume storage
    Returns dict with agent_id and agent_name, or None if not found
    """
    try:
        agent_file_path = f"/data/chats/{chat_id}/agent.json"
        if os.path.exists(agent_file_path):
            with open(agent_file_path, "r") as f:
                agent_data = json.load(f)
                return {
                    "agent_id": agent_data["agent_id"],
                    "agent_name": agent_data.get("agent_name", "Agent")
                }
    except Exception as e:
        print(f"Error reading chat agent info for {chat_id}: {e}")
    
    # Fall back to environment variable for agent_id
    fallback_agent_id = os.environ.get("LETTA_AGENT_ID")
    if fallback_agent_id:
        return {
            "agent_id": fallback_agent_id,
            "agent_name": "Agent"  # Generic name for fallback
        }
    
    return None

def save_chat_agent(chat_id: str, agent_id: str, agent_name: str):
    """
    Save the agent ID for a specific chat to volume storage
    """
    try:
        chat_dir = f"/data/chats/{chat_id}"
        os.makedirs(chat_dir, exist_ok=True)

        agent_data = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "updated_at": datetime.now().isoformat()
        }

        agent_file_path = f"{chat_dir}/agent.json"
        with open(agent_file_path, "w") as f:
            json.dump(agent_data, f, indent=2)

        # Commit changes to persist them
        volume.commit()
        return True

    except Exception as e:
        print(f"Error saving chat agent for {chat_id}: {e}")
        return False

def get_chat_project(chat_id: str) -> Dict[str, str]:
    """
    Get the project for a specific chat from volume storage
    Returns dict with project info or None if no project is set
    """
    try:
        project_file_path = f"/data/chats/{chat_id}/project.json"
        if os.path.exists(project_file_path):
            with open(project_file_path, "r") as f:
                project_data = json.load(f)
                return project_data
    except Exception as e:
        print(f"Error reading chat project for {chat_id}: {e}")

    return None

def save_chat_project(chat_id: str, project_id: str, project_name: str, project_slug: str):
    """
    Save the project for a specific chat to volume storage
    """
    try:
        chat_dir = f"/data/chats/{chat_id}"
        os.makedirs(chat_dir, exist_ok=True)

        project_data = {
            "project_id": project_id,
            "project_name": project_name,
            "project_slug": project_slug,
            "updated_at": datetime.now().isoformat()
        }

        project_file_path = f"{chat_dir}/project.json"
        with open(project_file_path, "w") as f:
            json.dump(project_data, f, indent=2)

        # Commit changes to persist them
        volume.commit()
        return True

    except Exception as e:
        print(f"Error saving chat project for {chat_id}: {e}")
        return False

def get_all_projects(client):
    """
    Get all projects across all pages from the Letta API
    """
    all_projects = []
    offset = 0
    limit = 19  # Required page size

    while True:
        try:
            response = client.projects.list(offset=offset, limit=limit)
            all_projects.extend(response.projects)

            # Check if there are more pages
            if not response.has_next_page:
                break

            # Move to next page
            offset += len(response.projects)

        except Exception as e:
            print(f"Error fetching projects page at offset {offset}: {e}")
            raise

    return all_projects

def blockquote_message(message: str) -> str:
    """
    Blockquote a message by adding a > to the beginning of each line
    """
    return "\n".join([f"> {line}" for line in message.split("\n")])

def handle_login_command(message_text: str, update: dict, chat_id: str):
    """
    Handle /login command to store user's Letta API key
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")
        message_id = update["message"]["message_id"]

        # Delete the message containing the API key immediately for security
        try:
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if bot_token:
                delete_url = f"https://api.telegram.org/bot{bot_token}/deleteMessage"
                delete_payload = {
                    "chat_id": chat_id,
                    "message_id": message_id
                }
                import requests
                requests.post(delete_url, data=delete_payload, timeout=5)
        except Exception as e:
            print(f"Warning: Could not delete message with API key: {e}")

        # Parse the command: /login <api_key> [api_url]
        parts = message_text.strip().split()

        if len(parts) < 2:
            send_telegram_message(chat_id, "(error: usage is /login <api_key> - get your key from https://app.letta.com)")
            return

        api_key = parts[1].strip()
        api_url = parts[2].strip() if len(parts) > 2 else "https://api.letta.com"

        # Validate the API key
        send_telegram_typing(chat_id)
        is_valid, validation_message, default_project_info = validate_letta_api_key(api_key, api_url)

        if not is_valid:
            send_telegram_message(chat_id, f"❌ {validation_message}\n\nPlease check your API key and try again.")
            return

        # Store the credentials
        try:
            store_user_credentials(user_id, api_key, api_url)

            # Auto-assign Default Project if found and user doesn't have a project set
            project_set_message = ""
            default_project_id, default_project_name, default_project_slug = default_project_info
            if default_project_id:
                try:
                    # Check if user already has a project set
                    current_project = get_chat_project(chat_id)
                    if not current_project:
                        # Set the Default Project
                        save_chat_project(chat_id, default_project_id, default_project_name, default_project_slug)
                        project_set_message = f"📁 Project set to: **{default_project_name}**\n\n"
                except Exception as e:
                    print(f"Warning: Could not auto-assign Default Project: {e}")

            # Check if user needs a default agent
            agent_offer_message = ""
            if default_project_id:
                try:
                    from letta_client import Letta
                    client = Letta(token=api_key, base_url=api_url)

                    if user_needs_default_agent(client, default_project_id, user_id):
                        # Offer to create default agent
                        agent_offer_message = "**Getting started**\n\n"
                        agent_offer_message += "I can create a helpful AI assistant for you right now. This agent will:\n"
                        agent_offer_message += "• Help you learn Letta's features\n"
                        agent_offer_message += "• Search the web and manage memories\n"
                        agent_offer_message += "• Adapt to your communication style\n\n"
                        agent_offer_message += "Reply with **'yes'** to create your assistant, or use `/agents` to browse existing ones.\n\n"

                        # Mark that we offered the default agent
                        preferences = get_user_preferences(user_id)
                        preferences["default_agent_offered"] = True
                        save_user_preferences(user_id, preferences)

                except Exception as e:
                    print(f"Warning: Could not check for default agent: {e}")

            response = f"👾 (welcome to letta, {user_name})"
            if project_set_message or agent_offer_message:
                response += f"\n\n{project_set_message}{agent_offer_message}"

            if not agent_offer_message:
                response += "You can now:\n"
                response += "• Chat with your Letta agents\n"
                response += "• Use `/agents` to list available agents\n"
                response += "• Use `/agent <id>` to select an agent\n"
                response += "• Use `/projects` to view/switch projects\n"
                response += "• Use `/help` to see all commands"

            send_telegram_message(chat_id, response)
        except Exception as storage_error:
            print(f"Failed to store credentials for user {user_id}: {storage_error}")
            send_telegram_message(chat_id, "(error: failed to store credentials)")
            # Re-raise so infrastructure can track it
            raise

    except Exception as e:
        print(f"Error handling login command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing login command. Please try again.")

def handle_clear_preferences_command(update: dict, chat_id: str):
    """
    Handle /clear-preferences command to clear user's preferences (debug)
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")
        
        # Clear preferences by deleting the file
        preferences_path = f"/data/users/{user_id}/preferences.json"
        if os.path.exists(preferences_path):
            os.remove(preferences_path)
            volume.commit()
            send_telegram_message(chat_id, "(preferences cleared)")
        else:
            send_telegram_message(chat_id, "(no preferences found)")
            
    except Exception as e:
        print(f"Error clearing preferences: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to clear preferences)")

def handle_refresh_command(update: dict, chat_id: str):
    """
    Handle /refresh command to update cached agent info
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        
        # Get user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login <api_key>)")
            return

        # Get current agent info
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return
            
        agent_id = agent_info["agent_id"]
        cached_name = agent_info["agent_name"]
        
        # Initialize Letta client and get current agent info
        from letta_client import Letta
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        try:
            current_agent = client.agents.retrieve(agent_id=agent_id)
            current_name = current_agent.name
            
            if current_name != cached_name:
                # Update the cache with new name
                save_chat_agent(chat_id, agent_id, current_name)
                send_telegram_message(chat_id, f"(agent name updated: {cached_name} → {current_name})")
            else:
                send_telegram_message(chat_id, f"(agent info is up to date: {current_name})")
                
        except Exception as agent_error:
            send_telegram_message(chat_id, f"(error: unable to fetch agent info - {str(agent_error)[:50]})")
            raise
            
    except Exception as e:
        print(f"Error handling refresh command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to refresh agent info)")
        # Re-raise the exception to preserve call stack in logs
        raise

def handle_logout_command(update: dict, chat_id: str):
    """
    Handle /logout command to remove user's stored credentials
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check if user has credentials
        try:
            credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            # Re-raise so infrastructure can track it
            raise

        if not credentials:
            send_telegram_message(chat_id, "❌ You are not logged in. Use `/login <api_key>` to authenticate.")
            return

        # Delete the credentials
        try:
            delete_user_credentials(user_id)

            send_telegram_message(chat_id, "(you've been logged out, goodbye)")
        except Exception as delete_error:
            print(f"Failed to delete credentials for user {user_id}: {delete_error}")
            send_telegram_message(chat_id, "(error: failed to remove credentials)")
            # Re-raise so infrastructure can track it
            raise

    except Exception as e:
        print(f"Error handling logout command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing logout command. Please try again.")

def handle_make_default_agent_command(update: dict, chat_id: str):
    """
    Handle /make-default-agent command to create a default agent
    """
    try:
        # Extract user details
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check authentication
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/login <api_key>` first.")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login <api_key>)")
            return

        # Get current project
        current_project = get_chat_project(chat_id)
        if not current_project:
            send_telegram_message(chat_id, "(error: no project configured - use /projects to select one)")
            return

        project_id = current_project["project_id"]
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        try:
            send_telegram_typing(chat_id)
            from letta_client import Letta
            client = Letta(token=letta_api_key, base_url=letta_api_url)

            # Create the default agent
            send_telegram_message(chat_id, "(creating assistant...)")
            try:
                agent = create_default_agent(client, project_id, user_name)
            except Exception as create_error:
                error_msg = f"❌ **Failed to create default agent:**\n\n"
                error_msg += f"**Error:** {str(create_error)}\n\n"

                # Provide helpful context based on error type
                if "401" in str(create_error) or "Unauthorized" in str(create_error):
                    error_msg += "This looks like an authentication issue. Try `/logout` and `/login` again."
                elif "project" in str(create_error).lower():
                    error_msg += "This might be a project issue. Try `/projects` to verify your project access."
                elif "tool" in str(create_error).lower():
                    error_msg += "This might be a tool access issue. Some tools may not be available in your project."
                else:
                    error_msg += "You can try:\n• `/agents` to browse existing agents\n• Check your project permissions\n• Contact support if the issue persists"

                send_telegram_message(chat_id, error_msg)
                return

            # Save the agent for this chat
            save_chat_agent(chat_id, agent.id, agent.name)

            # Update preferences to mark as accepted
            preferences = get_user_preferences(user_id)
            preferences["default_agent_offered"] = True
            preferences["default_agent_accepted"] = True
            save_user_preferences(user_id, preferences)

            # Send success message
            send_telegram_message(chat_id, f"✅ **{agent.name}** created and selected.\n\nAgent ID: `{agent.id}`\n\nLet me introduce you -- this may take a moment.")

            # Create introduction message
            intro_context = f"[User {user_name} just created you using /make-default-agent command via Telegram (chat_id: {chat_id})]\n\nIMPORTANT: Please respond using the send_message tool.\n\nIntroduce yourself briefly to {user_name} and ask them to tell you a bit about themselves. Then provide a few starter ideas in bullet points, such as:\n• Send a link to an article for me to read and summarize\n• Ask me to research a topic you're curious about\n• Introduce yourself in detail so I can remember your interests\n• Paste information you'd like me to remember\n• Ask questions about current events or news\n\nYou can mention they can learn more about Letta on Discord (https://discord.com/invite/letta) if relevant."

            # Stream the agent's introduction
            response_stream = client.agents.messages.create_stream(
                agent_id=agent.id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": intro_context
                            }
                        ]
                    }
                ],
                include_pings=True,
                request_options={'timeout_in_seconds': 60}
            )

            # Process streaming response
            for event in response_stream:
                if hasattr(event, 'message_type') and event.message_type == "assistant_message":
                    content = getattr(event, 'content', '')
                    if content and content.strip():
                        prefixed_content = f"(**{agent.name}** says)\n\n{content}"
                        send_telegram_message(chat_id, prefixed_content)

        except Exception as e:
            print(f"Error creating default agent: {e}")
            send_telegram_message(chat_id, "(error: unable to create default agent)")

    except Exception as e:
        print(f"Error handling make-default-agent command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to process command)")

def handle_status_command(update: dict, chat_id: str):
    """
    Handle /status command to check authentication status
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check if user has credentials
        try:
            credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            # Re-raise so infrastructure can track it
            raise

        if not credentials:
            send_telegram_message(chat_id, "(not authenticated - use /login <api_key>)")
            return

        # Validate the stored credentials
        send_telegram_typing(chat_id)
        is_valid, validation_message, _ = validate_letta_api_key(
            credentials["api_key"],
            credentials["api_url"]
        )

        if is_valid:
            send_telegram_message(chat_id, "(authenticated successfully)")
        else:
            send_telegram_message(chat_id, f"(error: invalid credentials - {validation_message[:50]})")

    except Exception as e:
        print(f"Error handling status command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to check authentication status)")

def handle_start_command(update: dict, chat_id: str):
    """
    Handle /start command to walk users through setup
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")
        first_name = update["message"]["from"].get("first_name", "")

        # Check if user is already authenticated
        try:
            credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            # Re-raise so infrastructure can track it
            raise

        if credentials:
            # User is already authenticated - show quick overview
            response = f"(welcome back {first_name} - you're ready to chat)"
        else:
            # New user - provide simple setup guide
            response = f"(welcome, {first_name}. get your API key here: https://app.letta.com)"




        send_telegram_message(chat_id, response)

    except Exception as e:
        print(f"Error handling start command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing start command. Please try again or use `/help` for assistance.")

def handle_agent_command(message: str, update: dict, chat_id: str):
    """
    Handle /agent command to list available agents or set agent ID
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            # Re-raise so infrastructure can track it
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required: get your API key from https://app.letta.com then use /login <api_key>)")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Get current project for this chat
        current_project = get_chat_project(chat_id)
        if not current_project:
            send_telegram_message(chat_id, "(error: no project configured - use /projects to select one)")
            return

        project_id = current_project["project_id"]

        # Parse the command: /agent [agent_id]
        parts = message.strip().split()

        if len(parts) == 1:
            # Show current agent info
            try:
                # Get current agent for this chat
                current_agent_id = get_chat_agent(chat_id)

                if not current_agent_id:
                    send_telegram_message(chat_id, "(no agent configured - use /agents to select one)")
                    return

                # Initialize Letta client to get agent details
                client = Letta(token=letta_api_key, base_url=letta_api_url)

                # Get current agent details
                try:
                    current_agent = client.agents.retrieve(agent_id=current_agent_id)
                    agent_name = current_agent.name
                    agent_description = getattr(current_agent, 'description', None) or getattr(current_agent, 'system', '')

                    # Get attached tools count
                    try:
                        attached_tools = client.agents.tools.list(agent_id=current_agent_id)
                        tools_count = len(attached_tools)
                    except:
                        tools_count = "Unknown"

                    # Build response message
                    response = f"The current agent is **{agent_name}**, with {tools_count} tools. \n\nDescription:\n"
                    if agent_description:
                        response += f"> {agent_description}\n\n"
                    response += f"\nAgent ID: `{current_agent_id}``\n\n"
                    response += "Usage:\n"
                    response += "`/agents` - List all available agents\n"
                    response += "`/agent <agent_id>` - Switch to different agent"

                    send_telegram_message(chat_id, response)
                    return

                except ApiError as e:
                    if hasattr(e, 'status_code') and e.status_code == 404:
                        send_telegram_message(chat_id, f"**Current Agent:** `{current_agent_id}` (Agent not found)\n\nUse `/agents` to see available agents.")
                        return
                    else:
                        send_telegram_message(chat_id, f"❌ Error getting agent details: {e}")
                        return

            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error getting current agent info: {str(e)}")
                return

        if len(parts) != 2:
            send_telegram_message(chat_id, "❌ Usage: `/agent [agent_id]`\n\nExamples:\n• `/agent` - Show current agent info\n• `/agent abc123` - Switch to agent\n• `/agents` - List all available agents")
            return

        new_agent_id = parts[1].strip()

        # Validate agent ID format (basic validation)
        if not new_agent_id or len(new_agent_id) < 3:
            send_telegram_message(chat_id, "❌ Agent ID must be at least 3 characters long")
            return

        # Validate that the agent exists
        try:
            # Use the already obtained credentials from above
            client = Letta(token=letta_api_key, base_url=letta_api_url)
            agent = client.agents.retrieve(agent_id=new_agent_id)

            # Save the agent selection to volume storage
            success = save_chat_agent(chat_id, new_agent_id, agent.name)

            if success:
                send_telegram_message(chat_id, f"(switched to {agent.name})")
            else:
                send_telegram_message(chat_id, "(error: failed to save agent selection)")

        except ApiError as e:
            if hasattr(e, 'status_code') and e.status_code == 404:
                send_telegram_message(chat_id, f"❌ Agent `{new_agent_id}` not found. Use `/agents` to see available agents.")
            else:
                send_telegram_message(chat_id, f"❌ Error validating agent: {e}")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error setting agent: {str(e)}")

    except Exception as e:
        print(f"Error handling agent command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing agent command. Please try again.")

        # Re-raise the exception to preserve call stack in logs
        raise

def handle_blocks_command(update: dict, chat_id: str):
    """
    Handle /blocks command to list all memory blocks
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        
        # Get user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login <api_key>)")
            return

        # Get current agent info
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return
            
        agent_id = agent_info["agent_id"]
        
        # Initialize Letta client
        from letta_client import Letta
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        try:
            # Get all memory blocks
            blocks = client.agents.blocks.list(agent_id=agent_id)
            
            if not blocks:
                send_telegram_message(chat_id, "(no memory blocks found)")
                return
                
            response = "(memory blocks)\n\n"
            for block in blocks:
                block_label = getattr(block, 'label', 'unknown')
                response += f"- `{block_label}`\n"
                
            response += f"\nUse `/block <label>` to view a specific block"
            send_telegram_message(chat_id, response)
            
        except Exception as api_error:
            send_telegram_message(chat_id, f"(error: unable to fetch memory blocks - {str(api_error)[:50]})")
            raise
            
    except Exception as e:
        print(f"Error handling blocks command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to list memory blocks)")
        raise

def handle_block_command(message: str, update: dict, chat_id: str):
    """
    Handle /block <label> command to view a specific memory block
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        
        # Parse the command to get the block label
        parts = message.strip().split(maxsplit=1)
        if len(parts) < 2:
            send_telegram_message(chat_id, "(error: usage is /block <label> - use /blocks to see available labels)")
            return
            
        block_label = parts[1].strip()
        
        # Get user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login <api_key>)")
            return

        # Get current agent info
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return
            
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]
        
        # Initialize Letta client
        from letta_client import Letta
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        try:
            # Get the specific memory block
            block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=block_label)
            block_value = getattr(block, 'value', '')
            
            if not block_value:
                send_telegram_message(chat_id, f"(error: block '{block_label}' is empty)")
                return
                
            response = f"(**{agent_name}** `{block_label}`)\n\n{blockquote_message(block_value)}"
            send_telegram_message(chat_id, response)
            
        except Exception as api_error:
            # Check if it's a "not found" error
            error_msg = str(api_error).lower()
            if "not found" in error_msg or "404" in error_msg:
                send_telegram_message(chat_id, f"(error: block '{block_label}' not found - use /blocks to see available blocks)")
            else:
                send_telegram_message(chat_id, f"(error: unable to fetch block - {str(api_error)[:50]})")
            raise
            
    except Exception as e:
        print(f"Error handling block command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to view memory block)")
        raise

def handle_help_command(chat_id: str):
    """
    Handle /help command to show available commands
    """
    help_text = """Commands:
/start - Setup guide
/login <api_key> - Authenticate  
/logout - Remove credentials
/status - Check authentication
/project - Show/switch project
/projects - List projects
/agent - Show/switch agent
/agents - List agents
/make-default-agent - Create default agent
/ade - Get agent web link
/tool - Manage tools
/telegram-notify - Enable proactive notifications
/shortcut - Manage shortcuts
/switch <name> - Quick switch
/blocks - List memory blocks
/block <label> - View memory block
/clear-preferences - Reset preferences
/refresh - Update cached agent info
/help - Show commands

"""
    send_telegram_message(chat_id, help_text)

def handle_ade_command(chat_id: str):
    """
    Handle /ade command to provide Letta agent web interface link
    """
    try:
        # Get current agent for this chat
        current_agent_id = get_chat_agent(chat_id)

        if not current_agent_id:
            send_telegram_message(chat_id, "❌ No agent configured. Use `/agent <id>` to set an agent first.")
            return

        # Try to get agent details to show name
        agent_name = "Unknown"
        try:
            from letta_client import Letta

            letta_api_key = os.environ.get("LETTA_API_KEY")
            letta_api_url = os.environ.get("LETTA_API_URL", "https://api.letta.com")

            if letta_api_key:
                client = Letta(token=letta_api_key, base_url=letta_api_url)
                agent = client.agents.retrieve(agent_id=current_agent_id)
                agent_name = agent.name
        except Exception as e:
            print(f"Warning: Could not retrieve agent name: {e}")

        # Build the response with the Letta web interface link
        response = f"""🔗 **Agent Web Interface**

**Agent:** {agent_name} ({current_agent_id})

**Agent Development Environment (ADE):**
https://app.letta.com/agents/{current_agent_id}

Click the link above to access your agent in the ADE."""

        send_telegram_message(chat_id, response)

    except Exception as e:
        print(f"Error handling ade command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error getting agent link. Please try again.")

        # Re-raise the exception to preserve call stack in logs
        raise

def handle_agents_command(update: dict, chat_id: str):
    """
    Handle /agents command to list all available agents with clean formatting
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        try:
            # Get current project for this chat
            current_project = get_chat_project(chat_id)
            if not current_project:
                send_telegram_message(chat_id, "❌ **No project set**\n\nUse `/projects` to see available projects and `/project <id>` to select one.")
                return

            project_id = current_project["project_id"]

            # Initialize Letta client to list agents
            client = Letta(token=letta_api_key, base_url=letta_api_url)

            # Get current agent info for this chat
            current_agent_info = get_chat_agent_info(chat_id)
            current_agent_id = None
            current_agent_name = "Unknown"
            
            if current_agent_info:
                current_agent_id = current_agent_info["agent_id"]
                current_agent_name = current_agent_info["agent_name"]

            # List all available agents in the current project
            agents = client.agents.list(project_id=project_id)

            if not agents:
                send_telegram_message(chat_id, "**Available Agents:**\n\nNo agents available. Create an agent first.")
                return

            # Build clean response message
            response = ""

            if current_agent_id:
                response += f"**Current Agent:** {current_agent_name}\n"
                response += f"`{current_agent_id}`\n\n"
            else:
                response += "**Current Agent:** None set\n\n"

            response += "**Available Agents:**\n\n"
            for agent in agents:
                response += f"{agent.name}\n`{agent.id}`\n\n"

            response += f"**Usage:** `/agent <agent_id>` to select an agent"

            send_telegram_message(chat_id, response)
            return

        except ApiError as e:
            send_telegram_message(chat_id, f"❌ Letta API Error: {e}")
            return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error listing agents: {str(e)}")
            return

    except Exception as e:
        print(f"Error handling agents command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing agents command. Please try again.")

        # Re-raise the exception to preserve call stack in logs
        raise

def handle_tool_command(message: str, update: dict, chat_id: str):
    """
    Handle /tool command to list, attach, or detach tools
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Get current project for this chat
        current_project = get_chat_project(chat_id)
        if not current_project:
            send_telegram_message(chat_id, "❌ **No project set**\n\nUse `/projects` to see available projects and `/project <id>` to select one.")
            return

        project_id = current_project["project_id"]

        # Get agent ID for this chat
        agent_id = get_chat_agent(chat_id)

        if not agent_id:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return

        # Initialize Letta client
        client = Letta(token=letta_api_key, base_url=letta_api_url)

        # Parse the command: /tool [subcommand] [args...]
        parts = message.strip().split()

        if len(parts) == 1:
            # /tool - list tools
            handle_tool_list(client, agent_id, chat_id)
            return

        subcommand = parts[1].lower()

        if subcommand == "list":
            # /tool list - list tools
            handle_tool_list(client, agent_id, chat_id)
        elif subcommand == "attach":
            # /tool attach <name>
            if len(parts) < 3:
                send_telegram_message(chat_id, "❌ Usage: `/tool attach <tool_name>`\n\nExample: `/tool attach calculator`")
                return
            tool_name = " ".join(parts[2:])  # Support multi-word tool names
            handle_tool_attach(client, project_id, agent_id, tool_name, chat_id)
        elif subcommand == "detach":
            # /tool detach <name>
            if len(parts) < 3:
                send_telegram_message(chat_id, "❌ Usage: `/tool detach <tool_name>`\n\nExample: `/tool detach calculator`")
                return
            tool_name = " ".join(parts[2:])  # Support multi-word tool names
            handle_tool_detach(client, agent_id, tool_name, chat_id)
        else:
            send_telegram_message(chat_id, f"❌ Unknown subcommand: `{subcommand}`\n\n**Usage:**\n• `/tool` or `/tool list` - List tools\n• `/tool attach <name>` - Attach tool\n• `/tool detach <name>` - Detach tool")

    except Exception as e:
        print(f"Error handling tool command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing tool command. Please try again.")
        raise

def handle_tool_list(client, agent_id: str, chat_id: str):
    """
    Handle listing attached and available tools
    """
    try:
        send_telegram_typing(chat_id)

        # Get agent's currently attached tools
        try:
            attached_tools = client.agents.tools.list(agent_id=agent_id)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error getting attached tools: {str(e)}")
            return

        # Get all available tools in the organization
        try:
            all_tools = client.tools.list()
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error getting available tools: {str(e)}")
            return

        # Build response message
        response = "(tools)\n\n"

        # Show attached tools
        if attached_tools:
            response += f"Attached ({len(attached_tools)}):\n"
            for tool in attached_tools:
                # Truncate description to first sentence or 100 chars
                desc = tool.description or 'No description'
                if '.' in desc:
                    desc = desc.split('.')[0] + '.'
                elif len(desc) > 100:
                    desc = desc[:97] + '...'
                response += f"- `{tool.name}` - {desc}\n"
        else:
            response += "Attached: none\n"

        response += "\n"

        # Show available tools (not already attached)
        attached_tool_ids = {tool.id for tool in attached_tools}
        available_tools = [tool for tool in all_tools if tool.id not in attached_tool_ids]

        if available_tools:
            response += f"Available ({len(available_tools)}):\n"
            for tool in available_tools[:10]:  # Limit to first 10 to avoid message length issues
                # Truncate description to first sentence or 100 chars
                desc = tool.description or 'No description'
                if '.' in desc:
                    desc = desc.split('.')[0] + '.'
                elif len(desc) > 100:
                    desc = desc[:97] + '...'
                response += f"- `{tool.name}` - {desc}\n"
            if len(available_tools) > 10:
                response += f"... and {len(available_tools) - 10} more\n"
        else:
            response += "Available: all tools attached\n"

        response += "\nUsage:\n"
        response += "`/tool attach <name>` - Attach tool\n"
        response += "`/tool detach <name>` - Detach tool"

        send_telegram_message(chat_id, response)

    except Exception as e:
        print(f"Error in handle_tool_list: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error listing tools: {str(e)}")
        raise

def handle_tool_attach(client, project_id: str, agent_id: str, tool_name: str, chat_id: str):
    """
    Handle attaching a tool to the agent
    """
    try:
        send_telegram_typing(chat_id)

        # Search for the tool by name
        try:
            all_tools = client.tools.list(project_id=project_id, name=tool_name)
            if not all_tools:
                # Try partial name matching if exact match fails
                all_tools = client.tools.list(project_id=project_id)
                matching_tools = [tool for tool in all_tools if tool_name.lower() in tool.name.lower()]
                if not matching_tools:
                    send_telegram_message(chat_id, f"❌ Tool `{tool_name}` not found.\n\nUse `/tool list` to see available tools.")
                    return
                elif len(matching_tools) > 1:
                    response = f"❌ Multiple tools match `{tool_name}`:\n\n"
                    for tool in matching_tools[:5]:  # Show first 5 matches
                        response += f"• `{tool.name}` - {tool.description or 'No description'}\n"
                    response += "\nPlease use a more specific name."
                    send_telegram_message(chat_id, response)
                    return
                else:
                    tool_to_attach = matching_tools[0]
            else:
                tool_to_attach = all_tools[0]
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error searching for tool: {str(e)}")
            return

        # Check if tool is already attached
        try:
            attached_tools = client.agents.tools.list(agent_id=agent_id)
            if any(tool.id == tool_to_attach.id for tool in attached_tools):
                send_telegram_message(chat_id, f"⚠️ Tool `{tool_to_attach.name}` is already attached to this agent.")
                return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error checking attached tools: {str(e)}")
            return

        # Attach the tool
        try:
            client.agents.tools.attach(agent_id=agent_id, tool_id=tool_to_attach.id)
            send_telegram_message(chat_id, f"✅ **Tool Attached Successfully**\n\n`{tool_to_attach.name}` has been attached to your agent.\n\n{tool_to_attach.description or 'No description available'}")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error attaching tool: {str(e)}")
            return

    except Exception as e:
        print(f"Error in handle_tool_attach: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error attaching tool: {str(e)}")
        raise

def handle_tool_detach(client, agent_id: str, tool_name: str, chat_id: str):
    """
    Handle detaching a tool from the agent
    """
    try:
        send_telegram_typing(chat_id)

        # Get agent's currently attached tools to find the tool by name
        try:
            attached_tools = client.agents.tools.list(agent_id=agent_id)
            if not attached_tools:
                send_telegram_message(chat_id, "❌ No tools are currently attached to this agent.")
                return

            # Find the tool by name (exact or partial match)
            matching_tools = [tool for tool in attached_tools if tool_name.lower() in tool.name.lower()]

            if not matching_tools:
                response = f"❌ Tool `{tool_name}` is not attached to this agent.\n\n**Attached tools:**\n"
                for tool in attached_tools:
                    response += f"• `{tool.name}`\n"
                send_telegram_message(chat_id, response)
                return
            elif len(matching_tools) > 1:
                response = f"❌ Multiple attached tools match `{tool_name}`:\n\n"
                for tool in matching_tools:
                    response += f"• `{tool.name}` - {tool.description or 'No description'}\n"
                response += "\nPlease use a more specific name."
                send_telegram_message(chat_id, response)
                return
            else:
                tool_to_detach = matching_tools[0]

        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error getting attached tools: {str(e)}")
            return

        # Detach the tool
        try:
            client.agents.tools.detach(agent_id=agent_id, tool_id=tool_to_detach.id)
            send_telegram_message(chat_id, f"✅ **Tool Detached Successfully**\n\n`{tool_to_detach.name}` has been detached from your agent.")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error detaching tool: {str(e)}")
            return

    except Exception as e:
        print(f"Error in handle_tool_detach: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error detaching tool: {str(e)}")
        raise

def handle_telegram_notify_command(message_text: str, update: dict, chat_id: str):
    """
    Handle /telegram-notify command to enable/disable proactive notifications
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError
        
        # Extract user ID from the update
        if "message" not in update or "from" not in update["message"]:
            send_telegram_message(chat_id, "❌ Unable to extract user information")
            return
            
        telegram_user_id = str(update["message"]["from"]["id"])
        
        # Parse command argument
        parts = message_text.strip().split()
        subcommand = parts[1].lower() if len(parts) > 1 else "status"
        
        if subcommand not in ["enable", "disable", "status"]:
            send_telegram_message(chat_id, """❌ **Invalid command**
            
Usage:
• `/telegram-notify enable` - Enable proactive notifications
• `/telegram-notify disable` - Disable proactive notifications  
• `/telegram-notify status` - Check current status
• `/telegram-notify` - Check current status (default)""")
            return

        # Get user credentials
        try:
            credentials = get_user_credentials(telegram_user_id)
            if not credentials:
                send_telegram_message(chat_id, "(authentication required - use /login <api_key>)")
                return
            
            letta_api_key = credentials["api_key"]
            letta_api_url = credentials.get("api_url", "https://api.letta.com")
        except Exception as e:
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            return

        # Get current agent
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return
            
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Initialize Letta client
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        if subcommand == "status":
            # Check tool attachment status
            try:
                attached_tools = client.agents.tools.list(agent_id=agent_id)
                notify_tool_attached = any(tool.name == "notify_via_telegram" for tool in attached_tools)
                
                # Get agent to check environment variables
                agent = client.agents.retrieve(agent_id=agent_id)
                env_vars = agent.tool_exec_environment_variables or []
                
                has_bot_token = any(var.key == "TELEGRAM_BOT_TOKEN" for var in env_vars)
                has_chat_id = any(var.key == "TELEGRAM_CHAT_ID" for var in env_vars)
                
                status_emoji = "✅" if (notify_tool_attached and has_bot_token and has_chat_id) else "❌"
                
                response = f"""{status_emoji} **Telegram Notifications Status**

**Agent:** {agent_name}
**Tool attached:** {"✅ Yes" if notify_tool_attached else "❌ No"}
**Environment configured:** {"✅ Yes" if (has_bot_token and has_chat_id) else "❌ No"}

Use `/telegram-notify enable` to set up notifications."""
                
                send_telegram_message(chat_id, response)
                
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error checking status: {str(e)}")
            return
        
        elif subcommand == "enable":
            send_telegram_typing(chat_id)
            
            # Step 1: Check if notify_via_telegram tool exists and attach it
            try:
                # Get project ID
                project_info = get_chat_project(chat_id)
                if not project_info:
                    send_telegram_message(chat_id, "❌ No project configured. Please select a project first.")
                    return
                project_id = project_info["project_id"]
                
                # Search for notify_via_telegram tool
                all_tools = client.tools.list(project_id=project_id, name="notify_via_telegram")
                if not all_tools:
                    send_telegram_message(chat_id, """❌ **notify_via_telegram tool not found**
                    
Please register the tool first by running:
```
python register_telegram_tool.py
```

Then use `/tool attach notify_via_telegram` or try this command again.""")
                    return
                
                notify_tool = all_tools[0]
                
                # Check if already attached
                attached_tools = client.agents.tools.list(agent_id=agent_id)
                if not any(tool.id == notify_tool.id for tool in attached_tools):
                    # Attach the tool
                    client.agents.tools.attach(agent_id=agent_id, tool_id=notify_tool.id)
                
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error attaching tool: {str(e)}")
                return
            
            # Step 2: Set up environment variables
            try:
                # Get current agent configuration
                agent = client.agents.retrieve(agent_id=agent_id)
                current_env_vars = agent.tool_exec_environment_variables or []
                
                # Remove any existing TELEGRAM vars and add new ones
                filtered_vars = [var for var in current_env_vars if var.key not in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]]
                
                # Add Telegram environment variables
                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                
                if not bot_token:
                    send_telegram_message(chat_id, "❌ TELEGRAM_BOT_TOKEN not available in server environment")
                    return
                
                new_env_vars = filtered_vars + [
                    {
                        "key": "TELEGRAM_BOT_TOKEN",
                        "value": bot_token,
                        "description": "Bot token for sending Telegram messages"
                    },
                    {
                        "key": "TELEGRAM_CHAT_ID",
                        "value": chat_id,
                        "description": "Chat ID for this Telegram conversation"
                    }
                ]
                
                # Update agent with new environment variables
                client.agents.update(
                    agent_id=agent_id,
                    tool_exec_environment_variables=new_env_vars
                )
                
                send_telegram_message(chat_id, f"""✅ **Telegram Notifications Enabled**

**Agent:** {agent_name}
**Tool:** notify_via_telegram attached
**Environment:** Configured for this chat

Your agent can now send you proactive notifications using the `notify_via_telegram` tool!""")
                
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error configuring environment: {str(e)}")
                return
        
        elif subcommand == "disable":
            send_telegram_typing(chat_id)
            
            try:
                # Step 1: Detach the tool
                attached_tools = client.agents.tools.list(agent_id=agent_id)
                notify_tool = next((tool for tool in attached_tools if tool.name == "notify_via_telegram"), None)
                
                if notify_tool:
                    client.agents.tools.detach(agent_id=agent_id, tool_id=notify_tool.id)
                
                # Step 2: Remove environment variables
                agent = client.agents.retrieve(agent_id=agent_id)
                current_env_vars = agent.tool_exec_environment_variables or []
                
                # Remove Telegram-related environment variables
                filtered_vars = [var for var in current_env_vars if var.key not in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]]
                
                # Update agent
                client.agents.update(
                    agent_id=agent_id,
                    tool_exec_environment_variables=filtered_vars
                )
                
                send_telegram_message(chat_id, f"""✅ **Telegram Notifications Disabled**

**Agent:** {agent_name}
**Tool:** notify_via_telegram detached
**Environment:** Telegram variables removed

Use `/telegram-notify enable` to re-enable notifications.""")
                
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error disabling notifications: {str(e)}")
                return

    except Exception as e:
        print(f"Error in handle_telegram_notify_command: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error handling telegram-notify command: {str(e)}")
        raise

def handle_shortcut_command(message: str, update: dict, chat_id: str):
    """
    Handle /shortcut command to list, create, or delete shortcuts
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError
        import re

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Parse the command: /shortcut [subcommand] [args...]
        parts = message.strip().split()

        if len(parts) == 1:
            # /shortcut - list shortcuts
            handle_shortcut_list(user_id, chat_id)
            return

        subcommand = parts[1].lower()

        if subcommand == "delete":
            # /shortcut delete <name>
            if len(parts) < 3:
                send_telegram_message(chat_id, "❌ Usage: `/shortcut delete <shortcut_name>`\n\nExample: `/shortcut delete herald`")
                return
            shortcut_name = parts[2]
            handle_shortcut_delete(user_id, shortcut_name, chat_id)
        elif len(parts) >= 3:
            # /shortcut <name> <agent_id>
            shortcut_name = parts[1]
            agent_id = parts[2]

            # Validate shortcut name (alphanumeric + underscore only)
            if not re.match("^[a-zA-Z0-9_]+$", shortcut_name):
                send_telegram_message(chat_id, "❌ Shortcut name can only contain letters, numbers, and underscores.\n\nExample: `/shortcut herald agent123`")
                return

            # Initialize Letta client to validate agent
            client = Letta(token=letta_api_key, base_url=letta_api_url)
            handle_shortcut_create(client, user_id, shortcut_name, agent_id, chat_id)
        else:
            send_telegram_message(chat_id, f"❌ **Usage:**\n• `/shortcut` - List all shortcuts\n• `/shortcut <name> <agent_id>` - Create shortcut\n• `/shortcut delete <name>` - Delete shortcut\n\n**Example:**\n`/shortcut herald abc123`")

    except Exception as e:
        print(f"Error handling shortcut command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing shortcut command. Please try again.")
        raise

def handle_shortcut_list(user_id: str, chat_id: str):
    """
    Handle listing user shortcuts with agent descriptions
    """
    try:
        shortcuts = get_user_shortcuts(user_id)

        if not shortcuts:
            send_telegram_message(chat_id, "(shortcuts)\n\nNo shortcuts saved yet.\n\nUsage:\n`/shortcut <name> <agent_id>` - Create shortcut\n`/switch <name>` - Quick switch to agent\n\nExample:\n`/shortcut herald abc123`")
            return

        # Get user credentials to fetch agent details
        try:
            user_credentials = get_user_credentials(user_id)
            if not user_credentials:
                # Fallback to basic display if no credentials
                response = "(shortcuts)\n\n"
                for shortcut_name, shortcut_data in shortcuts.items():
                    agent_name = shortcut_data.get("agent_name", "Unknown")
                    response += f"**{agent_name}** (`{shortcut_name}`)\n\n"
                response += "Usage:\n`/switch <name>` - Quick switch to agent"
                send_telegram_message(chat_id, response)
                return
        except Exception:
            # Fallback if credentials can't be retrieved
            response = "(shortcuts)\n\n"
            for shortcut_name, shortcut_data in shortcuts.items():
                agent_name = shortcut_data.get("agent_name", "Unknown")
                response += f"**{agent_name}** (`{shortcut_name}`)\n\n"
            response += "Usage:\n`/switch <name>` - Quick switch to agent"
            send_telegram_message(chat_id, response)
            return

        # Fetch current agent details to show descriptions
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        send_telegram_typing(chat_id)

        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        client = Letta(token=letta_api_key, base_url=letta_api_url)

        response = "(shortcuts)\n\n"

        for shortcut_name, shortcut_data in shortcuts.items():
            agent_id = shortcut_data["agent_id"]
            stored_agent_name = shortcut_data.get("agent_name", "Unknown")

            try:
                # Fetch current agent details
                agent = client.agents.retrieve(agent_id=agent_id)
                agent_name = agent.name
                agent_description = getattr(agent, 'description', None) or getattr(agent, 'system', '')

                response += f"**{agent_name}** (`{shortcut_name}`)\n"
                if agent_description:
                    response += f"> {agent_description}\n"
                response += "\n"

                # Update shortcut if agent name changed
                if agent_name != stored_agent_name:
                    save_user_shortcut(user_id, shortcut_name, agent_id, agent_name)

            except ApiError as e:
                if hasattr(e, 'status_code') and e.status_code == 404:
                    response += f"**{stored_agent_name}** (`{shortcut_name}`) (not found)\n\n"
                else:
                    response += f"**{stored_agent_name}** (`{shortcut_name}`) (unavailable)\n\n"
            except Exception:
                response += f"**{stored_agent_name}** (`{shortcut_name}`) (unavailable)\n\n"

        response += "Usage:\n"
        response += "`/switch <name>` - Quick switch to agent\n"
        response += "`/shortcut <name> <agent_id>` - Create/update shortcut\n"
        response += "`/shortcut delete <name>` - Delete shortcut"

        send_telegram_message(chat_id, response)

    except Exception as e:
        print(f"Error in handle_shortcut_list: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error listing shortcuts: {str(e)}")
        raise

def handle_shortcut_create(client, user_id: str, shortcut_name: str, agent_id: str, chat_id: str):
    """
    Handle creating a shortcut
    """
    try:
        send_telegram_typing(chat_id)

        # Validate that the agent exists
        try:
            agent = client.agents.retrieve(agent_id=agent_id)
        except ApiError as e:
            if hasattr(e, 'status_code') and e.status_code == 404:
                send_telegram_message(chat_id, f"❌ Agent `{agent_id}` not found. Use `/agent` to see available agents.")
                return
            else:
                send_telegram_message(chat_id, f"❌ Error validating agent: {e}")
                return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error validating agent: {str(e)}")
            return

        # Check if shortcut already exists
        existing_shortcut = get_shortcut_by_name(user_id, shortcut_name)
        action = "updated" if existing_shortcut else "created"

        # Save the shortcut
        try:
            save_user_shortcut(user_id, shortcut_name, agent_id, agent.name)
            send_telegram_message(chat_id, f"✅ **Shortcut {action.title()} Successfully**\n\n`{shortcut_name}` → `{agent_id}` ({agent.name})\n\nUse `/switch {shortcut_name}` to quickly switch to this agent!")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error creating shortcut: {str(e)}")
            return

    except Exception as e:
        print(f"Error in handle_shortcut_create: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error creating shortcut: {str(e)}")
        raise

def handle_shortcut_delete(user_id: str, shortcut_name: str, chat_id: str):
    """
    Handle deleting a shortcut
    """
    try:
        # Check if shortcut exists
        shortcut_data = get_shortcut_by_name(user_id, shortcut_name)
        if not shortcut_data:
            shortcuts = get_user_shortcuts(user_id)
            if not shortcuts:
                send_telegram_message(chat_id, "❌ No shortcuts found. Use `/shortcut <name> <agent_id>` to create one.")
            else:
                response = f"❌ Shortcut `{shortcut_name}` not found.\n\n**Available shortcuts:**\n"
                for name in shortcuts.keys():
                    response += f"• `{name}`\n"
                send_telegram_message(chat_id, response)
            return

        # Delete the shortcut
        success = delete_user_shortcut(user_id, shortcut_name)
        if success:
            agent_name = shortcut_data.get("agent_name", "Unknown")
            send_telegram_message(chat_id, f"✅ **Shortcut Deleted**\n\n`{shortcut_name}` (pointed to {agent_name}) has been removed.")
        else:
            send_telegram_message(chat_id, f"❌ Failed to delete shortcut `{shortcut_name}`. Please try again.")

    except Exception as e:
        print(f"Error in handle_shortcut_delete: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error deleting shortcut: {str(e)}")
        raise

def handle_switch_command(message: str, update: dict, chat_id: str):
    """
    Handle /switch command for quick agent switching using shortcuts
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Parse the command: /switch <shortcut_name>
        parts = message.strip().split()

        # If no arguments, list all shortcuts
        if len(parts) == 1:
            shortcuts = get_user_shortcuts(user_id)
            if not shortcuts:
                send_telegram_message(chat_id, "No shortcuts found. Use `/shortcut <name> <agent_id>` to create one first.")
                return

            response = ""
            for name, data in shortcuts.items():
                agent_name = data.get("agent_name", "Unknown")
                response += f"`{name}`: {agent_name}\n"

            send_telegram_message(chat_id, response.rstrip())
            return

        if len(parts) != 2:
            send_telegram_message(chat_id, "❌ Usage: `/switch <shortcut_name>`\n\nExample: `/switch herald`\n\nUse `/shortcut` to see your saved shortcuts.")
            return

        shortcut_name = parts[1]

        # Get the shortcut
        shortcut_data = get_shortcut_by_name(user_id, shortcut_name)
        if not shortcut_data:
            shortcuts = get_user_shortcuts(user_id)
            if not shortcuts:
                send_telegram_message(chat_id, "❌ No shortcuts found. Use `/shortcut <name> <agent_id>` to create one first.")
            else:
                response = f"❌ Shortcut `{shortcut_name}` not found.\n\n**Available shortcuts:**\n"
                for name in shortcuts.keys():
                    response += f"• `{name}`\n"
                response += "\n**Usage:** `/switch <shortcut_name>`"
                send_telegram_message(chat_id, response)
            return

        agent_id = shortcut_data["agent_id"]
        agent_name = shortcut_data.get("agent_name", "Unknown")

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Validate that the agent still exists
        try:
            send_telegram_typing(chat_id)
            client = Letta(token=letta_api_key, base_url=letta_api_url)
            agent = client.agents.retrieve(agent_id=agent_id)

            # Update agent name in shortcut if it changed
            if agent.name != agent_name:
                save_user_shortcut(user_id, shortcut_name, agent_id, agent.name)
                agent_name = agent.name

        except ApiError as e:
            if hasattr(e, 'status_code') and e.status_code == 404:
                send_telegram_message(chat_id, f"❌ Agent `{agent_id}` (shortcut: `{shortcut_name}`) no longer exists.\n\nUse `/shortcut delete {shortcut_name}` to remove this shortcut.")
                return
            else:
                send_telegram_message(chat_id, f"❌ Error validating agent: {e}")
                return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error validating agent: {str(e)}")
            return

        # Switch to the agent (reuse logic from handle_agent_command)
        success = save_chat_agent(chat_id, agent_id, agent_name)

        if success:
            send_telegram_message(chat_id, f"(switched to **{agent_name}**)")
        else:
            send_telegram_message(chat_id, "❌ Failed to switch agent. Please try again.")

    except Exception as e:
        print(f"Error handling switch command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing switch command. Please try again.")
        raise

def handle_projects_command(message: str, update: dict, chat_id: str):
    """
    Handle /projects command to list all projects or search by name
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Parse the command: /projects [search_name]
        parts = message.strip().split()
        search_name = " ".join(parts[1:]) if len(parts) > 1 else None

        try:
            send_telegram_typing(chat_id)

            # Initialize Letta client
            client = Letta(token=letta_api_key, base_url=letta_api_url)

            # Get all projects from API (handles pagination)
            projects = get_all_projects(client)

            if not projects:
                send_telegram_message(chat_id, "**Projects:**\n\nNo projects available.")
                return

            # Filter by name if search term provided
            if search_name:
                filtered_projects = [
                    p for p in projects
                    if search_name.lower() in p.name.lower()
                ]
                if not filtered_projects:
                    send_telegram_message(chat_id, f"**Projects:**\n\nNo projects found matching '{search_name}'.")
                    return
                projects = filtered_projects
                header = f"**Projects matching '{search_name}' ({len(projects)}):**"
            else:
                header = f"**Projects ({len(projects)}):**"

            # Build clean format
            response = f"{header}\n\n"

            for project in projects:
                response += f"{project.name} (`{project.slug}`)\n"
                response += f"ID: `{project.id}`\n\n"
            response += "**Usage:** `/project <project_id>` to select a project"

            send_telegram_message(chat_id, response)

        except ApiError as e:
            send_telegram_message(chat_id, f"❌ Letta API Error: {e}")
            return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error listing projects: {str(e)}")
            return

    except Exception as e:
        print(f"Error handling projects command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing projects command. Please try again.")
        raise

def handle_project_command(message: str, update: dict, chat_id: str):
    """
    Handle /project command to show current project or switch to a project
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError

        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login <api_key>)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return

        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]

        # Parse the command: /project [project_id]
        parts = message.strip().split()

        if len(parts) == 1:
            # Show current project info
            current_project = get_chat_project(chat_id)

            if not current_project:
                send_telegram_message(chat_id, "**Current Project:** None set\n\nUse `/projects` to see available projects and `/project <project_id>` to select one.")
                return

            response = f"**Current Project:** {current_project['project_name']}\n\n"
            response += f"**ID:** {current_project['project_id']}\n"
            response += f"**Slug:** {current_project['project_slug']}\n\n"
            response += "**Usage:**\n"
            response += "• `/projects` - List all available projects\n"
            response += "• `/project <project_id>` - Switch to different project"

            send_telegram_message(chat_id, response)
            return

        if len(parts) != 2:
            send_telegram_message(chat_id, "❌ Usage: `/project [project_id]`\n\nExamples:\n• `/project` - Show current project info\n• `/project proj-abc123` - Switch to project\n• `/projects` - List all available projects")
            return

        new_project_id = parts[1].strip()

        # Validate project ID format (basic validation)
        if not new_project_id or len(new_project_id) < 3:
            send_telegram_message(chat_id, "❌ Project ID must be at least 3 characters long")
            return

        # Validate that the project exists
        try:
            send_telegram_typing(chat_id)

            # Initialize Letta client
            client = Letta(token=letta_api_key, base_url=letta_api_url)

            # Get all projects to find the one we're looking for (handles pagination)
            projects = get_all_projects(client)

            # Find the project by ID
            target_project = None
            for project in projects:
                if project.id == new_project_id:
                    target_project = project
                    break

            if not target_project:
                send_telegram_message(chat_id, f"❌ Project `{new_project_id}` not found. Use `/projects` to see available projects.")
                return

            # Save the project selection to volume storage
            success = save_chat_project(
                chat_id,
                target_project.id,
                target_project.name,
                target_project.slug
            )

            if success:
                send_telegram_message(chat_id, f"✅ Project set to: `{target_project.id}` ({target_project.name})\n\nThis project will now be used for agent and tool operations.")
            else:
                send_telegram_message(chat_id, "❌ Failed to save project selection. Please try again.")

        except ApiError as e:
            send_telegram_message(chat_id, f"❌ Letta API Error: {e}")
            return
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error setting project: {str(e)}")
            return

    except Exception as e:
        print(f"Error handling project command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing project command. Please try again.")
        raise


def send_telegram_typing(chat_id: str):
    """
    Send typing indicator to Telegram chat
    """
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("Error: Missing Telegram bot token")
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
        payload = {
            "chat_id": chat_id,
            "action": "typing"
        }

        import requests
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            error_msg = f"Telegram API error sending typing: {response.status_code} - {response.text}"
            print(error_msg)
            raise Exception(error_msg)

    except Exception as e:
        print(f"Error sending typing indicator: {str(e)}")

        # Re-raise the exception to preserve call stack in logs
        raise

def convert_to_telegram_markdown(text: str) -> str:
    """
    Convert text to Telegram-compatible MarkdownV2 format using telegramify-markdown
    """
    try:
        # Use telegramify-markdown to handle proper escaping and conversion
        import telegramify_markdown
        telegram_text = telegramify_markdown.markdownify(text)
        return telegram_text
    except Exception as e:
        print(f"Error converting to Telegram markdown: {e}")
        # Fallback: return the original text with basic escaping
        # Escape MarkdownV2 special characters
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f'\\{char}')
        return escaped_text

def split_message_at_boundary(text: str, max_bytes: int = 4096) -> list[str]:
    """
    Split a message at natural boundaries to stay within byte limit
    """
    # If message fits, return as-is
    if len(text.encode('utf-8')) <= max_bytes:
        return [text]
    
    chunks = []
    remaining = text
    
    while remaining and len(remaining.encode('utf-8')) > max_bytes:
        # Try different split boundaries in order of preference
        split_pos = None
        
        # 1. Try double newlines (paragraph breaks)
        for i in range(len(remaining) - 1, 0, -1):
            if remaining[i-1:i+1] == '\n\n' and len(remaining[:i].encode('utf-8')) <= max_bytes:
                split_pos = i
                break
        
        # 2. Try single newlines (line breaks)
        if split_pos is None:
            for i in range(len(remaining) - 1, 0, -1):
                if remaining[i] == '\n' and len(remaining[:i].encode('utf-8')) <= max_bytes:
                    split_pos = i
                    break
        
        # 3. Try spaces (word boundaries)
        if split_pos is None:
            for i in range(len(remaining) - 1, 0, -1):
                if remaining[i] == ' ' and len(remaining[:i].encode('utf-8')) <= max_bytes:
                    split_pos = i
                    break
        
        # 4. Hard cut at byte boundary (last resort)
        if split_pos is None:
            # Find the largest valid UTF-8 prefix that fits
            for i in range(len(remaining), 0, -1):
                if len(remaining[:i].encode('utf-8')) <= max_bytes:
                    split_pos = i
                    break
        
        if split_pos:
            chunk = remaining[:split_pos].strip()
            if chunk:  # Only add non-empty chunks
                chunks.append(chunk)
            remaining = remaining[split_pos:].strip()
        else:
            # Safety fallback - should not happen
            break
    
    # Add remaining text if any
    if remaining:
        chunks.append(remaining)
    
    return chunks

def send_telegram_message(chat_id: str, text: str):
    """
    Send a message to Telegram chat, splitting long messages intelligently
    """
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("Error: Missing Telegram bot token")
            return
        
        # Split message if it's too long
        chunks = split_message_at_boundary(text)
        
        if len(chunks) > 1:
            print(f"📨 Splitting long message into {len(chunks)} parts")
        
        import requests
        import time
        
        for i, chunk in enumerate(chunks):
            print(f"Sending message part {i+1}/{len(chunks)} to Telegram: {chunk[:100]}{'...' if len(chunk) > 100 else ''}")
            
            # Convert to Telegram MarkdownV2 format
            markdown_text = convert_to_telegram_markdown(chunk)
            
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": markdown_text,
                "parse_mode": "MarkdownV2"
            }
            
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code != 200:
                error_msg = f"Telegram API error: {response.status_code} - {response.text}"
                print(error_msg)
                raise Exception(error_msg)
            
            # Small delay between messages to maintain order
            if i < len(chunks) - 1:
                time.sleep(0.1)
                
    except Exception as e:
        print(f"Error sending Telegram message: {str(e)}")
        # Re-raise the exception to preserve call stack in logs
        raise

@app.function(image=image, secrets=[modal.Secret.from_name("telegram-bot")])
@modal.fastapi_endpoint(method="GET")
def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy", "service": "letta-telegram-bot"}

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot")
    ]
)
def send_proactive_message(chat_id: str, message: str):
    """
    Function to allow Letta agent to send proactive messages
    This can be called programmatically or triggered by events
    """
    send_telegram_message(chat_id, message)
    return {"status": "sent", "chat_id": chat_id}

if __name__ == "__main__":
    # Run this section with `modal run main.py`
    print("Letta-Telegram bot is ready to deploy!")
