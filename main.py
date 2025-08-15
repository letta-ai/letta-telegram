import os
import json
import requests
import telegramify_markdown
from typing import Dict, Any
import modal


image = modal.Image.debian_slim(python_version="3.12").pip_install([
    "fastapi[standard]",
    "requests",
    "pydantic>=2.0",
    "telegramify-markdown",
    "letta_client"
])

app = modal.App("letta-telegram-bot", image=image)

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),  
        modal.Secret.from_name("letta-api")
    ]
)
@modal.fastapi_endpoint(method="POST")
def telegram_webhook(update: dict):
    """
    Webhook that processes messages using Letta SDK streaming
    """
    from letta_client import Letta

    print(f"Received update: {update}")
    
    try:
        # Extract message details from Telegram update
        if "message" in update and "text" in update["message"]:

            message_text = update["message"]["text"]
            chat_id = str(update["message"]["chat"]["id"])
            user_name = update["message"]["from"].get("username", "Unknown")
            send_telegram_typing(chat_id)
            print(f"Received message: {message_text} from {user_name} in chat {chat_id}")

            # Handle commands
            if message_text.startswith('/agent'):
                handle_agent_command(message_text, user_name, chat_id)
                return {"ok": True}
            elif message_text.startswith('/help'):
                handle_help_command(chat_id)
                return {"ok": True}
            
            # Process regular messages with Letta streaming
            print("Loading Letta client")
            letta_api_key = os.environ.get("LETTA_API_KEY")
            letta_api_url = os.environ.get("LETTA_API_URL", "https://api.letta.com")
            agent_id = os.environ.get("LETTA_AGENT_ID")
            
            if not letta_api_key:
                send_telegram_message(chat_id, "❌ Configuration error: Missing LETTA_API_KEY")
                return {"ok": True}
                
            if not agent_id:
                send_telegram_message(chat_id, "❌ Configuration error: Missing LETTA_AGENT_ID")
                return {"ok": True}
            
            # Initialize Letta client
            print("Initializing Letta client")
            client = Letta(token=letta_api_key, base_url=letta_api_url)
            
            # Add context about the source and user
            context_message = f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\nIMPORTANT: Please respond to this message using the send_message tool.\n\n{message_text}"
            print(f"Context message: {context_message}")
            
            # Stream the agent response
            try:
                print("Streaming response")
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
                    
                )
                
                # Process streaming response
                for event in response_stream:
                    print(f"Processing event: {event}")
                    send_telegram_typing(chat_id)
                    # event_as_json = event.model_dump_json(indent=2)
                    # send_telegram_message(chat_id, f"```\n{event_as_json}\n```")

                    print(f"Sent event: {event}")
                    try:
                        if hasattr(event, 'message_type'):
                            message_type = event.message_type
                            
                            if message_type == "assistant_message":
                                content = getattr(event, 'content', '')
                                if content and content.strip():
                                    send_telegram_message(chat_id, content)

                            elif message_type == "reasoning_message":
                                content = "> **Reasoning**\n" + blockquote_message(getattr(event, 'reasoning', ''))
                                send_telegram_message(chat_id, content)
                            
                            elif message_type == "system_alert":
                                alert_message = getattr(event, 'message', '')
                                if alert_message and alert_message.strip():
                                    send_telegram_message(chat_id, f"ℹ️ {alert_message}")
                            
                            elif message_type == "tool_call_message":
                                # {
                                #     "id": "message-ca9f8365-fc5c-4650-8665-e1eb0907d97a",
                                #     "date": "2025-08-15T03:49:02Z",
                                #     "name": null,
                                #     "message_type": "tool_call_message",
                                #     "otid": "ca9f8365-fc5c-4650-8665-e1eb0907d901",
                                #     "sender_id": null,
                                #     "step_id": "step-93fe2195-fe52-4e17-b4e4-8752cc2bbf77",
                                #     "is_err": null,
                                #     "tool_call": {
                                #         "name": "archival_memory_search",
                                #         "arguments": "{\"query\": \"OpenAI\", \"page\": 0, \"start\": 0, \"request_heartbeat\": true}",
                                #         "tool_call_id": "call_vJk5jsQ7FqiFWVVfmXE26Hem"
                                #     }
                                #  }

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
                                        else:
                                            tool_msg = f"🔧 Using tool: {tool_name}"
                                            formatted_args = json.dumps(args_obj, indent=2)
                                            tool_msg += f"\n```json\n{formatted_args}\n```"
                                    except Exception as e:
                                        send_telegram_message(chat_id, f"Experienced an error: {e}")
                                        tool_msg = f"🔧 Using tool: {tool_name}\n```\n{arguments}\n```"
                                    
                                    send_telegram_message(chat_id, tool_msg)
                            
                            # Disabled, no need to show tool return messages
                            # elif message_type == "tool_return_message":
                            #     tool_name = getattr(event, 'name', 'unknown')
                            #     status = getattr(event, 'status', 'unknown')
                                
                            #     if tool_name == "web_search" and status == "success":
                            #         tool_return = getattr(event, 'tool_return', '')
                            #         if tool_return:
                            #             try:
                            #                 return_data = json.loads(tool_return)
                            #                 results = return_data.get("results", {})
                                            
                            #                 for _, result in results.items():
                            #                     if result.get("raw_results", {}).get("success"):
                            #                         search_data = result["raw_results"]["data"]
                            #                         if search_data:
                            #                             first_result = search_data[0]
                            #                             title = first_result.get("title", "")
                            #                             description = first_result.get("description", "")
                            #                             url = first_result.get("url", "")
                                                        
                            #                             response = f"🌤 **{title}**\n\n{description}"
                            #                             if url:
                            #                                 response += f"\n\n[View full forecast]({url})"
                                                        
                            #                             send_telegram_message(chat_id, response)
                            #             except Exception as e:
                            #                 print(f"⚠️  Error processing web_search results: {e}")
                            #                 send_telegram_message(chat_id, f"🔧 {tool_name} completed")
                                
                    except Exception as e:
                        print(f"⚠️  Error processing stream event: {e}")
                        continue
                
            except Exception as e:
                send_telegram_message(chat_id, f"[MODAL ERROR] Error streaming from Letta: {str(e)}")
            
    except Exception as e:
        raise Exception(f"Error processing webhook: {str(e)}")
    
    # Always return OK to Telegram quickly
    return {"ok": True}



