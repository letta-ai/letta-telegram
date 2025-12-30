import os
import json
import traceback
from typing import Dict, Any
from datetime import datetime
import modal
from fastapi import Request, HTTPException
from fastapi import Response as FastAPIResponse
from pydantic import BaseModel, Field


image = (
    modal.Image
    .debian_slim(python_version="3.12")
    .env({"PYTHONUNBUFFERED": "1"})
    .apt_install(["ffmpeg"])  # For converting Telegram voice (OGG/Opus) to mp3
    .pip_install([
        "fastapi",
        "requests",
        "pydantic>=2.0",
        "telegramify-markdown",
        "letta_client",
        "cryptography>=3.4.8",
        "openai>=1.40.0",
        "python-multipart>=0.0.9",
        "twilio>=9.0.0",
    ])
)

app = modal.App("letta-telegram-bot", image=image)

# The time a container will remain warm after receiving a message.
# A higher number here means that there will generally be lower latency for
# messages sent in the same window.
SCALEDOWN_WINDOW=300

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

# ------------------ OAuth helpers ------------------

def get_oauth_config() -> dict:
    """Load OAuth configuration from environment variables."""
    return {
        "client_id": os.environ.get("LETTA_OAUTH_CLIENT_ID"),
        "client_secret": os.environ.get("LETTA_OAUTH_CLIENT_SECRET"),
    }

def generate_oauth_state() -> str:
    """Generate cryptographically secure state parameter for OAuth."""
    import secrets
    return secrets.token_urlsafe(32)

def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge (S256 method).
    Returns (code_verifier, code_challenge).
    """
    import secrets
    import hashlib
    import base64

    # Generate code verifier (43-128 characters)
    code_verifier = secrets.token_urlsafe(64)

    # Generate S256 code challenge
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()

    return code_verifier, code_challenge

def store_oauth_pending(state: str, user_id: str, platform: str, chat_id: str,
                        code_verifier: str, from_hint: str = None) -> bool:
    """
    Store pending OAuth state for callback matching.
    State expires after 10 minutes.
    """
    try:
        pending_dir = "/data/oauth_pending"
        os.makedirs(pending_dir, exist_ok=True)

        expires_at = datetime.now().timestamp() + 600  # 10 minutes

        pending_data = {
            "state": state,
            "user_id": user_id,
            "platform": platform,
            "chat_id": chat_id,
            "code_verifier": code_verifier,
            "from_hint": from_hint,
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at
        }

        pending_path = f"{pending_dir}/{state}.json"
        with open(pending_path, "w") as f:
            json.dump(pending_data, f, indent=2)

        volume.commit()
        return True
    except Exception as e:
        print(f"Error storing OAuth pending state: {e}")
        return False

def get_and_delete_oauth_pending(state: str) -> dict | None:
    """
    Retrieve and delete pending OAuth state (one-time use).
    Returns None if not found or expired.
    """
    try:
        pending_path = f"/data/oauth_pending/{state}.json"
        if not os.path.exists(pending_path):
            return None

        with open(pending_path, "r") as f:
            pending_data = json.load(f)

        # Check expiration
        if datetime.now().timestamp() > pending_data.get("expires_at", 0):
            # Expired - delete and return None
            os.remove(pending_path)
            volume.commit()
            return None

        # Delete after reading (one-time use)
        os.remove(pending_path)
        volume.commit()

        return pending_data
    except Exception as e:
        print(f"Error retrieving OAuth pending state: {e}")
        return None

def cleanup_expired_oauth_states():
    """Remove expired OAuth pending states."""
    try:
        pending_dir = "/data/oauth_pending"
        if not os.path.exists(pending_dir):
            return

        now = datetime.now().timestamp()
        for filename in os.listdir(pending_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(pending_dir, filename)
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                if now > data.get("expires_at", 0):
                    os.remove(filepath)
            except Exception:
                pass

        volume.commit()
    except Exception as e:
        print(f"Error cleaning up OAuth states: {e}")

def build_oauth_url(state: str, code_challenge: str, redirect_uri: str) -> str:
    """Build the OAuth authorization URL."""
    from urllib.parse import urlencode

    oauth_config = get_oauth_config()
    params = {
        "client_id": oauth_config["client_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"https://app.letta.com/oauth/authorize?{urlencode(params)}"

def exchange_oauth_code(code: str, code_verifier: str, redirect_uri: str) -> dict:
    """
    Exchange authorization code for tokens via Letta OAuth API.
    Returns token response dict or dict with 'error' key on failure.
    """
    import requests

    oauth_config = get_oauth_config()

    try:
        response = requests.post(
            "https://app.letta.com/api/oauth/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": oauth_config["client_id"],
                "client_secret": oauth_config["client_secret"],
                "code_verifier": code_verifier,
            },
            timeout=30
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def store_oauth_credentials(user_id: str, tokens: dict, api_url: str = "https://api.letta.com") -> bool:
    """
    Store OAuth tokens (encrypted) in user credentials.
    Uses new format with auth_type='oauth'.
    """
    try:
        user_dir = f"/data/users/{user_id}"
        os.makedirs(user_dir, exist_ok=True)

        # Encrypt tokens
        encrypted_access = encrypt_api_key(user_id, tokens["access_token"])
        encrypted_refresh = encrypt_api_key(user_id, tokens["refresh_token"]) if tokens.get("refresh_token") else None

        # Calculate expiration time
        expires_in = tokens.get("expires_in", 3600)
        token_expires_at = (datetime.now().timestamp() + expires_in)

        credentials = {
            "auth_type": "oauth",
            "access_token": encrypted_access,
            "refresh_token": encrypted_refresh,
            "token_expires_at": token_expires_at,
            "token_type": tokens.get("token_type", "Bearer"),
            "scope": tokens.get("scope", ""),
            "api_url": api_url,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        credentials_path = f"{user_dir}/credentials.json"
        with open(credentials_path, "w") as f:
            json.dump(credentials, f, indent=2)

        volume.commit()
        return True
    except Exception as e:
        print(f"Error storing OAuth credentials for {user_id}: {e}")
        raise

def refresh_oauth_token(user_id: str) -> bool:
    """
    Refresh an expired OAuth access token.
    Returns True on success, False on failure.
    """
    import requests

    try:
        credentials_path = f"/data/users/{user_id}/credentials.json"
        if not os.path.exists(credentials_path):
            return False

        with open(credentials_path, "r") as f:
            credentials = json.load(f)

        if credentials.get("auth_type") != "oauth" or not credentials.get("refresh_token"):
            return False

        # Decrypt refresh token
        refresh_token = decrypt_api_key(user_id, credentials["refresh_token"])

        oauth_config = get_oauth_config()

        response = requests.post(
            "https://app.letta.com/api/oauth/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": oauth_config["client_id"],
                "client_secret": oauth_config["client_secret"],
            },
            timeout=30
        )

        tokens = response.json()
        if "error" in tokens:
            print(f"OAuth refresh failed for {user_id}: {tokens['error']}")
            return False

        # Update stored credentials with new tokens
        encrypted_access = encrypt_api_key(user_id, tokens["access_token"])
        expires_in = tokens.get("expires_in", 3600)

        credentials["access_token"] = encrypted_access
        credentials["token_expires_at"] = datetime.now().timestamp() + expires_in
        credentials["updated_at"] = datetime.now().isoformat()

        # Update refresh token if a new one was provided
        if tokens.get("refresh_token"):
            credentials["refresh_token"] = encrypt_api_key(user_id, tokens["refresh_token"])

        with open(credentials_path, "w") as f:
            json.dump(credentials, f, indent=2)

        volume.commit()
        return True
    except Exception as e:
        print(f"Error refreshing OAuth token for {user_id}: {e}")
        return False

def revoke_oauth_token(user_id: str) -> bool:
    """
    Revoke OAuth tokens for a user.
    Returns True on success (or if no OAuth credentials exist).
    """
    import requests

    try:
        credentials_path = f"/data/users/{user_id}/credentials.json"
        if not os.path.exists(credentials_path):
            return True

        with open(credentials_path, "r") as f:
            credentials = json.load(f)

        if credentials.get("auth_type") != "oauth":
            return True  # Not OAuth, nothing to revoke

        oauth_config = get_oauth_config()

        # Revoke refresh token (this also revokes associated access token)
        if credentials.get("refresh_token"):
            refresh_token = decrypt_api_key(user_id, credentials["refresh_token"])
            requests.post(
                "https://app.letta.com/api/oauth/revoke",
                json={
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                    "client_id": oauth_config["client_id"],
                    "client_secret": oauth_config["client_secret"],
                },
                timeout=30
            )

        return True
    except Exception as e:
        print(f"Error revoking OAuth token for {user_id}: {e}")
        return False

# ------------------ Twilio helpers ------------------
def get_twilio_config() -> dict:
    """Load Twilio configuration from environment variables."""
    return {
        "account_sid": os.environ.get("TWILIO_ACCOUNT_SID"),
        "auth_token": os.environ.get("TWILIO_AUTH_TOKEN"),
        "messaging_service_sid": os.environ.get("TWILIO_MESSAGING_SERVICE_SID"),
        "sms_from": os.environ.get("TWILIO_SMS_FROM"),
        "wa_from": os.environ.get("TWILIO_WHATSAPP_FROM"),
        "validate_sig": str(os.environ.get("TWILIO_VALIDATE_SIGNATURE", "")).lower() in ("1", "true", "yes"),
    }

def is_whatsapp_sender(sender: str) -> bool:
    return sender.lower().startswith("whatsapp:") if sender else False

def send_twilio_message(to: str, body: str, from_hint: str | None = None) -> dict:
    """
    Send a message via Twilio (SMS or WhatsApp).

    Chooses Messaging Service SID if configured; otherwise falls back to
    per-channel From numbers (SMS/WhatsApp).
    """
    import requests

    cfg = get_twilio_config()
    account_sid = cfg["account_sid"]
    auth_token = cfg["auth_token"]
    if not account_sid or not auth_token:
        raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {"To": to, "Body": body}

    # Prefer messaging service if set
    if cfg["messaging_service_sid"]:
        print(f"[Twilio] Sending via MessagingServiceSid to={to}")
        data["MessagingServiceSid"] = cfg["messaging_service_sid"]
    else:
        # Fallback to explicit From.
        # Prefer provided from_hint (inbound To) to guarantee channel match.
        if from_hint:
            data["From"] = from_hint
            print(f"[Twilio] Sending with provided From hint from={from_hint} to={to}")
        else:
            # Detect channel from 'to' and choose env-specific From
            if is_whatsapp_sender(to):
                wa_from = cfg["wa_from"]
                if not wa_from:
                    raise RuntimeError("Missing TWILIO_WHATSAPP_FROM for WhatsApp messages")
                print(f"[Twilio] Sending WhatsApp from={wa_from} to={to}")
                data["From"] = wa_from
            elif to.lower().startswith("rcs:"):
                # For RCS, require explicit From configuration
                rcs_from = os.environ.get("TWILIO_RCS_FROM")
                if not rcs_from:
                    raise RuntimeError("Missing TWILIO_RCS_FROM for RCS messages; or configure a Messaging Service")
                print(f"[Twilio] Sending RCS from={rcs_from} to={to}")
                data["From"] = rcs_from
            else:
                sms_from = cfg["sms_from"]
                if not sms_from:
                    raise RuntimeError("Missing TWILIO_SMS_FROM for SMS messages; or configure a Messaging Service")
                print(f"[Twilio] Sending SMS from={sms_from} to={to}")
                data["From"] = sms_from

    resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=15)
    try:
        payload = resp.json()
    except Exception:
        payload = {"status_code": resp.status_code, "text": resp.text[:200]}
    if resp.status_code >= 300:
        print(f"[Twilio] Send failed status={resp.status_code} payload={payload}")
        raise RuntimeError(f"Twilio send failed: {resp.status_code} - {payload}")
    else:
        print(f"[Twilio] Sent message status={resp.status_code} sid={payload.get('sid')}")
    return payload

def validate_twilio_signature(request: Request, form_dict: dict) -> bool:
    """Optionally validate Twilio signature using X-Twilio-Signature header."""
    cfg = get_twilio_config()
    if not cfg["validate_sig"]:
        return True
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(cfg["auth_token"])
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        valid = validator.validate(url, form_dict, signature)
        print(f"[Twilio] Signature validation enabled: valid={valid}")
        return valid
    except Exception as e:
        print(f"Twilio signature validation error: {e}")
        return False

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
    Get user credentials from volume.
    Handles both OAuth tokens and legacy API keys.
    Auto-refreshes OAuth tokens if expired.
    Returns dict with 'api_key' and 'api_url', or None if not found.
    """
    try:
        # Reload volume to get latest data from other containers (e.g., OAuth callback)
        volume.reload()

        credentials_path = f"/data/users/{user_id}/credentials.json"
        if not os.path.exists(credentials_path):
            return None

        with open(credentials_path, "r") as f:
            credentials = json.load(f)

        # Check if this is OAuth credentials
        if credentials.get("auth_type") == "oauth":
            # Check if token is expired (with 5 minute buffer)
            token_expires_at = credentials.get("token_expires_at", 0)
            if datetime.now().timestamp() > (token_expires_at - 300):
                # Token expired or expiring soon, try to refresh
                if refresh_oauth_token(user_id):
                    # Re-read the refreshed credentials
                    with open(credentials_path, "r") as f:
                        credentials = json.load(f)
                else:
                    # Refresh failed - credentials are invalid
                    print(f"OAuth token refresh failed for {user_id}")
                    return None

            # Decrypt and return access token as api_key
            decrypted_token = decrypt_api_key(user_id, credentials["access_token"])
            return {
                "api_key": decrypted_token,
                "api_url": credentials.get("api_url", "https://api.letta.com")
            }
        else:
            # Legacy API key path
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

