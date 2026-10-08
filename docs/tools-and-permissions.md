# Tools and permissions

The bot exposes listener-owned tools only when they are useful on the current route:

- `telegram_react(message_id, emoji)` accepts Telegram's supported reaction emoji.
- `telegram_send_file(path, caption?)` reads a normalized path under `/root/downloads` from the managed sandbox and sends a photo or document.
- `telegram_send_message(text)` is available in tool-mode open chats, where ordinary assistant text is not posted.

Every tool is scoped to the active chat and forum topic. Telegram bots cannot read arbitrary chat history, so there is no history tool. Set `ENABLE_TELEGRAM_TOOLS=false` to remove reaction and file tools. The send-message tool remains in tool mode because it is the only way for the agent to speak there.

`PERMISSION_MODE`, `ALLOWED_TOOLS`, and `TOOLSET_BASE` control the Agent SDK toolset. `APPROVAL_MODE` controls calls that still need a human decision:

- `deny`: deny them immediately.
- `admins`: configured Telegram admins may decide.
- `requester`: the requester or an admin may decide.
- `allow`: allow without a button.

Approval buttons are authorization prompts, not proof of authorization. The callback user is checked before state changes. Each request resolves once, and its keyboard is removed after approval, denial, timeout, cancellation, or shutdown.

A routing file can override policy by topic, chat, or private-chat user. More specific entries supply each field first. Use restrictive policies for open groups, and never expose a token or Telegram file URL to the agent sandbox.