def blockquote_message(message: str) -> str:
    """
    Blockquote a message by adding a > to the beginning of each line
    """
    return "\n".join([f"> {line}" for line in message.split("\n")])

def handle_agent_command(message: str, _user_name: str, chat_id: str):
    """
    Handle /agent command to change or view the agent ID
    """
    try:
        # Parse the command: /agent [agent_id]
        parts = message.strip().split()
        
        if len(parts) == 1:
            # Show current agent ID
            current_agent_id = os.environ.get("LETTA_AGENT_ID", "Not set")
            send_telegram_message(chat_id, f"🤖 Current Agent ID: `{current_agent_id}`\n\nUse `/agent <new_id>` to change it.")
            return
        
        if len(parts) != 2:
            send_telegram_message(chat_id, "❌ Usage: `/agent [agent_id]`\n\nExamples:\n• `/agent` - Show current agent ID\n• `/agent abc123` - Set new agent ID")
            return
        
        new_agent_id = parts[1].strip()
        
        # Validate agent ID format (basic validation)
        if not new_agent_id or len(new_agent_id) < 3:
            send_telegram_message(chat_id, "❌ Agent ID must be at least 3 characters long")
            return
        
        # Update the agent ID
        success = update_agent_id(new_agent_id)
        
        if success:
            send_telegram_message(chat_id, f"✅ Agent ID updated to: `{new_agent_id}`\n\nYou can now chat with the new agent!")
        else:
            send_telegram_message(chat_id, "❌ Failed to update agent ID. Please try again or check the logs.")
    
    except Exception as e:
        print(f"Error handling agent command: {str(e)}")
        send_telegram_message(chat_id, "❌ Error processing agent command. Please try again.")

def update_agent_id(new_agent_id: str) -> bool:
    """
    Update the LETTA_AGENT_ID in the Modal secret
    """
    try:
        # Note: This is a simplified approach - in production you'd want to
        # properly retrieve and update the existing secret via Modal's API
        
        # Update the environment variable for the current session
        os.environ["LETTA_AGENT_ID"] = new_agent_id
        
        print(f"✅ Agent ID updated to: {new_agent_id}")
        return True
        
    except Exception as e:
        print(f"Error updating agent ID: {str(e)}")
        return False

def handle_help_command(chat_id: str):
    """
    Handle /help command to show available commands
    """
    help_text = """🤖 **Letta Telegram Bot Commands**

**Available Commands:**
• `/help` - Show this help message
• `/agent` - Show current agent ID
• `/agent <id>` - Change to a different agent ID

**Examples:**
• `/agent` - Shows your current agent ID
• `/agent abc123` - Switches to agent with ID "abc123"

**Note:** Agent ID changes are temporary for this session. For permanent changes, update your Modal secrets.
"""
    send_telegram_message(chat_id, help_text)


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
        
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            error_msg = f"Telegram API error sending typing: {response.status_code} - {response.text}"
            print(error_msg)
            raise Exception(error_msg)
    
    except Exception as e:
        print(f"Error sending typing indicator: {str(e)}")

def convert_to_telegram_markdown(text: str) -> str:
    """
    Convert text to Telegram-compatible MarkdownV2 format using telegramify-markdown
    """
    try:
        # Use telegramify-markdown to handle proper escaping and conversion
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
        
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            error_msg = f"Telegram API error: {response.status_code} - {response.text}"
            print(error_msg)
            raise Exception(error_msg)
    
    except Exception as e:
        print(f"Error sending Telegram message: {str(e)}")

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
        modal.Secret.from_name("telegram-bot"),
        modal.Secret.from_name("letta-api")
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
    # For local development
    print("Letta-Telegram bot is ready to deploy!")