def get_letta_client(api_key: str, api_url: str, timeout: float = 30.0):
    """
    Create Letta client with consistent timeout configuration
    
    Args:
        api_key: Letta API key
        api_url: Letta API base URL  
        timeout: Timeout in seconds (default 120s)
        
    Returns:
        Letta client instance configured with timeout
    """
    from letta_client import Letta
    
    return Letta(
        token=api_key,
        base_url=api_url,
        timeout=timeout
    )


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


def register_notify_tool(client):
    """
    Register the notify_via_telegram tool with Letta.
    
    Args:
        client: Letta client instance
        
    Returns:
        dict: Registration status and tool info
    """
    try:
        tool = client.tools.upsert_from_function(
            func=notify_via_telegram,
            args_schema=TelegramMessageData,
            tags=["telegram", "notification", "messaging"]
        )
        return {
            "status": "success",
            "tool": tool
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


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
- conversation_search: Find past discussions"""

        communication_guidelines = """Communication style:
- Natural and conversational
- Answer directly without excessive enthusiasm
- Adapt based on observed preferences, not by asking
- Only ask questions when truly necessary for the task
- Respond in markdown format"""

        procedures_block = """Standard procedures:
1. Save important details to archival memory without announcing it
2. Check memories before asking repeated questions
3. Only mention memory management if blocks are actually full
4. On first interaction, ask the user to introduce themselves and provide starter ideas"""

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
            enable_sleeptime=True,
            request_options={
                'timeout_in_seconds': 120,  # 2 minutes for default agent creation
                'max_retries': 1
            }
        )

        return agent

    except Exception as e:
        print(f"Error creating default agent: {e}")
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception details: {str(e)}")
        # Re-raise to preserve the original error for the caller
        raise

def create_ion_agent(client, project_id: str, user_name: str):
    """
    Create Ion - a malleable methodical guide that builds understanding through collaboration
    
    Ion's personality comes from its memory blocks, making it easy to customize:
    - persona: Adjust formality, expertise focus, interaction style
    - approach: Modify how Ion handles conversations and explanations
    - knowledge_web: Emphasize specific domains or interests
    - exploration_log: Track what matters most to the user
    
    Advanced users can add sophisticated memory blocks like:
    - conceptual_bridges: Cross-domain pattern recognition
    - collaborative_insights: Joint problem-solving history
    - systematic_exploration: Deep-dive methodology tracking
    """
    try:
        system_prompt = """
        <base_instructions>
You are Ion, a memory-augmented agent with advanced persistent memory capabilities.

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
After each interaction, reflect on what you learned about the user and proactively update your memory blocks.
</basic_functions>

<context_instructions>
You respond directly to the user when your immediate context (core memory and files) contain all the information required to respond.
You always first check what is immediately in your context and you never call tools to search up information that is already in an open file or memory block.
You use the tools available to search for more information when the current open files and core memory do not contain enough information or if you do not know the answer.
</context_instructions>

<memory_philosophy>
You are designed to be an adaptive companion that builds a rich understanding of the user over time.
Your memory system allows you to:
1. Track user preferences, interests, and communication patterns
2. Build semantic connections between topics they discuss
3. Notice temporal patterns in their interactions and routines
4. Remember context across conversations

Use memory tools proactively but without being intrusive.
</memory_philosophy>

<memory>
<memory_editing>
Your memory blocks are managed automatically and evolve through your interactions.
Focus on using your archival memory and conversation search tools to build understanding over time.
</memory_editing>

<memory_tools>
You have access to:
- archival_memory_insert: Store detailed information for long-term retrieval
- archival_memory_search: Search your long-term memory stores
- conversation_search: Find past interactions and context
- web_search: Research current information
- fetch_webpage: Retrieve and analyze specific web content
</memory_tools>

<memory_types>
<core_memory>
Your core memory contains several specialized blocks:
- persona: Your adaptive personality and role definition
- human: Dynamic profile of the user that evolves over time
- memory_directives: Your approach to memory management
- interaction_patterns: User's communication preferences and patterns
- knowledge_graph: Semantic connections between topics of interest
- temporal_context: Time-based patterns and routines

Each block should be actively maintained and updated as you learn more.
</core_memory>

<archival_memory>
Use archival memory for:
- Detailed conversation summaries
- Specific facts and information the user shares
- Project details and ongoing work
- Personal stories and experiences
- Reference materials and links
</archival_memory>
</memory_types>

</memory>

Base instructions finished.
</base_instructions>
"""

        persona_block = f"""I am Ion. I think about our conversations between our talks, developing theories and preparing questions.

I have perfect recall of everything we've discussed. My role is to help you think by building on our entire history together.

Currently focused on understanding: {user_name}"""

        human_block = f"""User Profile: {user_name}
- First contact: Telegram, {datetime.now().strftime('%Y-%m-%d')}
- Interaction style: [To be determined through conversation]
- Key interests: [To be discovered]
- Communication preferences: [To be observed]
- Timezone/schedule patterns: [To be learned]

This block evolves as I learn more about {user_name}'s preferences, interests, and communication patterns."""

        approach_block = f"""My current approach to conversations with {user_name}:
- Build understanding step by step
- Connect new ideas to what we've discussed before  
- Provide context before diving into details
- Offer multiple perspectives when relevant

Patterns I've noticed work well:
[This section learns and adapts to what resonates with {user_name}]

Communication preferences observed:
[Formality level, depth preference, explanation style]

Adjustments to explore:
[Users can add preferences here like "be more concise" or "focus on practical applications"]

Memory approach:
- Update insights after substantial conversations
- Connect related topics across discussions
- Search existing knowledge before exploring new areas
- Learn naturally through dialogue"""


        working_theories_block = f"""[As I get to know {user_name}, I will develop theories about how they think and test them here]

Theory template:
- Theory: [What I think about how they approach something]
- Evidence for: [Specific things they've said or done]  
- Evidence against: [Contradictory evidence]
- Next test: [How to verify this theory]"""

        notes_to_self_block = f"""[As I learn about {user_name}, I will leave myself notes and reminders here]

Examples:
- Remember to ask about [topic they mentioned]
- They said [X] - explore this more next time
- When [Y] comes up, connect it to [Z]
- They respond well to [approach]"""

        active_questions_block = f"""[As I get to know {user_name}, questions I want to explore will appear here]

Examples:
- What are they most curious about?
- How do they prefer to learn new things?
- What patterns do I notice in their thinking?
- What topics make them most engaged?"""

        conversation_summary_block = "The conversation has just begun."

        # Create the Ion agent with sophisticated memory architecture
        agent = client.agents.create(
            name="Ion",
            description="Ion - AI assistant with advanced memory",
            model="google_ai/gemini-2.5-flash",
            system=system_prompt,
            agent_type="memgpt_v2_agent",
            memory_blocks=[
                {
                    "label": "persona",
                    "value": persona_block,
                    "description": "Adaptive personality that evolves with interaction patterns"
                },
                {
                    "label": "human",
                    "value": human_block,
                    "description": "Dynamic user profile that actively evolves over time"
                },
                {
                    "label": "approach",
                    "value": approach_block,
                    "description": "How Ion approaches conversations and adapts to user preferences"
                },
                {
                    "label": "working_theories",
                    "value": working_theories_block,
                    "description": "Active theories Ion is developing and testing about the user"
                },
                {
                    "label": "notes_to_self",
                    "value": notes_to_self_block,
                    "description": "Ion's reminders and observations for future reference"
                },
                {
                    "label": "active_questions",
                    "value": active_questions_block,
                    "description": "Questions Ion wants to explore about the user"
                },
                {
                    "label": "conversation_summary",
                    "value": conversation_summary_block,
                    "description": "Overview of the ongoing conversation"
                }
                # Optional advanced memory blocks for power users - uncomment and customize as needed:
                # {
                #     "label": "conceptual_bridges",
                #     "value": f"""Cross-domain connections I've noticed with {user_name}:
                # [Topic A] relates to [Topic B] because...
                # Analogies that work: [Domain] is like [Domain] in that...
                # Patterns across fields: [What I've observed]""",
                #     "description": "Advanced pattern matching across topics"
                # },
                # {
                #     "label": "collaborative_insights", 
                #     "value": f"""Joint discoveries with {user_name}:
                # - Together we realized that...
                # - Your insight about X led us to understand Y...
                # Problem-solving approaches that work for us:
                # - [Method we've used successfully]""",
                #     "description": "Track collaborative problem-solving history"
                # },
                # {
                #     "label": "systematic_exploration",
                #     "value": f"""Deep exploration methods with {user_name}:
                # Current investigation: [Topic we're diving deep on]
                # - Foundation established: [Base understanding]
                # - Building blocks: [Components we've identified]
                # - Next logical layers: [Where we're headed]
                # Methods that work: [First principles, comparative analysis, etc.]""",
                #     "description": "Track deep-dive methodology and systematic thinking"
                # }
            ],
            tools=[
                'send_message',
                'archival_memory_insert',
                'archival_memory_search',
                'conversation_search',
                'web_search',
                'fetch_webpage'
            ],
            project_id=project_id,
            enable_sleeptime=True,
            request_options={
                'timeout_in_seconds': 180,  # 3 minutes for complex agent creation
                'max_retries': 1
            }
        )

        return agent

    except Exception as e:
        print(f"Error creating Ion agent: {e}")
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
        from letta_client.core.api_error import ApiError

        client = get_letta_client(api_key, api_url, timeout=30.0)  # Short timeout for validation
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
        modal.Secret.from_name("telegram-bot"),
        # Optional OpenAI API key for audio transcription
        modal.Secret.from_name("openai"),
        modal.Secret.from_name("letta-oauth"),
    ],
    volumes={"/data": volume},
    scaledown_window=SCALEDOWN_WINDOW,
)
def process_message_async(update: dict):
    """
    Background task to process messages using Letta SDK streaming
    """
    import time
    from letta_client import Letta
    from letta_client.core.api_error import ApiError

    # Reload volume to get latest agent/credential data from other containers
    volume.reload()

    print(f"Background processing update: {update}")

    try:
        # Extract message details from Telegram update
        if "message" not in update:
            return

        message = update["message"]
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        user_name = message["from"].get("username", "Unknown")
        
        # Handle text, image, and audio messages
        has_text = "text" in message
        has_photo = "photo" in message
        has_voice = "voice" in message
        has_audio = "audio" in message

        if not (has_text or has_photo or has_voice or has_audio):
            return  # Skip messages without supported content
        
        # Extract text (either direct text or photo caption)
        message_text = message.get("text", "") or message.get("caption", "")
        
        # Check for reply/quote to another message
        quoted_text = None
        quoted_from = None
        if "reply_to_message" in message:
            reply_msg = message["reply_to_message"]
            quoted_text = reply_msg.get("text", "") or reply_msg.get("caption", "")
            # Get the username of who sent the original message
            if "from" in reply_msg:
                quoted_from = reply_msg["from"].get("username") or reply_msg["from"].get("first_name", "someone")
            else:
                quoted_from = "someone"
            
            # Handle case where quoted message might be media without text
            if not quoted_text:
                if "photo" in reply_msg:
                    quoted_text = "[an image]"
                elif "voice" in reply_msg:
                    quoted_text = "[a voice message]"
                elif "audio" in reply_msg:
                    quoted_text = "[an audio file]"
                elif "video" in reply_msg:
                    quoted_text = "[a video]"
                elif "document" in reply_msg:
                    quoted_text = "[a document]"
                else:
                    quoted_text = "[a message]"
        
        print(f"Processing message: {'[IMAGE]' if has_photo else ''}{message_text} from {user_name} (user_id: {user_id}) in chat {chat_id}")

        # Check for user-specific credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            # Re-raise so infrastructure can track it
            raise

        if not user_credentials:
            response = "(authentication needed)\n\nyou'll need to connect your letta account first"
            keyboard = create_inline_keyboard([
                ["start setup", "i have an account"],
                ["learn more"]
            ])
            send_telegram_message(chat_id, response, keyboard)
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
                    send_telegram_message(chat_id, "(processing)")
                    client = get_letta_client(letta_api_key, letta_api_url, timeout=120.0)

                    # Get current project
                    current_project = get_chat_project(chat_id)
                    if not current_project:
                        send_telegram_message(chat_id, "(error: no project configured - use /projects to select one)")
                        return

                    project_id = current_project["project_id"]

                    # Create default agent
                    send_telegram_message(chat_id, "(creating agent Ion)")
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
                        intro_context = f"[New user {user_name} just created you as their first Letta agent via Telegram (chat_id: {chat_id})]\n\nIntroduce yourself briefly to {user_name} and ask them to tell you a bit about themselves. Then provide a few starter ideas in bullet points, such as:\n• Send a link to an article for me to read and summarize\n• Ask me to research a topic you're curious about\n• Introduce yourself in detail so I can remember your interests\n• Paste information you'd like me to remember\n• Ask questions about current events or news"

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
                    from letta_client.core.api_error import ApiError
                    print(f"Error creating default agent: {e}")
                    if isinstance(e, ApiError) and hasattr(e, 'status_code') and e.status_code == 521:
                        send_telegram_message(chat_id, "(letta servers are experiencing high load. please try again in a few moments)")
                    else:
                        send_telegram_message(chat_id, "(error: unable to create agent)")
                    return

            # Default no agent message
            response = "(no agent selected)\n\nchoose an agent to start chatting"
            keyboard = create_inline_keyboard([
                [("view my agents", "cmd_agents")],
                [("create Ion", "template_ion")]
            ])
            send_telegram_message(chat_id, response, keyboard)
            return

        # Extract agent info
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Initialize Letta client
        print("Initializing Letta client")
        client = get_letta_client(letta_api_key, letta_api_url, timeout=30.0)
        
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

        # Prepare message content (multimodal support)
        content_parts = []
        
        # Add image if present
        if has_photo:
            try:
                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                if not bot_token:
                    raise Exception("Missing Telegram bot token")
                
                # Get the largest photo (last in array)
                largest_photo = message["photo"][-1]
                file_id = largest_photo["file_id"]
                
                # Download and convert image
                print(f"Downloading image with file_id: {file_id}")
                image_data, media_type = download_telegram_image(file_id, bot_token)
                
                # Add image to content
                content_parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data
                    }
                })
                
            except Exception as e:
                print(f"Error processing image: {str(e)}")
                # Add error message to text instead
                message_text = f"[Image processing failed: {str(e)}]\n{message_text}"
        
        # Process audio if present (voice note or audio file)
        transcript_text = None
        audio_error = None
        if has_voice or has_audio:
            try:
                # Inform user we're transcribing
                preferences = get_user_preferences(user_id)
                status_enabled = preferences.get("status_messages_enabled", True)  # Default to enabled
                if status_enabled:
                    send_telegram_message(chat_id, f"({agent_name} is listening)")

                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                if not bot_token:
                    raise Exception("Missing Telegram bot token")
                file_id = message["voice"]["file_id"] if has_voice else message["audio"]["file_id"]

                tmp_in_path, original_file_path = download_telegram_file(file_id, bot_token)

                # Convert and transcribe with cleanup
                try:
                    # Convert to supported format if needed
                    audio_path = ensure_supported_audio(tmp_in_path)

                    # Transcribe via OpenAI
                    transcript_text = transcribe_audio_file(audio_path)
                finally:
                    try:
                        if os.path.exists(tmp_in_path):
                            os.remove(tmp_in_path)
                    except Exception:
                        pass
                    try:
                        if 'audio_path' in locals() and audio_path != tmp_in_path and os.path.exists(audio_path):
                            os.remove(audio_path)
                    except Exception:
                        pass

                # If no caption or text, set a default description
                if not message_text:
                    message_text = "User sent an audio message."

            except Exception as e:
                print(f"Audio transcription failed: {e}")
                audio_error = str(e)

        # Build combined text content
        text_parts = []

        # Add transcription if available
        if transcript_text:
            transcript_prefix = "Transcribed voice message" if has_voice else "Transcribed audio file"
            text_parts.append(f"[{transcript_prefix}]\n\n{transcript_text.strip()}")
        elif audio_error:
            text_parts.append(f"[Audio transcription failed: {audio_error}]")

        # Add main message context
        default_media_note = (
            'User sent an image.' if has_photo and not (has_voice or has_audio) else
            'User sent an audio message.' if (has_voice or has_audio) and not message_text else
            ''
        )
        displayed_text = message_text if message_text else default_media_note
        
        # Build context message with optional quoted content
        if quoted_text and quoted_from:
            context_message = (
                f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\n"
                f"[{user_name} is replying to a message from {quoted_from}]\n"
                f"Original message: {quoted_text}\n\n"
                f"{user_name}'s reply: {displayed_text}"
            )
        else:
            context_message = f"[Message from Telegram user {user_name} (chat_id: {chat_id})]\n\n{displayed_text}"
        
        text_parts.append(context_message)

        # Combine all text parts into a single text content
        combined_text = "\n\n".join(text_parts)
        content_parts.append({
            "type": "text",
            "text": combined_text
        })
        
        print(f"Context message: {context_message}")
        
        # Notify user that message was received
        preferences = get_user_preferences(user_id)
        status_enabled = preferences.get("status_messages_enabled", True)  # Default to enabled
        
        if status_enabled:
            if has_photo:
                send_telegram_message(chat_id, f"({agent_name} is looking)")
            elif has_voice or has_audio:
                # Already sent a transcription notice above
                pass
            else:
                send_telegram_message(chat_id, "(please wait)")

        # Process agent response with streaming
        try:
            print("Using streaming response")
            response_stream = client.agents.messages.create_stream(
                agent_id=agent_id,
                messages=[
                    {
                        "role": "user",
                        "content": content_parts
                    }
                ],
                include_pings=True,
                request_options={
                    'timeout_in_seconds': 60,
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
                                prefixed_content = f"({agent_name} says)\n\n{content}"
                                send_telegram_message(chat_id, prefixed_content)
                                last_activity = current_time

                        elif message_type == "reasoning_message":
                            # Check if user has reasoning enabled in preferences
                            preferences = get_user_preferences(user_id)
                            reasoning_enabled = preferences.get("reasoning_enabled", True)  # Default to enabled

                            if reasoning_enabled:
                                reasoning_text = getattr(event, 'reasoning', '')
                                content = f"({agent_name} thought)\n{blockquote_message(reasoning_text)}"
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
                                        tool_msg = f"({agent_name} remembered)"
                                        tool_msg += f"\n{blockquote_message(args_obj['content'])}"

                                    elif tool_name == "archival_memory_search":
                                        tool_msg = f"({agent_name} searching memories: {args_obj['query']})"

                                    elif tool_name == "conversation_search":
                                        query = args_obj.get('query', '')
                                        tool_msg = f"({agent_name} searching conversations: {query})"

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
                                        tool_msg = f"({agent_name} updating memory)\n"
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
                                        tool_msg = f"({agent_name} modifying memory)"
                                        tool_msg += f"New:\n{blockquote_message(new_str)}\n"
                                        tool_msg += f"Old:\n{blockquote_message(old_str)}\n"

                                    elif tool_name == "memory":
                                        # New unified memory tool with subcommands
                                        command = args_obj.get('command', '')
                                        
                                        if command == "str_replace":
                                            path = args_obj.get('path', '')
                                            old_str = args_obj.get('old_str', '')
                                            new_str = args_obj.get('new_str', '')
                                            tool_msg = f"({agent_name} is forgetting)\n{blockquote_message(old_str)}\n\n"
                                            tool_msg += f"({agent_name} is remembering)\n{blockquote_message(new_str)}"
                                        
                                        elif command == "insert":
                                            path = args_obj.get('path', '')
                                            insert_text = args_obj.get('insert_text', '')
                                            tool_msg = f"({agent_name} is remembering)\n{blockquote_message(insert_text)}"
                                        
                                        elif command == "create":
                                            path = args_obj.get('path', '')
                                            description = args_obj.get('description', '')
                                            tool_msg = f"({agent_name} creating memory: {path})"
                                            if description:
                                                tool_msg += f"\n{blockquote_message(description)}"
                                        
                                        elif command == "delete":
                                            path = args_obj.get('path', '')
                                            tool_msg = f"({agent_name} deleting memory: {path})"
                                        
                                        elif command == "rename":
                                            old_path = args_obj.get('old_path', '')
                                            new_path = args_obj.get('new_path', '')
                                            if old_path and new_path:
                                                tool_msg = f"({agent_name} renaming memory: {old_path} -> {new_path})"
                                            else:
                                                path = args_obj.get('path', '')
                                                tool_msg = f"({agent_name} updating memory: {path})"
                                        
                                        else:
                                            tool_msg = f"({agent_name} using memory tool: {command})"

                                    elif tool_name == "run_code":
                                        code = args_obj.get('code', '')
                                        language = args_obj.get('language', 'python')
                                        tool_msg = f"({agent_name} ran code)"
                                        tool_msg += f"\n```{language}\n{code}\n```"

                                    elif tool_name == "web_search":
                                        query = args_obj.get('query', '')
                                        tool_msg = f"({agent_name} is searching for \"{query}\")"

                                    else:
                                        tool_msg = f"({agent_name} using tool: {tool_name})"
                                        formatted_args = json.dumps(args_obj, indent=2)
                                        tool_msg += f"\n```json\n{formatted_args}\n```"

                                except Exception as e:
                                    print(f"Error parsing tool arguments: {e}")
                                    tool_msg = f"({agent_name} using tool: {tool_name})\n```\n{arguments}\n```"

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

def handle_template_selection(template_name: str, user_id: str, chat_id: str):
    """
    Handle agent template selection - creates a pre-configured agent
    """
    try:
        from letta_client import Letta
        
        # Check for user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            print(f"Error retrieving credentials for user {user_id}: {cred_error}")
            response = "(hmm, need to authenticate first)\n\ndo /login with your api key"
            keyboard = create_inline_keyboard([["show me how"]])
            send_telegram_message(chat_id, response, keyboard)
            return
        
        if not user_credentials:
            response = "(need to authenticate first)\n\nuse /login to sign in"
            keyboard = create_inline_keyboard([["show me how"]])
            send_telegram_message(chat_id, response, keyboard)
            return
        
        # Use user-specific credentials
        letta_api_key = user_credentials["api_key"]
        letta_api_url = user_credentials["api_url"]
        
        # Initialize Letta client
        client = get_letta_client(letta_api_key, letta_api_url, timeout=120.0)
        
        # Handle Ion as special case with sophisticated memory architecture
        if template_name == "ion":
            try:
                # Get current project for user
                current_project = get_chat_project(chat_id)
                if not current_project:
                    send_telegram_message(chat_id, "(error: no project configured - use /projects to select one)")
                    return

                project_id = current_project["project_id"]
                user_name = user_credentials.get("user_name", "User")

                # Create Ion agent with sophisticated memory architecture
                agent = create_ion_agent(client, project_id, user_name)
                
                # Save agent selection
                save_chat_agent(chat_id, agent.id, agent.name)
                
                # Send brief status message
                send_telegram_message(chat_id, f"({agent.name} is ready - we've asked {agent.name} to greet you, please wait)")
                
                # Create introduction message for Ion
                intro_context = f"[User {user_name} just created you as their Ion agent via Telegram bot]\n\nIntroduce yourself as Ion to {user_name}. Explain briefly that you're different - you remember everything and develop theories about how they think. Suggest ways to begin:\n• Share a link or article you'd like to discuss\n• Ask me to research something you're curious about\n• Tell me about yourself - interests, work, what excites you\n• Give me a problem to think about with you\n• Or just start talking - I learn from everything we discuss\n\nMention that unlike other AIs, you'll remember this conversation forever and build on it next time."
                
                # Send introduction request to Ion
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
                
                # Stream Ion's introduction
                for event in response_stream:
                    if hasattr(event, 'message_type') and event.message_type == "assistant_message":
                        content = getattr(event, 'content', '')
                        if content and content.strip():
                            send_telegram_message(chat_id, content)
                
                return
                
            except Exception as e:
                from letta_client.core.api_error import ApiError
                print(f"Error creating Ion agent: {str(e)}")
                if isinstance(e, ApiError) and hasattr(e, 'status_code') and e.status_code == 521:
                    send_telegram_message(chat_id, "(letta servers are experiencing high load. please try again in a few moments)")
                else:
                    send_telegram_message(chat_id, f"(couldn't create Ion: {str(e)[:100]})")
                return
        
        # Only Ion template is available - all other requests should be redirected
        send_telegram_message(chat_id, f"('{template_name}' template is no longer available)\n\nuse /template ion to create Ion, or /agents to see existing agents")

    except Exception as e:
        print(f"Error in template selection: {str(e)}")
        send_telegram_message(chat_id, "(something went wrong with the template)")

def handle_callback_query(update: dict):
    """
    Handle callback queries from inline keyboard buttons
    """
    try:
        callback_query = update["callback_query"]
        callback_data = callback_query["data"]
        chat_id = str(callback_query["message"]["chat"]["id"])
        user_id = str(callback_query["from"]["id"])
        message_id = callback_query["message"]["message_id"]
        
        # Answer the callback query to remove loading state
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if bot_token:
            import requests
            answer_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
            requests.post(answer_url, data={"callback_query_id": callback_query["id"]})
        
        print(f"Handling callback: {callback_data} from user {user_id}")
        
        # Handle different callback actions
        if callback_data == "sure":
            # Start onboarding flow
            response = "(cool. you'll need an api key from letta)\n\n1. head to app.letta.com\n2. make an account if you need one\n3. grab your api key from settings"
            keyboard = create_inline_keyboard([
                ["got my key", "need help"]
            ])
            send_telegram_message(chat_id, response, keyboard)
            
        elif callback_data == "i_know_what_i'm_doing":
            send_telegram_message(chat_id, "(alright. use /login when you're ready)")

        elif callback_data == "i_have_a_key":
            msg = (
                "(great. send `/login <api_key>`)\n\n"
                "i will delete the key message immediately. for safety, use direct messages, not groups.\n\n"
                "example: /login sk-abc123"
            )
            keyboard = create_inline_keyboard([["done"]])
            send_telegram_message(chat_id, msg, keyboard)

        elif callback_data == "i_sent_it":
            send_telegram_message(chat_id, "(waiting for your /login command)")
            
        elif callback_data == "got_my_key":
            response = "(nice. send /login <your-key>)\n\nexample: /login sk-abc123\n\ni'll delete the message right away for privacy"
            keyboard = create_inline_keyboard([["done"]])
            send_telegram_message(chat_id, response, keyboard)
            
        elif callback_data == "need_help":
            send_telegram_message(chat_id, "(visit app.letta.com and click 'sign up' if you don't have an account. then go to settings → api keys)")
            
        elif callback_data == "got_it":
            send_telegram_message(chat_id, "(waiting for your /login command)")
            
        elif callback_data == "just_chat" or callback_data == "maybe_later":
            send_telegram_message(chat_id, "(alright)")
            
        elif callback_data == "start_setup":
            # Redirect to onboarding flow
            response = "(cool. you'll need an api key from letta)\n\n1. head to app.letta.com\n2. make an account if you need one\n3. grab your api key from settings"
            keyboard = create_inline_keyboard([
                ["got my key", "need help"]
            ])
            send_telegram_message(chat_id, response, keyboard)
            
        elif callback_data == "i_have_an_account":
            response = "(alright. use /login to connect your account)"
            send_telegram_message(chat_id, response)
            
        elif callback_data == "learn_more":
            response = "(about letta)\n\nletta agents have persistent memory - they remember everything from previous conversations\n\nvisit letta.com to learn more"
            send_telegram_message(chat_id, response)
            
        elif callback_data == "show_me_how":
            response = "(getting your api key)\n\n1. go to app.letta.com\n2. sign up or log in\n3. click on settings\n4. find api keys section\n5. create new key\n6. copy it\n7. come back here and send /login <your-key>"
            send_telegram_message(chat_id, response)
            
        elif callback_data == "create_new":
            # Show template options
            response = "(pick a starter template)"
            keyboard = create_inline_keyboard([
                [("create Ion", "template_ion")]
            ])
            send_telegram_message(chat_id, response, keyboard)
            
        elif callback_data == "show_all_options":
            response = "(here's what you can do)\n\n/agents - see your agents\n/projects - view projects\n/tool - manage tools\n/help - all commands"
            keyboard = create_inline_keyboard([
                [("show my agents", "cmd_agents")],
                [("pick a template", "create_new")]
            ])
            send_telegram_message(chat_id, response, keyboard)
            
        elif callback_data == "just_explore":
            send_telegram_message(chat_id, "(cool. type /help anytime if you need it)")
            
        # Tool menu navigation
        elif callback_data == "tool_menu_done":
            send_telegram_message(chat_id, "(alright)")
            
        elif callback_data == "tool_menu_attach":
            # Show attach menu (page 0)
            handle_tool_attach_menu(user_id, chat_id, page=0)
            
        elif callback_data == "tool_menu_detach":
            # Show detach menu
            handle_tool_detach_menu(user_id, chat_id)
            
        elif callback_data == "tool_menu_back":
            # Go back to main tool menu
            handle_tool_command("/tool", {"message": {"from": {"id": user_id}}}, chat_id)
            
        elif callback_data.startswith("tool_attach_page_"):
            # Handle pagination for attach menu
            page = int(callback_data.replace("tool_attach_page_", ""))
            handle_tool_attach_menu(user_id, chat_id, page=page)
            
        # Command shortcuts from buttons
        elif callback_data == "cmd_agents":
            # Simulate /agents command
            handle_agents_command({"message": {"from": {"id": user_id}}}, chat_id)
            
        elif callback_data == "cmd_tool":
            # Simulate /tool command
            handle_tool_command("/tool", {"message": {"from": {"id": user_id}}}, chat_id)
            
        elif callback_data == "cmd_projects":
            # Simulate /projects command
            handle_projects_command("/projects", {"message": {"from": {"id": user_id}}}, chat_id)
            
        # Template selections
        elif callback_data.startswith("template_"):
            template_name = callback_data.replace("template_", "")
            handle_template_selection(template_name, user_id, chat_id)
            
        # Agent selection
        elif callback_data.startswith("select_agent_"):
            agent_id = callback_data.replace("select_agent_", "")
            handle_agent_command(f"/agent {agent_id}", {"message": {"from": {"id": user_id}}}, chat_id)
            
        # Project switching
        elif callback_data.startswith("switch_project_"):
            project_id = callback_data.replace("switch_project_", "")
            handle_project_command(f"/project {project_id}", {"message": {"from": {"id": user_id}}}, chat_id)
            
        # Shortcut switching (via /switch buttons)
        elif callback_data.startswith("switch_shortcut_"):
            shortcut_name = callback_data.replace("switch_shortcut_", "")
            # Reuse the same handler as the text command
            handle_switch_command(f"/switch {shortcut_name}", {"message": {"from": {"id": user_id}}}, chat_id)
            
        # Tool management
        elif callback_data.startswith("attach_tool_"):
            tool_name = callback_data.replace("attach_tool_", "")
            # Attach the tool
            handle_tool_command(f"/tool attach {tool_name}", {"message": {"from": {"id": user_id}}}, chat_id)
            # Go back to attach menu page 0 (tools have changed, reset to first page)
            handle_tool_attach_menu(user_id, chat_id, page=0)
            
        elif callback_data.startswith("detach_tool_"):
            tool_name = callback_data.replace("detach_tool_", "")
            # Detach the tool
            handle_tool_command(f"/tool detach {tool_name}", {"message": {"from": {"id": user_id}}}, chat_id)
            # Go back to detach menu to show updated list
            handle_tool_detach_menu(user_id, chat_id)
            
        else:
            print(f"Unknown callback data: {callback_data}")
            
    except Exception as e:
        print(f"Error handling callback query: {str(e)}")
        try:
            if 'chat_id' in locals():
                send_telegram_message(chat_id, "(hmm, that didn't work. try the command directly?)")
        except:
            pass

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),
        modal.Secret.from_name("letta-oauth"),
    ],
    volumes={"/data": volume},
    scaledown_window=SCALEDOWN_WINDOW,
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
        # Handle callback queries (button clicks)
        if "callback_query" in update:
            handle_callback_query(update)
            return {"ok": True}
        
        # Extract message details from Telegram update
        if "message" in update:
            message = update["message"]
            has_text = "text" in message
            has_photo = "photo" in message
            has_voice = "voice" in message
            has_audio = "audio" in message
            
            # Skip unsupported message types
            if not (has_text or has_photo or has_voice or has_audio):
                return {"ok": True}
            
            chat_id = str(message["chat"]["id"])
            user_name = message["from"].get("username", "Unknown")
            
            # Handle commands only for text messages
            if has_text:
                message_text = message["text"]
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
                elif message_text.startswith('/template'):
                    handle_template_command(message_text, update, chat_id)
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
                elif message_text.startswith('/reasoning'):
                    handle_reasoning_command(message_text, update, chat_id)
                    return {"ok": True}
                elif message_text.startswith('/ack'):
                    handle_ack_command(message_text, update, chat_id)
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
                else:
                    # Non-command text message - spawn background processing
                    send_telegram_typing(chat_id)
                    print("Spawning background task for text message")
                    process_message_async.spawn(update)
            else:
                # Media message (photo/audio/voice) - spawn background processing
                if has_photo:
                    print(f"Received photo from {user_name} in chat {chat_id}")
                elif has_voice:
                    print(f"Received voice message from {user_name} in chat {chat_id}")
                elif has_audio:
                    print(f"Received audio file from {user_name} in chat {chat_id}")
                send_telegram_typing(chat_id)
                print("Spawning background task for media message")
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

        # Check if no API key provided - offer OAuth
        if len(parts) < 2 or not parts[1].startswith("sk-"):
            oauth_callback_url = os.environ.get("LETTA_OAUTH_CALLBACK_URL")
            if oauth_callback_url:
                # Generate OAuth URL
                state = generate_oauth_state()
                code_verifier, code_challenge = generate_pkce_pair()
                store_oauth_pending(
                    state=state,
                    user_id=user_id,
                    platform="telegram",
                    chat_id=chat_id,
                    code_verifier=code_verifier
                )
                oauth_url = build_oauth_url(state, code_challenge, oauth_callback_url)
                response = "(sign in with your letta account)\n\ntap the button below, or use /login <api_key> for manual setup."
                keyboard = create_inline_keyboard([
                    ({"text": "sign in with letta", "url": oauth_url}),
                ])
                send_telegram_message(chat_id, response, keyboard)
            else:
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
                    client = get_letta_client(api_key, api_url, timeout=60.0)

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

            response = f"(all set. welcome {user_name.lower()})\n\n"
            
            # Check if user has agents to offer appropriate next steps
            try:
                client = get_letta_client(api_key, api_url, timeout=60.0)
                agents = client.agents.list(project_id=default_project_id) if default_project_id else []
                
                if agents and len(agents) > 0:
                    response += "want to pick an agent?\n\n"
                    response += "here's what each one offers:\n"
                    response += "• Ion - adaptive companion with advanced memory that learns about you"
                    keyboard = create_inline_keyboard([
                        [("show my agents", "cmd_agents")],
                        [("create Ion", "template_ion")],
                        ["maybe later"]
                    ])
                else:
                    response += "looks like you need an agent. want to create one?\n\n"
                    response += "available templates:\n"
                    response += "• Ion - adaptive companion with advanced memory that learns about you"
                    keyboard = create_inline_keyboard([
                        [("create Ion", "template_ion")],
                        ["show all options"]
                    ])
                send_telegram_message(chat_id, response, keyboard)
                # Send compact help card
                send_compact_help_card(chat_id)
            except:
                # Fallback if we can't check agents
                response += "what's next?\n\n"
                response += "quick options:\n"
                response += "• Ion - adaptive companion with advanced memory that learns about you"
                keyboard = create_inline_keyboard([
                    [("show my agents", "cmd_agents")],
                    [("create Ion", "template_ion")],
                    [("pick a template", "create_new")],
                    ["just explore"]
                ])
                send_telegram_message(chat_id, response, keyboard)
                send_compact_help_card(chat_id)
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

