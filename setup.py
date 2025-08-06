"""
Setup script for configuring the Letta-Telegram bot
"""
import requests
import os
from pathlib import Path

def load_env_file():
    """Load .env file if it exists, overriding existing environment variables"""
    env_file = Path(".env")
    if env_file.exists():
        print(f"📁 Loading environment from {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove quotes if present
                    value = value.strip('"\'')
                    os.environ[key] = value
        print("✅ Environment variables loaded from .env")
    else:
        print("⚠️  No .env file found, using system environment variables")

def setup_telegram_webhook(bot_token: str, webhook_url: str, secret_token: str = None):
    """
    Configure Telegram webhook to point to Modal endpoint
    """
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    
    params = {"url": webhook_url}
    if secret_token:
        params["secret_token"] = secret_token
    
    response = requests.post(url, data=params)
    
    if response.status_code == 200:
        result = response.json()
        if result.get("ok"):
            print(f"✅ Webhook configured successfully!")
            print(f"   URL: {webhook_url}")
            if secret_token:
                print(f"   Secret token configured")
        else:
            print(f"❌ Failed to set webhook: {result.get('description')}")
    else:
        print(f"❌ HTTP Error: {response.status_code}")
        try:
            error_result = response.json()
            print(f"   Error details: {error_result.get('description', 'No description')}")
        except:
            print(f"   Response text: {response.text}")

def check_telegram_bot(bot_token: str):
    """
    Verify Telegram bot credentials
    """
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    response = requests.get(url)
    
    if response.status_code == 200:
        result = response.json()
        if result.get("ok"):
            bot_info = result["result"]
            print(f"✅ Bot verified: @{bot_info['username']} ({bot_info['first_name']})")
            return True
        else:
            print(f"❌ Bot verification failed: {result.get('description')}")
    else:
        print(f"❌ HTTP Error: {response.status_code}")
    
    return False

if __name__ == "__main__":
    print("🚀 Letta-Telegram Bot Setup")
    print("=" * 40)
    
    # Load .env file if it exists
    load_env_file()
    
    # Get configuration from environment or user input
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        bot_token = input("Enter your Telegram Bot Token: ").strip()
    
    webhook_url = input("Enter your Modal webhook URL (from modal deploy): ").strip()
    
    secret_token = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret_token:
        secret_token = input("Enter webhook secret token (optional, press enter to skip): ").strip() or None
    
    # Verify bot
    if check_telegram_bot(bot_token):
        # Configure webhook
        setup_telegram_webhook(bot_token, webhook_url, secret_token)
        
        print("\n📋 Next steps:")
        print("1. Make sure your Modal secrets are configured:")
        print("   - telegram-bot: TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET")
        print("   - letta-api: LETTA_API_KEY, LETTA_API_URL, LETTA_AGENT_ID")
        print("2. Deploy with: modal deploy main.py")
        print("3. Test by sending a message to your bot!")
    else:
        print("❌ Please check your bot token and try again.")