import os
import json
import requests
import telegramify_markdown
from typing import Dict, Any
import modal
import time
from functools import wraps

class LettaAPIError(Exception):
    """Custom exception for Letta API errors"""
    def __init__(self, status_code: int, response_text: str):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(f"Letta API error: {status_code} - {response_text}")

def retry_on_500(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Decorator to retry function calls on 500 errors with exponential backoff
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except LettaAPIError as e:
                    last_exception = e
                    
                    # Only retry on 500 errors
                    if e.status_code != 500:
                        raise e
                    
                    # Don't retry on last attempt
                    if attempt == max_retries:
                        print(f"❌ Max retries ({max_retries}) exceeded for 500 error")
                        # Now send the 500 error to client since all retries failed
                        # Extract chat_id from function arguments (assumes it's the third argument)
                        if len(args) >= 3 and isinstance(args[2], str):
                            chat_id = args[2]
                            send_telegram_message(chat_id, f"API Error (500). Server temporarily unavailable after {max_retries} retries.")
                        raise e
                    
                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    print(f"🔄 Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries}) after 500 error")
                    time.sleep(delay)
                    
                except Exception as e:
                    # Don't retry non-LettaAPIError exceptions
                    raise e
            
            # This shouldn't be reached, but just in case
            raise last_exception
        
        return wrapper
    return decorator

image = modal.Image.debian_slim(python_version="3.12").pip_install([
    "fastapi[standard]",
    "requests",
    "pydantic",
    "telegramify-markdown"
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
    Webhook that acknowledges immediately and processes asynchronously
    """
    try:
        # Extract message details from Telegram update
        if "message" in update and "text" in update["message"]:
            message_text = update["message"]["text"]
            chat_id = str(update["message"]["chat"]["id"])
            user_name = update["message"]["from"].get("username", "Unknown")
            
            # Send typing indicator to show bot is processing
            send_telegram_typing(chat_id)
            
            # Spawn async processing in background
            process_message_async.spawn(message_text, user_name, chat_id)
            
    except Exception as e:
        print(f"Error processing webhook: {str(e)}")
    
    # Always return OK to Telegram quickly
    return {"ok": True}


@retry_on_500(max_retries=3, base_delay=2.0, max_delay=30.0)
def process_with_letta_agent_stream(message: str, user_name: str, chat_id: str):
    """
    Stream messages from Letta agent in real-time to Telegram
    """
    try:
        letta_api_url = os.environ.get("LETTA_API_URL", "https://api.letta.com")
        letta_api_key = os.environ.get("LETTA_API_KEY")
        agent_id = os.environ.get("LETTA_AGENT_ID")
        
        print(f"🔍 Debug - Streaming message from {user_name} (chat_id: {chat_id})")
        print(f"🔍 Debug - Message: {message[:100]}...")
        print(f"🔍 Debug - Letta URL: {letta_api_url}")
        print(f"🔍 Debug - Agent ID: {agent_id}")
        print(f"🔍 Debug - API Key present: {'Yes' if letta_api_key else 'No'}")
        
        if not letta_api_key:
            error_msg = "❌ Configuration error: Missing LETTA_API_KEY"
            print(error_msg)
            send_telegram_message(chat_id, error_msg)
            return
            
        if not agent_id:
            error_msg = "❌ Configuration error: Missing LETTA_AGENT_ID"
            print(error_msg)
            send_telegram_message(chat_id, error_msg)
            return
        
        headers = {
            "Authorization": f"Bearer {letta_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
        }
        
        # Add context about the source and user
        context_message = f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\nIMPORTANT: Please respond to this message using the send_message tool.\n\n{message}"
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": context_message
                        }
                    ]
                }
            ]
        }
        
        print(f"🔍 Debug - Making streaming request to: {letta_api_url}/v1/agents/{agent_id}/messages/stream")
        print(f"🔍 Debug - Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(
            f"{letta_api_url}/v1/agents/{agent_id}/messages/stream",
            headers=headers,
            json=payload,
            stream=True,
            timeout=300  # 5 minute timeout for streaming
        )
        
        print(f"🔍 Debug - Response status: {response.status_code}")
        
        if response.status_code == 200:
            # Process streaming response
            current_message = ""
            
            print("🔍 Starting to process streaming response...")
            lines_processed = 0
            
            for line in response.iter_lines(decode_unicode=True):
                lines_processed += 1
                print(f"🔍 Line {lines_processed}: '{line}'")
                
                if not line:
                    print("🔍 Empty line - skipping")
                    continue
                
                print(f"🔍 Line starts with 'data: ': {line.startswith('data: ')}")
                
                # Skip non-data lines but log them
                if not line.startswith('data: '):
                    print(f"🔍 Non-data line: {line}")
                    continue
                
                # Handle end of stream
                if line == 'data: [DONE]':
                    print("📤 Stream completed with [DONE]")
                    break
                
                try:
                    # Parse JSON data
                    json_str = line[6:]  # Remove 'data: ' prefix
                    print(f"🔍 JSON string: '{json_str}'")
                    
                    data = json.loads(json_str)
                    print(f"🔍 Parsed data: {json.dumps(data, indent=2)}")
                    
                    message_type = data.get("message_type")
                    print(f"🔍 Message type: {message_type}")
                    print(f"🔍 All keys: {list(data.keys())}")
                    
                    if message_type == "assistant_message":
                        content = data.get("content", "")
                        if content and content.strip():
                            current_message += content
                            # Send complete message when we have substantial content
                            if len(current_message) > 100 or content.endswith((".", "!", "?", "\n")):
                                print(f"📤 Sending assistant message: {current_message[:100]}...")
                                send_telegram_message(chat_id, current_message.strip())
                                current_message = ""
                    
                    elif message_type == "system_alert":
                        alert_message = data.get("message", "")
                        if alert_message and alert_message.strip():
                            print(f"📤 Sending system alert: {alert_message[:100]}...")
                            send_telegram_message(chat_id, f"ℹ️ {alert_message}")
                    
                    elif message_type == "reasoning_message":
                        # Optional: send reasoning messages for debugging
                        reasoning = data.get("reasoning", "")
                        if reasoning and reasoning.strip():
                            print(f"💭 Reasoning: {reasoning[:100]}...")
                            # Uncomment to send reasoning to user:
                            # send_telegram_message(chat_id, f"💭 {reasoning}")
                    
                    elif message_type == "tool_call":
                        tool_name = data.get("tool_name", "unknown")
                        print(f"🔧 Tool call: {tool_name}")
                        # Optional: notify user of tool usage
                        # send_telegram_message(chat_id, f"🔧 Using tool: {tool_name}")
                    
                    elif message_type == "tool_call_message":
                        tool_call = data.get("tool_call", {})
                        tool_name = tool_call.get("name", "unknown")
                        arguments = tool_call.get("arguments", "")
                        print(f"🔧 Tool call message: {tool_name}")
                        
                        # Send tool name and arguments to user
                        tool_msg = f"🔧 Using tool: {tool_name}"
                        if arguments and arguments.strip():
                            try:
                                # Try to format arguments as JSON for readability
                                args_obj = json.loads(arguments) if isinstance(arguments, str) else arguments
                                formatted_args = json.dumps(args_obj, indent=2)
                                tool_msg += f"\n```json\n{formatted_args}\n```"
                            except Exception:
                                # Fallback to raw arguments
                                tool_msg += f"\n```\n{arguments}\n```"
                        send_telegram_message(chat_id, tool_msg)
                    
                    elif message_type == "tool_return_message":
                        tool_name = data.get("name", "unknown")
                        status = data.get("status", "unknown")
                        print(f"🔧 Tool return: {tool_name} - {status}")
                        
                        # For web_search tool, extract and send results to user
                        if tool_name == "web_search" and status == "success":
                            tool_return = data.get("tool_return", "")
                            if tool_return:
                                try:
                                    return_data = json.loads(tool_return)
                                    results = return_data.get("results", {})
                                    
                                    # Extract search results and send to user
                                    for query, result in results.items():
                                        if result.get("raw_results", {}).get("success"):
                                            search_data = result["raw_results"]["data"]
                                            if search_data:
                                                # Get first result
                                                first_result = search_data[0]
                                                title = first_result.get("title", "")
                                                description = first_result.get("description", "")
                                                url = first_result.get("url", "")
                                                
                                                # Format response
                                                response = f"🌤 **{title}**\n\n{description}"
                                                if url:
                                                    response += f"\n\n[View full forecast]({url})"
                                                
                                                send_telegram_message(chat_id, response)
                                except Exception as e:
                                    print(f"⚠️  Error processing web_search results: {e}")
                                    # Send raw tool return as fallback
                                    send_telegram_message(chat_id, f"🔧 {tool_name} completed")
                        else:
                            # For other tools, just log completion
                            print(f"🔧 Tool {tool_name} completed with status {status}")
                    
                    elif message_type == "stop_reason":
                        stop_reason = data.get("stop_reason", "unknown")
                        print(f"🛑 Stop reason: {stop_reason}")
                        # End of stream, no action needed
                    
                    elif message_type == "usage_statistics":
                        print(f"📊 Usage stats: {data}")
                        # Optional: send usage info to user
                    
                    else:
                        print(f"🔍 Unknown message type '{message_type}' - full data: {json.dumps(data, indent=2)}")
                        # For debugging, let's try to extract any content
                        possible_content = (
                            data.get("content") or 
                            data.get("text") or 
                            data.get("message") or
                            data.get("assistant_message") or
                            data.get("user_message")
                        )
                        if possible_content and str(possible_content).strip():
                            print(f"📤 Sending unknown type content: {str(possible_content)[:100]}...")
                            send_telegram_message(chat_id, f"[{message_type or 'UNKNOWN'}] {possible_content}")
                    
                except json.JSONDecodeError as e:
                    print(f"⚠️  Failed to parse JSON: '{line}' - Error: {e}")
                    # For debugging, send the raw line content
                    if len(line) > 6:
                        raw_content = line[6:]
                        print(f"📤 Sending raw content: {raw_content[:100]}...")
                        send_telegram_message(chat_id, f"[RAW] {raw_content}")
                    continue
                except Exception as e:
                    print(f"⚠️  Error processing stream data: {e}")
                    continue
            
            print(f"🔍 Stream processing complete. Total lines: {lines_processed}")
            print(f"🔍 Current message buffer: '{current_message}'")
            
            # Send any remaining message content
            if current_message.strip():
                print(f"📤 Sending final message: {current_message[:100]}...")
                send_telegram_message(chat_id, current_message.strip())
        
        else:
            error_msg = f"❌ Letta API error: {response.status_code} - {response.text}"
            print(error_msg)
            # Only send non-500 errors immediately to client
            # 500 errors will be handled by the retry decorator
            if response.status_code != 500:
                send_telegram_message(chat_id, f"API Error ({response.status_code}). Check logs for details.")
            raise LettaAPIError(response.status_code, response.text)
    
    except requests.exceptions.Timeout:
        error_msg = "❌ Timeout calling Letta API"
        print(error_msg)
        send_telegram_message(chat_id, "Request timed out. Please try again.")
        raise
    except requests.exceptions.ConnectionError:
        error_msg = "❌ Connection error calling Letta API"
        print(error_msg)
        send_telegram_message(chat_id, "Connection failed. Please try again.")
        raise
    except Exception as e:
        error_msg = f"❌ Unexpected error calling Letta API: {str(e)}"
        print(error_msg)
        send_telegram_message(chat_id, "Unexpected error occurred. Check logs for details.")
        raise


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),
        modal.Secret.from_name("letta-api")
    ],
    timeout=300  # 5 minute timeout for long responses
)
def process_message_async(message: str, user_name: str, chat_id: str):
    """
    Process message with Letta agent using streaming to avoid webhook timeouts
    """
    print(f"🔄 Processing message with streaming for {user_name}")
    
    # Process message with streaming Letta agent
    try:
        process_with_letta_agent_stream(message, user_name, chat_id)
    except LettaAPIError as e:
        print(f"⚠️  Letta API Error in streaming processing: {str(e)}")
        # Only send non-500 errors immediately to client
        # 500 errors are already handled by the retry decorator
        if e.status_code != 500:
            send_telegram_message(chat_id, f"API Error: {e.status_code}. Please try again or check configuration.")
        # Re-raise to let the system know this is a critical error
        raise
    except Exception as e:
        print(f"⚠️  Error in streaming processing: {str(e)}")
        send_telegram_message(chat_id, "Sorry, I couldn't generate a response right now.")

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