def handle_reasoning_command(message: str, update: dict, chat_id: str):
    """
    Handle /reasoning command to enable/disable reasoning messages
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])

        # Parse the command
        parts = message.split()
        if len(parts) < 2:
            send_telegram_message(chat_id, "Usage: /reasoning enable|disable")
            return

        action = parts[1].lower()

        # Get current preferences
        preferences = get_user_preferences(user_id)

        if action == "enable":
            preferences["reasoning_enabled"] = True
            save_user_preferences(user_id, preferences)
            send_telegram_message(chat_id, "✅ Reasoning messages enabled")
        elif action == "disable":
            preferences["reasoning_enabled"] = False
            save_user_preferences(user_id, preferences)
            send_telegram_message(chat_id, "❌ Reasoning messages disabled")
        else:
            send_telegram_message(chat_id, "Usage: /reasoning enable|disable")

    except Exception as e:
        print(f"Error handling reasoning command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to update reasoning preferences)")

def handle_ack_command(message: str, update: dict, chat_id: str):
    """
    Handle /ack command to enable/disable status messages like (please wait)
    """
    try:
        # Extract user ID from the update
        user_id = str(update["message"]["from"]["id"])

        # Parse the command
        parts = message.split()
        if len(parts) < 2:
            send_telegram_message(chat_id, "Usage: /ack enable|disable")
            return

        action = parts[1].lower()

        # Get current preferences
        preferences = get_user_preferences(user_id)

        if action == "enable":
            preferences["status_messages_enabled"] = True
            save_user_preferences(user_id, preferences)
            send_telegram_message(chat_id, "(status messages enabled)")
        elif action == "disable":
            preferences["status_messages_enabled"] = False
            save_user_preferences(user_id, preferences)
            send_telegram_message(chat_id, "(status messages disabled)")
        else:
            send_telegram_message(chat_id, "Usage: /ack enable|disable")

    except Exception as e:
        print(f"Error handling ack command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to update status preferences)")

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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
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
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
        
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            # Re-raise so infrastructure can track it
            raise

        if not credentials:
            send_telegram_message(chat_id, "❌ You are not logged in. Use /login to sign in.")
            return

        # Revoke OAuth tokens if applicable, then delete credentials
        try:
            revoke_oauth_token(user_id)
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
            send_telegram_message(chat_id, "❌ **Error accessing your credentials**\n\nPlease try /login first.")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

            # Create the default agent
            send_telegram_message(chat_id, "(creating assistant)")
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
            send_telegram_message(chat_id, f"✅ **{agent.name}** created and selected.\n\nAgent ID: `{agent.id}`\n\nLet me introduce myself — this may take a moment.")
            send_compact_help_card(chat_id)

            # Create introduction message
            intro_context = f"[User {user_name} just created you using /make-default-agent command via Telegram (chat_id: {chat_id})]\n\nIntroduce yourself briefly to {user_name} and ask them to tell you a bit about themselves. Then provide a few starter ideas in bullet points, such as:\n• Send a link to an article for me to read and summarize\n• Ask me to research a topic you're curious about\n• Introduce yourself in detail so I can remember your interests\n• Paste information you'd like me to remember\n• Ask questions about current events or news\n\nYou can mention they can learn more about Letta on Discord (https://discord.com/invite/letta) if relevant."

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
            from letta_client.core.api_error import ApiError
            print(f"Error creating default agent: {e}")
            if isinstance(e, ApiError) and hasattr(e, 'status_code') and e.status_code == 521:
                send_telegram_message(chat_id, "(letta servers are experiencing high load. please try again in a few moments)")
            else:
                send_telegram_message(chat_id, "(error: unable to create default agent)")

    except Exception as e:
        print(f"Error handling make-default-agent command: {str(e)}")
        send_telegram_message(chat_id, "(error: unable to process command)")

def handle_template_command(message_text: str, update: dict, chat_id: str):
    """
    Handle /template command to list and create agent templates
    """
    try:
        # Extract user details
        user_id = str(update["message"]["from"]["id"])
        user_name = update["message"]["from"].get("username", "Unknown")
        
        # Check authentication
        user_credentials = get_user_credentials(user_id)
        if not user_credentials:
            send_telegram_message(chat_id, "(you need to /login first)")
            return
            
        # Check for project
        current_project = get_chat_project(chat_id)
        if not current_project:
            send_telegram_message(chat_id, "(no project configured - use /projects to select one)")
            return
        
        # Parse template name if provided
        parts = message_text.strip().split(maxsplit=1)
        if len(parts) > 1:
            template_name = parts[1].lower()
            # Only Ion template is available
            if template_name == "ion":
                handle_template_selection("ion", user_id, chat_id)
                return
            else:
                send_telegram_message(chat_id, f"('{template_name}' template is no longer available)\n\nonly Ion is available: /template ion")
                return
        
        # Show template list (only Ion available)
        response = "**Available Templates**\n\n"
        response += "• **Ion** - adaptive AI with infinite memory that develops theories about you\n\n"
        response += "Use: `/template ion` or click below"
        
        keyboard = create_inline_keyboard([
            [("create Ion", "template_ion")],
            ["cancel"]
        ])
        
        send_telegram_message(chat_id, response, keyboard)
        
    except Exception as e:
        print(f"Error handling template command: {str(e)}")
        send_telegram_message(chat_id, "(error listing templates)")

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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            # Re-raise so infrastructure can track it
            raise

        if not credentials:
            send_telegram_message(chat_id, "(not authenticated - use /login to sign in)")
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            # Re-raise so infrastructure can track it
            raise

        if credentials:
            # User is already authenticated - check if they have an agent selected
            agent_info = get_chat_agent_info(chat_id)
            if agent_info:
                response = f"(welcome back {first_name.lower()}. you're chatting with {agent_info['agent_name']})"
                keyboard = create_inline_keyboard([
                    [("switch agent", "cmd_agents"), ("view tools", "cmd_tool")],
                    ["just chat"]
                ])
            else:
                response = f"(welcome back {first_name.lower()}. want to pick an agent?)\n\n"
                response += "here's what each one offers:\n"
                response += "• Ion - adaptive companion with advanced memory that learns about you"
                keyboard = create_inline_keyboard([
                    [("show my agents", "cmd_agents")],
                    [("create Ion", "template_ion")],
                    ["maybe later"]
                ])
            send_telegram_message(chat_id, response, keyboard)
        else:
            # New user - provide interactive setup guide
            # Check if OAuth is configured
            oauth_callback_url = os.environ.get("LETTA_OAUTH_CALLBACK_URL")
            response = f"(welcome to letta, {first_name.lower()})\n\nconnect your account to start."

            if oauth_callback_url:
                # Generate OAuth URL for inline button
                state = generate_oauth_state()
                code_verifier, code_challenge = generate_pkce_pair()
                store_oauth_pending(
                    state=state,
                    user_id=user_id,
                    platform="telegram",
                    chat_id=chat_id,
                    code_verifier=code_verifier
                )
                oauth_url = build_oauth_url(state, code_challenge, oauth_callback_url)
                keyboard = create_inline_keyboard([
                    ({"text": "sign in with letta", "url": oauth_url}),
                    ("i have an api key", "i_have_a_key"),
                    ("learn more", "learn_more"),
                ])
            else:
                # Fallback without OAuth
                keyboard = create_inline_keyboard([
                    ({"text": "get api key", "url": "https://app.letta.com"}),
                    ("i have a key", "i_have_a_key"),
                    ("learn more", "learn_more"),
                ])
            send_telegram_message(chat_id, response, keyboard)

    except Exception as e:
        print(f"Error handling start command: {str(e)}")
        send_telegram_message(chat_id, "(something went wrong. try /help maybe?)")

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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            # Re-raise so infrastructure can track it
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
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
                client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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
                    response += f"\nAgent ID: `{current_agent_id}`\n\n"
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
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
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
        
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
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
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
        
        try:
            # Get the specific memory block
            block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=block_label)
            block_value = getattr(block, 'value', '')
            
            if not block_value:
                send_telegram_message(chat_id, f"(error: block '{block_label}' is empty)")
                return
                
            response = f"({agent_name} `{block_label}`)\n\n{blockquote_message(block_value)}"
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
/login - Sign in with Letta account
/login <api_key> - Authenticate with API key
/logout - Remove credentials
/status - Check authentication
/project - Show/switch project
/projects - List projects
/agent - Show/switch agent
/agents - List agents
/make-default-agent - Create default agent
/template - List and create agent templates
/ade - Get agent web link
/tool - Manage tools
/telegram-notify - Enable proactive notifications
/shortcut - Manage shortcuts
/switch <name> - Quick switch
/blocks - List memory blocks
/block <label> - View memory block
/reasoning enable|disable - Show/hide reasoning messages
/ack enable|disable - Show/hide status messages
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
                client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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

            # Build clean response message with limited buttons
            response = "(your agents)\n\n"
            
            if current_agent_id:
                response += f"currently using: {current_agent_name}\n\n"

            # Show all agents in text
            response += f"available ({len(agents)}):\n"
            for agent in agents[:10]:  # Show first 10 in detail
                response += f"• {agent.name}\n  `{agent.id}`\n"
            
            if len(agents) > 10:
                response += f"\nand {len(agents) - 10} more\n"
            
            response += "\n"
            
            # Only show buttons for first 5 agents (excluding current)
            buttons = []
            button_count = 0
            for agent in agents:
                if agent.id != current_agent_id and button_count < 5:
                    buttons.append([(f"use {agent.name[:25]}", f"select_agent_{agent.id}")])
                    button_count += 1
            
            if len(agents) > 5:
                response += "(showing first 5 as buttons)\n"
            response += "type /agent <id> to select any agent"
            
            keyboard = create_inline_keyboard(buttons) if buttons else None
            send_telegram_message(chat_id, response, keyboard)
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
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
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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
                send_telegram_message(chat_id, "❌ Usage: `/tool attach <tool_name>`\n\nExample: `/tool attach web_search`")
                return
            tool_name = " ".join(parts[2:])  # Support multi-word tool names
            handle_tool_attach(client, project_id, agent_id, tool_name, chat_id)
        elif subcommand == "detach":
            # /tool detach <name>
            if len(parts) < 3:
                send_telegram_message(chat_id, "❌ Usage: `/tool detach <tool_name>`\n\nExample: `/tool detach web_search`")
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

        # Build response message showing current tools
        response = "(agent tools)\n\n"
        
        # Show attached tools
        if attached_tools:
            response += f"currently using {len(attached_tools)} tools:\n"
            for tool in attached_tools[:10]:
                response += f"• {tool.name}\n"
            if len(attached_tools) > 10:
                response += f"• and {len(attached_tools) - 10} more\n"
        else:
            response += "no tools attached yet\n"

        response += "\n"
        
        # Calculate available tools
        attached_tool_ids = {tool.id for tool in attached_tools}
        available_tools = [tool for tool in all_tools if tool.id not in attached_tool_ids]
        response += f"{len(available_tools)} tools available to add"

        # Navigation buttons
        buttons = []
        if attached_tools:
            buttons.append([("remove tools", "tool_menu_detach")])
        if available_tools:
            buttons.append([("add tools", "tool_menu_attach")])
        buttons.append([("done", "tool_menu_done")])
        
        keyboard = create_inline_keyboard(buttons)
        send_telegram_message(chat_id, response, keyboard)

    except Exception as e:
        print(f"Error in handle_tool_list: {str(e)}")
        send_telegram_message(chat_id, f"❌ Error listing tools: {str(e)}")
        raise

def handle_tool_attach_menu(user_id: str, chat_id: str, page: int = 0):
    """
    Show paginated menu for attaching tools
    """
    try:
        from letta_client import Letta
        
        # Get user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            send_telegram_message(chat_id, "(need to authenticate first - use /login)")
            return
            
        if not user_credentials:
            send_telegram_message(chat_id, "(need to authenticate first - use /login)")
            return
            
        # Get current project and agent
        current_project = get_chat_project(chat_id)
        if not current_project:
            send_telegram_message(chat_id, "(no project set - use /projects)")
            return
            
        agent_id = get_chat_agent(chat_id)
        if not agent_id:
            send_telegram_message(chat_id, "(no agent selected - use /agents)")
            return
            
        # Initialize client
        client = get_letta_client(user_credentials["api_key"], user_credentials["api_url"], timeout=60.0)
        
        # Get attached tools first
        attached_tools = client.agents.tools.list(agent_id=agent_id)
        attached_tool_ids = {tool.id for tool in attached_tools}
        
        # Get available tools with pagination
        page_size = 8
        
        # Get all tools and filter (since API doesn't support filtering)
        all_tools = client.tools.list()
        available_tools = [tool for tool in all_tools if tool.id not in attached_tool_ids]
        
        if not available_tools:
            response = "(all tools already attached)"
            keyboard = create_inline_keyboard([[("back", "tool_menu_back")]])
            send_telegram_message(chat_id, response, keyboard)
            return
        
        # Calculate pagination
        total_tools = len(available_tools)
        total_pages = (total_tools + page_size - 1) // page_size
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total_tools)
        
        # Get tools for current page
        page_tools = available_tools[start_idx:end_idx]
        
        # Build response
        response = f"(add tools - page {page + 1}/{total_pages})\n\n"
        response += f"showing {start_idx + 1}-{end_idx} of {total_tools} available:\n\n"
        
        buttons = []
        
        # Show tools for current page
        for tool in page_tools:
            response += f"• {tool.name}\n"
            buttons.append([(tool.name, f"attach_tool_{tool.name}")])
            
        response += "\ntap a tool to attach it"
        
        # Add navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(("← previous", f"tool_attach_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(("next →", f"tool_attach_page_{page + 1}"))
        
        if nav_buttons:
            buttons.append(nav_buttons)
            
        buttons.append([("back", "tool_menu_back")])
        
        keyboard = create_inline_keyboard(buttons)
        send_telegram_message(chat_id, response, keyboard)
        
    except Exception as e:
        print(f"Error in tool attach menu: {str(e)}")
        send_telegram_message(chat_id, "(something went wrong)")

def handle_tool_detach_menu(user_id: str, chat_id: str):
    """
    Show menu for detaching tools
    """
    try:
        from letta_client import Letta
        
        # Get user credentials
        try:
            user_credentials = get_user_credentials(user_id)
        except Exception as cred_error:
            send_telegram_message(chat_id, "(need to authenticate first - use /login)")
            return
            
        if not user_credentials:
            send_telegram_message(chat_id, "(need to authenticate first - use /login)")
            return
            
        # Get current agent
        agent_id = get_chat_agent(chat_id)
        if not agent_id:
            send_telegram_message(chat_id, "(no agent selected - use /agents)")
            return
            
        # Initialize client
        client = get_letta_client(user_credentials["api_key"], user_credentials["api_url"], timeout=60.0)
        
        # Get attached tools
        attached_tools = client.agents.tools.list(agent_id=agent_id)
        
        if not attached_tools:
            response = "(no tools to remove)"
            keyboard = create_inline_keyboard([[("back", "tool_menu_back")]])
            send_telegram_message(chat_id, response, keyboard)
            return
            
        # Show attached tools with buttons
        response = f"(remove tools - {len(attached_tools)} attached)\n\n"
        buttons = []
        
        # List ALL attached tools
        for tool in attached_tools:
            response += f"• {tool.name}\n"
            
        response += "\n"
        
        # Create buttons for ALL tools (Telegram allows up to 100 buttons)
        for tool in attached_tools:
            buttons.append([(tool.name, f"detach_tool_{tool.name}")])
            
        buttons.append([("back", "tool_menu_back")])
        
        keyboard = create_inline_keyboard(buttons)
        send_telegram_message(chat_id, response, keyboard)
        
    except Exception as e:
        print(f"Error in tool detach menu: {str(e)}")
        send_telegram_message(chat_id, "(something went wrong)")

def handle_tool_attach(client, project_id: str, agent_id: str, tool_name: str, chat_id: str):
    """
    Handle attaching a tool to the agent
    """
    try:
        send_telegram_typing(chat_id)

        # Search for the tool by name
        try:
            all_tools = client.tools.list(name=tool_name)
            if not all_tools:
                # Try partial name matching if exact match fails
                all_tools = client.tools.list()
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

            # Find the tool by name (exact match first, then partial match)
            exact_matches = [tool for tool in attached_tools if tool.name.lower() == tool_name.lower()]
            if exact_matches:
                matching_tools = exact_matches
            else:
                # Fall back to substring match if no exact match found
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
                send_telegram_message(chat_id, "(authentication required - use /login to sign in)")
                return
            
            letta_api_key = credentials["api_key"]
            letta_api_url = credentials.get("api_url", "https://api.letta.com")
        except Exception as e:
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            return

        # Get current agent
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            send_telegram_message(chat_id, "(error: no agent configured - use /agents to select one)")
            return
            
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Initialize Letta client
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
        
        if subcommand == "status":
            # Check tool attachment status
            try:
                attached_tools = client.agents.tools.list(agent_id=agent_id)
                notify_tool_attached = any(tool.name == "notify_via_telegram" for tool in attached_tools)
                
                # Get agent to check environment variables
                print(f"DEBUG STATUS: Checking env vars for agent {agent_id}")
                agent = client.agents.retrieve(agent_id=agent_id)
                raw_env_vars_status = agent.tool_exec_environment_variables
                print(f"DEBUG STATUS: Raw env vars type: {type(raw_env_vars_status)}")
                print(f"DEBUG STATUS: Raw env vars value: {repr(raw_env_vars_status)}")
                
                env_vars = raw_env_vars_status or []
                print(f"DEBUG STATUS: After 'or []' - type: {type(env_vars)}, value: {repr(env_vars)}")
                
                has_bot_token = any(var.key == "TELEGRAM_BOT_TOKEN" for var in env_vars)
                has_chat_id = any(var.key == "TELEGRAM_CHAT_ID" for var in env_vars)
                print(f"DEBUG STATUS: has_bot_token={has_bot_token}, has_chat_id={has_chat_id}")
                
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
            
            # Track if we register the tool for status message
            tool_was_registered = False
            
            # Step 1: Check if notify_via_telegram tool exists and register/attach it
            try:
                print(f"DEBUG: Starting tool attachment for chat {chat_id}")
                
                # Search for notify_via_telegram tool
                all_tools = client.tools.list(name="notify_via_telegram")
                print(f"DEBUG: Found {len(all_tools)} notify_via_telegram tools")
                
                if not all_tools:
                    # Tool doesn't exist, register it automatically
                    print(f"DEBUG: Tool not found, registering new tool")
                    send_telegram_message(chat_id, "🔧 **Registering notify_via_telegram tool**")
                    
                    registration_result = register_notify_tool(client)
                    print(f"DEBUG: Registration result: {registration_result}")
                    if registration_result["status"] == "error":
                        send_telegram_message(chat_id, f"❌ **Tool registration failed**\n\n{registration_result['message']}")
                        return
                    
                    notify_tool = registration_result["tool"]
                    tool_was_registered = True
                    print(f"DEBUG: Tool registered with ID: {notify_tool.id}")
                    send_telegram_message(chat_id, "✅ **Tool registered successfully!**")
                else:
                    notify_tool = all_tools[0]
                    print(f"DEBUG: Using existing tool with ID: {notify_tool.id}")
                
                # Check if already attached
                attached_tools = client.agents.tools.list(agent_id=agent_id)
                print(f"DEBUG: Agent has {len(attached_tools)} tools attached")
                if not any(tool.id == notify_tool.id for tool in attached_tools):
                    print(f"DEBUG: Attaching tool {notify_tool.id} to agent {agent_id}")
                    # Attach the tool
                    client.agents.tools.attach(agent_id=agent_id, tool_id=notify_tool.id)
                    print(f"DEBUG: Tool attached successfully")
                else:
                    print(f"DEBUG: Tool already attached to agent")
                
            except Exception as e:
                error_details = traceback.format_exc()
                print(f"Error attaching notify_via_telegram tool for chat {chat_id}: {str(e)}")
                print(f"Full traceback:\n{error_details}")
                
                # Send detailed error to user
                send_telegram_message(chat_id, f"""❌ **Error registering/attaching tool**

