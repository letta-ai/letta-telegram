import os
import json
from typing import Dict, Any
from datetime import datetime
import modal


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

def validate_letta_api_key(api_key: str, api_url: str = "https://api.letta.com") -> tuple[bool, str]:
    """
    Validate a Letta API key by attempting to list agents
    Returns (is_valid, error_message)
    """
    try:
        from letta_client import Letta
        from letta_client.core.api_error import ApiError
        
        client = Letta(token=api_key, base_url=api_url)
        # Try to list agents to validate the API key
        agents = client.agents.list()
        return True, f"Successfully authenticated. Found {len(agents)} agents."
        
    except ApiError as e:
        if hasattr(e, 'status_code') and e.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"API error: {str(e)}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"

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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/logout` and `/login <api_key>` again.")
            # Re-raise so infrastructure can track it
            raise
        
        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate\n\nExample: `/login sk-123456789`")
            return
        
        # Use user-specific credentials
        print(f"Using user-specific credentials for user {user_id}")
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        
        # Get agent ID for this chat
        agent_id = get_chat_agent(chat_id)
        
        if not agent_id:
            send_telegram_message(chat_id, "❌ **No agent configured**\n\nUse `/agent` to see available agents and `/agent <id>` to select one.")
            return
        
        # Initialize Letta client
        print("Initializing Letta client")
        client = Letta(token=letta_api_key, base_url=letta_api_url)
        
        # Add context about the source and user
        context_message = f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\nIMPORTANT: Please respond to this message using the send_message tool.\n\n{message_text}"
        print(f"Context message: {context_message}")
        
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
                
                # Check for overall timeout
                if current_time - start_time > timeout_seconds:
                    send_telegram_message(chat_id, "⏰ Response took too long and was terminated. Please try again with a simpler message.")
                    break
                
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
                                send_telegram_message(chat_id, content)
                                last_activity = current_time

                        elif message_type == "reasoning_message":
                            content = "> **Reasoning**\n" + blockquote_message(getattr(event, 'reasoning', ''))
                            send_telegram_message(chat_id, content)
                            last_activity = current_time
                        
                        elif message_type == "system_alert":
                            alert_message = getattr(event, 'message', '')
                            if alert_message and alert_message.strip():
                                send_telegram_message(chat_id, f"ℹ️ {alert_message}")
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
                                        tool_msg = "**Remembered**"
                                        tool_msg += f"\n{blockquote_message(args_obj['content'])}"

                                    elif tool_name == "archival_memory_search":
                                        tool_msg = f"**Remembering** `{args_obj['query']}`"

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
                                        tool_msg = f"**Inserting into `{block_label}`**\n\n"
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
                                        tool_msg = f"**Modifying memory block `{block_label}`**\n\n"
                                        tool_msg += f"**New:**\n{blockquote_message(new_str)}"
                                        tool_msg += f"**Old:**\n{blockquote_message(old_str)}\n\n"

                                    else:
                                        tool_msg = f"🔧 Using tool: {tool_name}"
                                        formatted_args = json.dumps(args_obj, indent=2)
                                        tool_msg += f"\n```json\n{formatted_args}\n```"

                                except Exception as e:
                                    print(f"Error parsing tool arguments: {e}")
                                    tool_msg = f"🔧 Using tool: {tool_name}\n```\n{arguments}\n```"
                                
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
def telegram_webhook(update: dict):
    """
    Fast webhook handler that spawns background processing
    """
    print(f"Received update: {update}")
    
    try:
        # Extract message details from Telegram update
        if "message" in update and "text" in update["message"]:
            message_text = update["message"]["text"]
            chat_id = str(update["message"]["chat"]["id"])
            user_name = update["message"]["from"].get("username", "Unknown")
            print(f"Received message: {message_text} from {user_name} in chat {chat_id}")

            # Handle commands synchronously (they're fast)
            if message_text.startswith('/agent'):
                handle_agent_command(message_text, update, chat_id)
                return {"ok": True}
            elif message_text.startswith('/help'):
                handle_help_command(chat_id)
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
            send_telegram_message(chat_id, "❌ Usage: `/login <api_key>` or `/login <api_key> <api_url>`\n\nExample: `/login sk-123456789`\n\nYour API key can be found at https://app.letta.com")
            return
        
        api_key = parts[1].strip()
        api_url = parts[2].strip() if len(parts) > 2 else "https://api.letta.com"
        
        # Validate the API key
        send_telegram_typing(chat_id)
        is_valid, validation_message = validate_letta_api_key(api_key, api_url)
        
        if not is_valid:
            send_telegram_message(chat_id, f"❌ {validation_message}\n\nPlease check your API key and try again.")
            return
        
        # Store the credentials
        try:
            store_user_credentials(user_id, api_key, api_url)
            
            response = f"✅ **Authentication Successful!**\n\n"
            response += f"User: @{user_name}\n"
            response += f"{validation_message}\n\n"
            response += "You can now:\n"
            response += "• Chat with your Letta agents\n"
            response += "• Use `/agent` to select an agent\n"
            response += "• Use `/status` to check your authentication status\n"
            response += "• Use `/logout` to remove your credentials"
            
            send_telegram_message(chat_id, response)
        except Exception as storage_error:
            print(f"Failed to store credentials for user {user_id}: {storage_error}")
            send_telegram_message(chat_id, "❌ Failed to store credentials. Please try again.")
            # Re-raise so infrastructure can track it
            raise
            
    except Exception as e:
        print(f"Error handling login command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing login command. Please try again.")

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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/login <api_key>` again.")
            # Re-raise so infrastructure can track it
            raise
        
        if not credentials:
            send_telegram_message(chat_id, "❌ You are not logged in. Use `/login <api_key>` to authenticate.")
            return
        
        # Delete the credentials
        try:
            delete_user_credentials(user_id)
            
            response = f"✅ **Logged Out Successfully**\n\n"
            response += f"User @{user_name}, your credentials have been removed.\n"
            response += "Use `/login <api_key>` to authenticate again."
            send_telegram_message(chat_id, response)
        except Exception as delete_error:
            print(f"Failed to delete credentials for user {user_id}: {delete_error}")
            send_telegram_message(chat_id, "❌ Failed to remove credentials. Please try again.")
            # Re-raise so infrastructure can track it
            raise
            
    except Exception as e:
        print(f"Error handling logout command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing logout command. Please try again.")

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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/login <api_key>` again.")
            # Re-raise so infrastructure can track it
            raise
        
        if not credentials:
            response = "🔐 **Authentication Status**\n\n"
            response += f"User: @{user_name}\n"
            response += "Status: **Not Authenticated** ❌\n\n"
            response += "Use `/login <api_key>` to authenticate.\n"
            response += "Get your API key at https://app.letta.com"
            send_telegram_message(chat_id, response)
            return
        
        # Validate the stored credentials
        send_telegram_typing(chat_id)
        is_valid, validation_message = validate_letta_api_key(
            credentials["api_key"], 
            credentials["api_url"]
        )
        
        response = "🔐 **Authentication Status**\n\n"
        response += f"User: @{user_name}\n"
        
        if is_valid:
            response += "Status: **Authenticated** ✅\n"
            response += f"API URL: {credentials['api_url']}\n"
            response += f"{validation_message}\n\n"
            response += "Use `/agent` to select an agent."
        else:
            response += "Status: **Invalid Credentials** ❌\n"
            response += f"Error: {validation_message}\n\n"
            response += "Please use `/login <api_key>` to update your credentials."
        
        send_telegram_message(chat_id, response)
        
    except Exception as e:
        print(f"Error handling status command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error checking authentication status. Please try again.")

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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/login <api_key>` again.")
            # Re-raise so infrastructure can track it
            raise
        
        if credentials:
            # User is already authenticated - show quick overview
            response = f"👋 **Welcome back, {first_name}!**\n\n"
            response += "You're already authenticated and ready to go!\n\n"
            response += "**Quick Actions:**\n"
            response += "• `/agent` - View and select your agents\n"
            response += "• `/status` - Check your authentication status\n"
            response += "• `/help` - See all available commands\n\n"
            response += "Just type a message to start chatting with your agent!"
        else:
            # New user - provide complete setup guide
            response = f"🚀 **Welcome to the Letta Telegram Bot, {first_name}!**\n\n"
            response += "This bot connects you to your personal Letta AI agents. Here's how to get started:\n\n"
            
            response += "**Step 1: Get Your Letta API Key** 🔑\n"
            response += "1. Visit https://app.letta.com\n"
            response += "2. Sign up or log in to your account\n"
            response += "3. Create at least one AI agent\n"
            response += "4. Copy your API key from the settings\n\n"
            
            response += "**Step 2: Authenticate** 🔐\n"
            response += "Send me your API key using this command:\n"
            response += "`/login sk-your-api-key-here`\n\n"
            response += "⚠️ **Note**: Your message with the API key will be automatically deleted for security.\n\n"
            
            response += "**Step 3: Select an Agent** 🤖\n"
            response += "After logging in:\n"
            response += "• Use `/agent` to see your available agents\n"
            response += "• Use `/agent <agent_id>` to select one\n\n"
            
            response += "**Step 4: Start Chatting!** 💬\n"
            response += "Once you've selected an agent, just send any message to start a conversation.\n\n"
            
            response += "**Need Help?**\n"
            response += "• `/help` - See all commands\n"
            response += "• `/status` - Check your setup progress\n\n"
            
            response += "**Privacy & Security** 🛡️\n"
            response += "• Your API key is encrypted and stored securely\n"
            response += "• Only you can access your agents and data\n"
            response += "• Use `/logout` anytime to remove your credentials\n\n"
            
            response += "Ready to get started? Get your API key from https://app.letta.com and use `/login`!"
        
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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try `/login <api_key>` again.")
            # Re-raise so infrastructure can track it
            raise
        
        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse `/start` for a complete setup guide, or:\n\n1. Get your API key from https://app.letta.com\n2. Use `/login <api_key>` to authenticate")
            return
        
        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        
        # Parse the command: /agent [agent_id]
        parts = message.strip().split()
        
        if len(parts) == 1:
            # List available agents and show current selection
            try:
                # Initialize Letta client to list agents
                client = Letta(token=letta_api_key, base_url=letta_api_url)
                
                # Get current agent for this chat
                current_agent_id = get_chat_agent(chat_id)
                current_agent_name = "Unknown"
                
                # Try to get current agent details
                if current_agent_id:
                    try:
                        current_agent = client.agents.retrieve(agent_id=current_agent_id)
                        current_agent_name = current_agent.name
                    except:
                        pass
                
                # List all available agents
                agents = client.agents.list()
                
                if not agents:
                    send_telegram_message(chat_id, "❌ No agents available. Create an agent first.")
                    return
                
                # Build response message
                response = "🤖 **Available Agents**\n\n"
                
                if current_agent_id:
                    response += f"**Current Agent:** `{current_agent_id}` ({current_agent_name})\n\n"
                else:
                    response += "**Current Agent:** None set\n\n"
                
                response += "**Available Agents:**\n"
                for agent in agents:
                    status = "🟢" if agent.id == current_agent_id else "⚪"
                    response += f"{status} `{agent.id}` - {agent.name}\n"
                
                response += f"\n**Usage:** `/agent <agent_id>` to select an agent"
                
                send_telegram_message(chat_id, response)
                return
                
            except ApiError as e:
                send_telegram_message(chat_id, f"❌ Letta API Error: {e}")
                return
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Error listing agents: {str(e)}")
                return
        
        if len(parts) != 2:
            send_telegram_message(chat_id, "❌ Usage: `/agent [agent_id]`\n\nExamples:\n• `/agent` - List available agents\n• `/agent abc123` - Set agent ID")
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
                send_telegram_message(chat_id, f"✅ Agent set to: `{new_agent_id}` ({agent.name})\n\nYou can now chat with this agent!")
            else:
                send_telegram_message(chat_id, "❌ Failed to save agent selection. Please try again.")
                
        except ApiError as e:
            if hasattr(e, 'status_code') and e.status_code == 404:
                send_telegram_message(chat_id, f"❌ Agent `{new_agent_id}` not found. Use `/agent` to see available agents.")
            else:
                send_telegram_message(chat_id, f"❌ Error validating agent: {e}")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Error setting agent: {str(e)}")
    
    except Exception as e:
        print(f"Error handling agent command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing agent command. Please try again.")
        
        # Re-raise the exception to preserve call stack in logs
        raise

