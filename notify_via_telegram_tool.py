import os
import requests
from typing import Optional


def notify_via_telegram(message: str) -> str:
    """
    Send a notification message to the Telegram user.
    
    This tool sends a notification to a Telegram chat using the bot API.
    It requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
    
    Args:
        message (str): The notification message to send to the user
        
    Returns:
        str: Confirmation that the message was sent or error message
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token:
        return "Error: TELEGRAM_BOT_TOKEN environment variable is not set"
    
    if not chat_id:
        return "Error: TELEGRAM_CHAT_ID environment variable is not set"
    
    # Escape MarkdownV2 special characters
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    markdown_text = message
    for char in special_chars:
        markdown_text = markdown_text.replace(char, f'\\{char}')
    
    # Send message via Telegram API
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": markdown_text,
        "parse_mode": "MarkdownV2"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return "Message sent successfully via Telegram"
        else:
            return f"Failed to send Telegram message: {response.status_code} - {response.text}"
    except requests.exceptions.RequestException as e:
        return f"Error sending Telegram message: {str(e)}"