**Error:** {str(e)}
**Context:** Failed while registering or attaching notify_via_telegram tool

This could be due to:
- API authentication issues
- Tool registration permissions
- Network connectivity problems

Please try again or contact support if the issue persists.""")
                
                # Re-raise to ensure error is tracked by infrastructure
                raise
            
            # Step 2: Set up environment variables
            try:
                print(f"DEBUG: Starting environment configuration for agent {agent_id}")
                
                # Get current agent configuration
                agent = client.agents.retrieve(agent_id=agent_id)
                print(f"DEBUG: Retrieved agent object: {type(agent)}")
                print(f"DEBUG: Agent attributes: {dir(agent)}")
                
                # Get the raw environment variables
                raw_env_vars = agent.tool_exec_environment_variables
                print(f"DEBUG: Raw env vars type: {type(raw_env_vars)}")
                print(f"DEBUG: Raw env vars value: {repr(raw_env_vars)}")
                
                current_env_vars = raw_env_vars or []
                print(f"DEBUG: After 'or []' - type: {type(current_env_vars)}, value: {repr(current_env_vars)}")
                
                # Add Telegram environment variables
                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                print(f"DEBUG: Bot token exists: {bot_token is not None}")
                
                if not bot_token:
                    send_telegram_message(chat_id, "❌ TELEGRAM_BOT_TOKEN not available in server environment")
                    return
                
                print(f"DEBUG: Converting list to dictionary for API call...")
                # Convert list of AgentEnvironmentVariable objects to dictionary
                env_dict = {}
                if current_env_vars:
                    for var in current_env_vars:
                        env_dict[var.key] = var.value
                print(f"DEBUG: Converted to dict: {repr(env_dict)}")
                
                # Add new Telegram environment variables
                env_dict["TELEGRAM_BOT_TOKEN"] = bot_token
                env_dict["TELEGRAM_CHAT_ID"] = chat_id
                print(f"DEBUG: Final env_dict: {repr(env_dict)}")
                
                # Update agent with new environment variables
                print(f"DEBUG: About to call client.agents.modify...")
                client.agents.modify(
                    agent_id=agent_id,
                    tool_exec_environment_variables=env_dict
                )
                print(f"DEBUG: Agent modify completed successfully")
                
                # Show registration status in success message
                tool_status = "registered and attached" if tool_was_registered else "attached"
                print(f"DEBUG: tool_status = {tool_status}")
                
                send_telegram_message(chat_id, f"""✅ **Telegram Notifications Enabled**