def handle_help_command(chat_id: str):
    """
    Handle /help command to show available commands
    """
    help_text = """🤖 **Letta Telegram Bot Commands**

**Getting Started:**
• `/start` - Complete setup guide for new users

**Authentication Commands:**
• `/login <api_key>` - Authenticate with your Letta API key
• `/logout` - Remove your stored credentials
• `/status` - Check your authentication status

**Agent Commands:**
• `/agent` - List all available agents and show current selection
• `/agent <id>` - Set your preferred agent for this chat
• `/ade` - Get link to current agent in the agent development environment (ADE)

**Other Commands:**
• `/help` - Show this help message

**Quick Setup:**
1. Use `/start` for a complete setup walkthrough
2. Get your API key from https://app.letta.com
3. Use `/login <api_key>` to authenticate
4. Use `/agent` to select an agent
5. Start chatting!

**Examples:**
• `/start` - Get step-by-step setup instructions
• `/login sk-123456789` - Authenticate with your API key
• `/agent` - Lists all available agents with their IDs and names
• `/agent abc123` - Switches to agent with ID "abc123"

**Note:** Your credentials and agent selections are saved securely and persist across sessions.
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

def send_telegram_message(chat_id: str, text: str):
    """
    Send a message to Telegram chat
    Note: Each message must be less than 4,096 UTF-8 characters
    """
    try:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("Error: Missing Telegram bot token")
            return

        # Log the message to the console
        print(f"Sending message to Telegram: {text}")
        
        # Check if message exceeds Telegram's 4,096 character limit
        if len(text.encode('utf-8')) > 4096:
            original_length = len(text.encode('utf-8'))
            # Truncate to fit within limit, leaving space for truncation notice
            truncation_notice = "\n\n[Message truncated due to length limit]"
            max_length = 4096 - len(truncation_notice.encode('utf-8'))
            
            # Truncate at character boundary to avoid breaking UTF-8
            truncated_text = text.encode('utf-8')[:max_length].decode('utf-8', errors='ignore')
            text = truncated_text + truncation_notice
            print(f"⚠️  Message truncated from {original_length} to {len(text.encode('utf-8'))} bytes")
        
        # Convert to Telegram MarkdownV2 format
        markdown_text = convert_to_telegram_markdown(text)
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": markdown_text,
            "parse_mode": "MarkdownV2"
        }
        
        import requests
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            error_msg = f"Telegram API error: {response.status_code} - {response.text}"
            print(error_msg)
            raise Exception(error_msg)
    
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
