#!/usr/bin/env python3
"""
Script to register the notify_via_telegram tool with Letta.
Run this script to make the tool available for all agents.
"""

import os
from typing import Optional
from letta_client import Letta
from pydantic import BaseModel, Field


class TelegramMessageData(BaseModel):
    """Schema for the notify_via_telegram tool arguments."""
    message: str = Field(
        ...,
        description="The notification message to send to the Telegram user"
    )


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
    import os
    import requests
    
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


def register_tool(api_key: Optional[str] = None):
    """
    Register the notify_via_telegram tool with Letta.
    
    Args:
        api_key (str, optional): Letta API key. If not provided, tries to get from LETTA_API_KEY env var.
    
    Returns:
        dict: Registration status information
    """
    # Get API key
    api_key = api_key or os.getenv("LETTA_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "LETTA_API_KEY environment variable not found. Please set it or pass api_key parameter."
        }
    
    # Create client with token
    client = Letta(token=api_key)
    print("✅ Connected to Letta Cloud API")
    
    # Register the tool
    try:
        tool = client.tools.upsert_from_function(
            func=notify_via_telegram,
            args_schema=TelegramMessageData,
            tags=["telegram", "notification", "messaging"]
        )
        print(f"✅ Tool registered successfully!")
        print(f"   Tool ID: {tool.id}")
        print(f"   Tool Name: {tool.name}")
        print(f"   Description: {tool.description}")
        print()
        print("🔧 Next steps:")
        print("1. Make sure TELEGRAM_BOT_TOKEN is set in your environment")
        print("2. TELEGRAM_CHAT_ID will be set automatically when processing messages")
        print("3. Attach this tool to your agents using: /tool attach notify_via_telegram")
        print("4. Or modify main.py to auto-attach it to new agents")
        
        return {
            "status": "success",
            "tool_id": tool.id,
            "tool_name": tool.name
        }
        
    except Exception as e:
        print(f"❌ Failed to register tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


if __name__ == "__main__":
    # Register with cloud API
    result = register_tool()
    
    if result["status"] == "success":
        print(f"\n✅ Registration complete! Tool ID: {result['tool_id']}")
    else:
        print(f"\n❌ Registration failed: {result.get('message', 'Unknown error')}")