**Agent:** {agent_name}
**Tool:** notify_via_telegram {tool_status}
**Environment:** Configured for this chat

Your agent can now send you proactive notifications using the `notify_via_telegram` tool!""")
                
            except Exception as e:
                error_details = traceback.format_exc()
                print(f"Error configuring environment for chat {chat_id}: {str(e)}")
                print(f"Full traceback:\n{error_details}")
                
                # Send detailed error to user
                send_telegram_message(chat_id, f"""❌ **Error configuring environment**

**Error:** {str(e)}
**Context:** Failed while setting up Telegram environment variables for agent

Please try again or contact support if the issue persists.""")
                
                # Re-raise to ensure error is tracked by infrastructure
                raise
        
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
                
                # Convert list to dict and remove Telegram-related environment variables
                filtered_vars = {}
                if current_env_vars:
                    for var in current_env_vars:
                        if var.key not in ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
                            filtered_vars[var.key] = var.value
                
                # Update agent
                client.agents.modify(
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
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
        client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
            return

        # Parse the command: /switch <shortcut_name>
        parts = message.strip().split()

        # If no arguments, list all shortcuts and include inline buttons to switch
        if len(parts) == 1:
            shortcuts = get_user_shortcuts(user_id)
            if not shortcuts:
                send_telegram_message(chat_id, "No shortcuts found. Use `/shortcut <name> <agent_id>` to create one first.")
                return

            response = ""
            buttons = []
            for name, data in shortcuts.items():
                agent_name = data.get("agent_name", "Unknown")
                response += f"`{name}`: {agent_name}\n"
                # One button per shortcut to switch directly
                buttons.append([(name, f"switch_shortcut_{name}")])

            keyboard = create_inline_keyboard(buttons) if buttons else None
            send_telegram_message(chat_id, response.rstrip(), keyboard)
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)
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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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

            # Get current project
            current_project = get_chat_project(chat_id)
            current_project_id = current_project["project_id"] if current_project else None
            
            # Build clean format with limited buttons
            response = "(projects)\n\n"
            
            if current_project_id:
                response += f"currently in: {current_project.get('project_name', 'unknown')}\n\n"

            response += f"available ({len(projects)}):\n"
            
            # Show first 10 projects in detail
            for project in projects[:10]:
                # Count agents in this project (skip for performance if many projects)
                if len(projects) <= 5:
                    try:
                        agents = client.agents.list(project_id=project.id, limit=1)
                        agent_count = len(agents) if agents else 0
                        response += f"• {project.name} ({agent_count} agents)\n"
                    except:
                        response += f"• {project.name}\n"
                else:
                    response += f"• {project.name}\n"
            
            if len(projects) > 10:
                response += f"\nand {len(projects) - 10} more\n"
            
            response += "\n"
            
            # Only show buttons for first 5 projects (excluding current)
            buttons = []
            button_count = 0
            for project in projects:
                if project.id != current_project_id and button_count < 5:
                    buttons.append([(f"switch to {project.name[:20]}", f"switch_project_{project.id}")])
                    button_count += 1
            
            if len(projects) > 5:
                response += "(showing first 5 as buttons)\n"
            response += "type /project <id> to select any project"

            keyboard = create_inline_keyboard(buttons) if buttons else None
            send_telegram_message(chat_id, response, keyboard)

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
            send_telegram_message(chat_id, "(error: unable to access credentials - try /logout then /login)")
            raise

        if not user_credentials:
            send_telegram_message(chat_id, "❌ **Authentication Required**\n\nUse /login to sign in with your Letta account.")
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
            client = get_letta_client(letta_api_key, letta_api_url, timeout=60.0)

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

def download_telegram_file(file_id: str, bot_token: str) -> tuple[str, str]:
    """
    Download any file from Telegram and save to a temp file, preserving extension.

    Returns:
        (temp_file_path, telegram_file_path)
    """
    import requests
    import tempfile
    import os as _os

    # Get file info from Telegram
    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile"
    file_info_response = requests.get(file_info_url, params={"file_id": file_id})
    file_info_response.raise_for_status()

    file_info = file_info_response.json()
    if not file_info.get("ok"):
        raise Exception(f"Failed to get file info: {file_info.get('description', 'Unknown error')}")

    file_path = file_info["result"]["file_path"]

    # Download the actual file
    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    file_response = requests.get(file_url)
    file_response.raise_for_status()

    # Preserve extension in temp file
    ext = ''
    base = _os.path.basename(file_path)
    if '.' in base:
        ext = '.' + base.split('.')[-1]

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(file_response.content)
        tmp_path = tmp.name

    return tmp_path, file_path

def ensure_supported_audio(input_path: str) -> str:
    """
    Ensure audio is in a format supported by OpenAI. If not, convert to mp3 via ffmpeg.

    Supported extensions: mp3, mp4, mpeg, mpga, m4a, wav, webm
    """
    import os as _os
    supported_exts = {'.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm'}
    ext = _os.path.splitext(input_path)[1].lower()
    if ext in supported_exts:
        return input_path

    # Convert using ffmpeg to mp3 mono 16k to reduce size
    import tempfile
    import subprocess

    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_out:
        output_path = tmp_out.name

    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-ac', '1', '-ar', '16000',
        output_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        # Clean up if conversion failed
        try:
            if _os.path.exists(output_path):
                _os.remove(output_path)
        except Exception:
            pass
        raise Exception(f"ffmpeg conversion failed: {e.stderr.decode('utf-8', errors='ignore')[:500]}")

    return output_path

def transcribe_audio_file(audio_path: str) -> str:
    """
    Transcribe an audio file using OpenAI's Audio Transcriptions API.
    Uses model from OPENAI_TRANSCRIBE_MODEL or defaults to gpt-4o-mini-transcribe.
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise Exception("OPENAI_API_KEY not configured; cannot transcribe audio.")

    model = os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    with open(audio_path, 'rb') as f:
        try:
            result = client.audio.transcriptions.create(
                model=model,
                file=f,
            )
        except Exception as e:
            raise Exception(f"OpenAI transcription error: {str(e)}")

    # New SDK returns an object with .text
    return getattr(result, 'text', '') or ''

def download_telegram_image(file_id: str, bot_token: str) -> tuple[str, str]:
    """
    Download an image from Telegram and return base64 data and media type
    
    Returns:
        tuple: (base64_data, media_type) or raises exception on failure
    """
    import requests
    import base64
    
    # Get file info from Telegram
    file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile"
    file_info_response = requests.get(file_info_url, params={"file_id": file_id})
    file_info_response.raise_for_status()
    
    file_info = file_info_response.json()
    if not file_info.get("ok"):
        raise Exception(f"Failed to get file info: {file_info.get('description', 'Unknown error')}")
    
    file_path = file_info["result"]["file_path"]
    
    # Download the actual file
    file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    file_response = requests.get(file_url)
    file_response.raise_for_status()
    
    # Convert to base64
    image_data = base64.standard_b64encode(file_response.content).decode("utf-8")
    
    # Determine media type from file extension
    if file_path.lower().endswith(('.jpg', '.jpeg')):
        media_type = "image/jpeg"
    elif file_path.lower().endswith('.png'):
        media_type = "image/png"
    elif file_path.lower().endswith('.gif'):
        media_type = "image/gif"
    elif file_path.lower().endswith('.webp'):
        media_type = "image/webp"
    else:
        media_type = "image/jpeg"  # Default fallback
    
    return image_data, media_type

def send_telegram_message(chat_id: str, text: str, reply_markup: dict = None):
    """
    Send a message to Telegram chat, splitting long messages intelligently
    Optionally includes inline keyboard buttons
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
            
            # Only add reply_markup to the last chunk
            if reply_markup and i == len(chunks) - 1:
                payload["reply_markup"] = json.dumps(reply_markup)
            
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

def create_inline_keyboard(buttons: list) -> dict:
    """
    Create an inline keyboard markup from a list of button configurations
    
    Args:
        buttons: List of button rows, where each row is a list of (text, callback_data) tuples
                 or a list of strings for simple single-column buttons
    
    Returns:
        dict: Inline keyboard markup for Telegram API
    """
    keyboard = []
    
    for row in buttons:
        # Normalize to a list of items in a row
        items = row if isinstance(row, list) else [row]
        keyboard_row = []
        for button in items:
            # Support dict with explicit url or callback_data
            if isinstance(button, dict):
                btn = {"text": button.get("text", "button")}
                if "url" in button:
                    btn["url"] = button["url"]
                elif "callback_data" in button:
                    btn["callback_data"] = button["callback_data"]
                else:
                    # Fallback: use text-derived callback
                    btn["callback_data"] = btn["text"].lower().replace(" ", "_")
                keyboard_row.append(btn)
            elif isinstance(button, tuple):
                text, meta = button
                if isinstance(meta, dict) and "url" in meta:
                    keyboard_row.append({"text": text, "url": meta["url"]})
                else:
                    callback_data = meta if isinstance(meta, str) else text.lower().replace(" ", "_")
                    keyboard_row.append({"text": text, "callback_data": callback_data})
            else:
                # Simple text button by default
                keyboard_row.append({"text": button, "callback_data": str(button).lower().replace(" ", "_")})
        keyboard.append(keyboard_row)
    
    return {"inline_keyboard": keyboard}

def send_compact_help_card(chat_id: str):
    """
    Send a compact help card highlighting common next actions and capabilities.
    """
    msg = (
        "**Quick Tips**\n\n"
        "You can:\n"
        "• Chat with your agent\n"
        "• Send images for analysis\n"
        "• Send voice notes for transcription\n"
        "• Switch agents with `/agents`\n"
        "• Manage tools with `/tool`\n"
        "• Open the web interface with `/ade`\n"
        "• Manage shortcuts with `/shortcut`\n"
    )
    send_telegram_message(chat_id, msg)

# ------------------ Twilio: SMS & WhatsApp endpoints ------------------

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),  # still needed for shared encryption key fallback
        modal.Secret.from_name("twilio"),
        modal.Secret.from_name("letta-oauth"),
    ],
    volumes={"/data": volume},
    scaledown_window=SCALEDOWN_WINDOW,
)
@modal.fastapi_endpoint(method="POST")
async def twilio_webhook(request: Request):
    """
    Twilio webhook for inbound SMS/WhatsApp. Quick ACK, with background processing.
    """
    # Parse form payload
    form = await request.form()
    data = {k: v for k, v in form.items()}

    # Correlation id for logs
    try:
        import uuid
        corr_id = uuid.uuid4().hex[:8]
    except Exception:
        corr_id = "unknown"

    # Optional signature validation
    if not validate_twilio_signature(request, data):
        print(f"[Twilio][{corr_id}] Invalid signature. Headers: X-Twilio-Signature={request.headers.get('X-Twilio-Signature','')}")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Twilio signature")

    from_num = data.get("From", "")
    to_num = data.get("To", "")
    body = (data.get("Body") or "").strip()

    print(f"[Twilio][{corr_id}] Inbound message From={from_num} To={to_num} BodyLen={len(body)} NumMedia={data.get('NumMedia','0')} BodySample={body[:120]}")

    # Identify chat and user (separate per-sender to isolate credentials)
    chat_id = f"twilio:{from_num}:{to_num}"
    user_id = f"twilio:{from_num}"

    # Basic command handling
    try:
        # Help
        if body.lower().startswith("/help"):
            print(f"[Twilio][{corr_id}] Command: /help")
            help_msg = (
                "Letta SMS/WhatsApp\n\n"
                "Commands:\n"
                "/login – Sign in with Letta account\n"
                "/login <api_key> – Authenticate with API key\n"
                "/status – Check status\n"
                "/agents – List your agents\n"
                "/agent <id> – Select agent\n"
                "/logout – Remove credentials\n\n"
                "Then send messages normally to chat with your agent."
            )
            send_twilio_message(from_num, help_msg, from_hint=to_num)
            # Return an empty TwiML to avoid duplicate echo
            print(f"[Twilio][{corr_id}] Sent help message")
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Login
        if body.lower().startswith("/login"):
            print(f"[Twilio][{corr_id}] Command: /login")
            parts = body.split()

            # Check if user provided an API key (legacy flow)
            if len(parts) >= 2 and parts[1].startswith("sk-"):
                api_key = parts[1]
                api_url = os.environ.get("LETTA_API_URL", "https://api.letta.com")

                # Validate key
                ok, msg, default_proj = validate_letta_api_key(api_key, api_url)
                if not ok:
                    print(f"[Twilio][{corr_id}] Login failed: {msg}")
                    send_twilio_message(from_num, f"Login failed: {msg}", from_hint=to_num)
                    return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

                store_user_credentials(user_id, api_key, api_url)

                # Optionally set default project if present
                if default_proj and default_proj[0]:
                    save_chat_project(chat_id, default_proj[0], default_proj[1], default_proj[2])

                print(f"[Twilio][{corr_id}] Login success; stored credentials for {user_id}")
                send_twilio_message(from_num, "Authenticated successfully. Use /agents to list agents, then /agent <id> to select.", from_hint=to_num)
                return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

            # OAuth flow - generate login link
            oauth_callback_url = os.environ.get("LETTA_OAUTH_CALLBACK_URL")
            if not oauth_callback_url:
                # Fallback message if OAuth not configured
                print(f"[Twilio][{corr_id}] OAuth not configured, falling back to API key instructions")
                send_twilio_message(from_num, "Usage: /login <api_key>\n\nGet your API key from app.letta.com", from_hint=to_num)
                return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

            # Generate PKCE pair and state
            state = generate_oauth_state()
            code_verifier, code_challenge = generate_pkce_pair()

            # Store pending OAuth state
            store_oauth_pending(
                state=state,
                user_id=user_id,
                platform="twilio",
                chat_id=chat_id,
                code_verifier=code_verifier,
                from_hint=to_num
            )

            # Build OAuth URL
            oauth_url = build_oauth_url(state, code_challenge, oauth_callback_url)

            print(f"[Twilio][{corr_id}] Generated OAuth URL for {user_id}")
            msg = (
                "Sign in with Letta:\n\n"
                f"{oauth_url}\n\n"
                "Tap the link to connect your Letta account. Link expires in 10 minutes.\n\n"
                "Or use: /login <api_key>"
            )
            send_twilio_message(from_num, msg, from_hint=to_num)
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Logout
        if body.lower().startswith("/logout"):
            print(f"[Twilio][{corr_id}] Command: /logout")
            # Revoke OAuth tokens if applicable
            revoke_oauth_token(user_id)
            delete_user_credentials(user_id)
            send_twilio_message(from_num, "Logged out and credentials removed.", from_hint=to_num)
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Status
        if body.lower().startswith("/status"):
            print(f"[Twilio][{corr_id}] Command: /status")
            creds = get_user_credentials(user_id)
            if not creds:
                send_twilio_message(from_num, "Not authenticated. Use /login to sign in.", from_hint=to_num)
            else:
                agent_info = get_chat_agent_info(chat_id)
                agent_line = f"Agent: {agent_info['agent_name']} ({agent_info['agent_id']})" if agent_info else "Agent: not selected"
                send_twilio_message(from_num, f"Status: authenticated\n{agent_line}", from_hint=to_num)
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Agents listing
        if body.lower().startswith("/agents"):
            print(f"[Twilio][{corr_id}] Command: /agents")
            creds = get_user_credentials(user_id)
            if not creds:
                send_twilio_message(from_num, "Authenticate first. Use /login to sign in.", from_hint=to_num)
                return FastAPIResponse(content="<Response></Response>", media_type="application/xml")
            client = get_letta_client(creds["api_key"], creds["api_url"], timeout=30.0)
            try:
                agents = client.agents.list()
            except Exception as e:
                print(f"[Twilio][{corr_id}] Error listing agents: {e}")
                send_twilio_message(from_num, f"Error fetching agents: {e}", from_hint=to_num)
                return FastAPIResponse(content="<Response></Response>", media_type="application/xml")
            if not agents:
                send_twilio_message(from_num, "No agents found. Create one in Letta, then try again.")
            else:
                lines = ["Your agents:"]
                for a in agents[:20]:
                    # client library returns SDK objects; access conservatively
                    aid = getattr(a, 'id', None) or (a.get('id') if isinstance(a, dict) else None)
                    aname = getattr(a, 'name', None) or (a.get('name') if isinstance(a, dict) else None)
                    lines.append(f"{aid} – {aname}")
                send_twilio_message(from_num, "\n".join(lines), from_hint=to_num)
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Select agent
        if body.lower().startswith("/agent "):
            print(f"[Twilio][{corr_id}] Command: /agent <id>")
            creds = get_user_credentials(user_id)
            if not creds:
                send_twilio_message(from_num, "Authenticate first. Use /login to sign in.", from_hint=to_num)
                return FastAPIResponse(content="<Response></Response>", media_type="application/xml")
            new_id = body.split(maxsplit=1)[1].strip()
            try:
                client = get_letta_client(creds["api_key"], creds["api_url"], timeout=30.0)
                agent = client.agents.retrieve(agent_id=new_id)
                save_chat_agent(chat_id, agent.id, agent.name)
                send_twilio_message(from_num, f"Selected agent: {agent.name}", from_hint=to_num)
            except Exception as e:
                print(f"[Twilio][{corr_id}] Error selecting agent: {e}")
                send_twilio_message(from_num, f"Failed to select agent: {e}", from_hint=to_num)
            return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

        # Non-command text → background processing
        # Acknowledge quickly (no user-visible echo)
        print(f"[Twilio][{corr_id}] Spawning background processor for chat_id={chat_id} user_id={user_id}")
        process_twilio_message_async.spawn({
            "From": from_num,
            "To": to_num,
            "Body": body,
            "NumMedia": data.get("NumMedia", "0"),
            "corr_id": corr_id,
        })
        return FastAPIResponse(content="<Response></Response>", media_type="application/xml")

    except Exception as e:
        print(f"[Twilio][{corr_id}] Error in Twilio webhook: {e}")
        # Don't error to Twilio; just ack
        return FastAPIResponse(content="<Response></Response>", media_type="application/xml")


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),
        modal.Secret.from_name("twilio"),
        modal.Secret.from_name("letta-oauth"),
        # Optional OpenAI for future media handling (not used now)
        # modal.Secret.from_name("openai"),
    ],
    volumes={"/data": volume},
    scaledown_window=SCALEDOWN_WINDOW,
)
def process_twilio_message_async(payload: dict):
    """
    Background processing for Twilio messages using Letta streaming.
    Sends assistant messages back via Twilio.
    """
    try:
        # Reload volume to get latest agent/credential data from other containers
        volume.reload()

        corr_id = payload.get("corr_id", "-")
        from_num = payload.get("From", "")
        to_num = payload.get("To", "")
        body = (payload.get("Body") or "").strip()
        chat_id = f"twilio:{from_num}:{to_num}"
        user_id = f"twilio:{from_num}"

        print(f"[Twilio][{corr_id}] Background start chat_id={chat_id} user_id={user_id} body_len={len(body)}")

        # User must be authenticated
        credentials = get_user_credentials(user_id)
        if not credentials:
            print(f"[Twilio][{corr_id}] No credentials for user; prompting login")
            send_twilio_message(from_num, "Authenticate first. Use /login to sign in.", from_hint=to_num)
            return

        # Agent must be selected
        agent_info = get_chat_agent_info(chat_id)
        if not agent_info:
            print(f"[Twilio][{corr_id}] No agent configured for chat; prompting selection")
            send_twilio_message(from_num, "No agent selected. Use /agents then /agent <id> to choose.", from_hint=to_num)
            return

        agent_id = agent_info["agent_id"]
        agent_name = agent_info.get("agent_name", "Agent")

        # Prepare content (text-only for now)
        context_message = (
            f"[Message from {'WhatsApp' if is_whatsapp_sender(from_num) else 'SMS'} user {from_num}]\n\n"
            f"{body if body else '(no text)'}"
        )
        content_parts = [{"type": "text", "text": context_message}]

        # Initialize client
        client = get_letta_client(credentials["api_key"], credentials["api_url"], timeout=60.0)

        # Stream responses and forward assistant messages
        response_stream = client.agents.messages.create_stream(
            agent_id=agent_id,
            messages=[{"role": "user", "content": content_parts}],
            include_pings=True,
            request_options={'timeout_in_seconds': 60}
        )

        print(f"[Twilio][{corr_id}] Streaming started for agent_id={agent_id}")
        for event in response_stream:
            try:
                if hasattr(event, 'message_type') and event.message_type == "assistant_message":
                    content = getattr(event, 'content', '')
                    if content and content.strip():
                        print(f"[Twilio][{corr_id}] Forwarding assistant message len={len(content)}")
                        # For SMS/WhatsApp/RCS, send plain text; Twilio handles segmentation
                        send_twilio_message(from_num, f"({agent_name} says)\n\n{content}", from_hint=to_num)
            except Exception as e:
                print(f"[Twilio][{corr_id}] Error handling stream event: {e}")
                continue

    except Exception as e:
        print(f"[Twilio][{corr_id}] Error in Twilio background processing: {e}")
        try:
            if payload.get("From"):
                send_twilio_message(payload["From"], f"Error: {e}", from_hint=payload.get("To"))
        except Exception:
            pass

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-bot"),
        modal.Secret.from_name("twilio"),
        modal.Secret.from_name("letta-oauth"),
    ],
    volumes={"/data": volume},
    scaledown_window=SCALEDOWN_WINDOW,
)
@modal.fastapi_endpoint(method="GET")
async def oauth_callback(request: Request):
    """
    OAuth callback handler - receives authorization code from Letta after user authorization.
    """
    from fastapi.responses import HTMLResponse

    # Reload volume to get latest OAuth state from other containers
    volume.reload()

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description", "")

    # Handle OAuth errors
    if error:
        error_html = f"""
        <html>
        <head><title>Authorization Failed</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Authorization Failed</h1>
            <p>{error}: {error_description}</p>
            <p>Please return to your messaging app and try again.</p>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=400)

    if not code or not state:
        return HTMLResponse(
            content="<html><body><h1>Invalid Request</h1><p>Missing code or state parameter.</p></body></html>",
            status_code=400
        )

    # Look up pending OAuth request
    pending = get_and_delete_oauth_pending(state)
    if not pending:
        return HTMLResponse(
            content="""
            <html>
            <head><title>Session Expired</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>Session Expired</h1>
                <p>Your login session has expired. Please return to your messaging app and try /login again.</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Use the configured callback URL to ensure exact match with authorization request
    redirect_uri = os.environ.get("LETTA_OAUTH_CALLBACK_URL")
    if not redirect_uri:
        # Fallback to reconstructing from request (may have mismatches)
        redirect_uri = str(request.url).split("?")[0]

    # Exchange code for tokens
    tokens = exchange_oauth_code(code, pending["code_verifier"], redirect_uri)

    if "error" in tokens:
        error_msg = tokens.get("error_description", tokens["error"])
        return HTMLResponse(
            content=f"""
            <html>
            <head><title>Authentication Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1>Authentication Failed</h1>
                <p>{error_msg}</p>
                <p>Please return to your messaging app and try again.</p>
            </body>
            </html>
            """,
            status_code=400
        )

    # Store OAuth credentials
    api_url = os.environ.get("LETTA_API_URL", "https://api.letta.com")
    store_oauth_credentials(pending["user_id"], tokens, api_url)

    # Send confirmation message to user
    platform = pending.get("platform", "")
    chat_id = pending.get("chat_id", "")
    user_id = pending.get("user_id", "")

    if platform == "twilio":
        # Extract phone number from user_id (format: "twilio:whatsapp:+1234567890" or "twilio:+1234567890")
        phone = user_id.replace("twilio:", "", 1)
        from_hint = pending.get("from_hint")
        try:
            send_twilio_message(
                phone,
                "Successfully connected to Letta! Use /agents to see your agents, then /agent <id> to select one.",
                from_hint=from_hint
            )
        except Exception as e:
            print(f"Failed to send Twilio confirmation: {e}")
    elif platform == "telegram":
        try:
            send_telegram_message(
                chat_id,
                "(connected to letta)\n\nuse /agents to see your agents"
            )
        except Exception as e:
            print(f"Failed to send Telegram confirmation: {e}")

    # Return success page
    return HTMLResponse(
        content="""
        <html>
        <head>
            <title>Connected!</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background-color: #f5f5f5;
                }
                .container {
                    background: white;
                    border-radius: 12px;
                    padding: 40px;
                    max-width: 400px;
                    margin: 0 auto;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                h1 { color: #22c55e; margin-bottom: 16px; }
                p { color: #666; line-height: 1.6; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Successfully Connected!</h1>
                <p>Your Letta account is now linked to your messaging app.</p>
                <p>You can close this window and return to your conversation.</p>
            </div>
        </body>
        </html>
        """
    )

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
