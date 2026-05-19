# twitch_chat_bot_kind_of

A tiny Twitch chat gremlin that reads chat, lets me type what I was already going to say, optionally runs it through an LLM to preserve my style, then sends it only after I approve it.

Basically: accused of being an LLM bot, became an LLM bot out of spite.

## What it does

- Reads Twitch chat from a target channel
- Stores recent chat context in `runtime/recent_chat.json`
- Lets me draft a message locally
- Sends the draft/context to OpenAI for a light rewrite
- Preserves my meaning and typing style
- Requires manual approval before anything goes to Twitch

No autonomous posting. No spam cannon. No haunted autocomplete with root privileges.

## Current status

Prototype.

Working pieces:

- Twitch IRC read-only chat ingestion
- Send-only Twitch IRC message script
- OpenAI rewrite script
- Human approval gate before sending

## Requirements

- Python 3
- Twitch OAuth token with chat permissions
- OpenAI API key
- `openai` Python package

```bash
pip install openai
```

## Environment variables

Set these outside the repo:

```bash
export TWITCH_USERNAME="your_twitch_username"
export TWITCH_OAUTH_TOKEN="oauth:your_twitch_access_token"
export TWITCH_CHANNEL="piratesoftware"
export OPENAI_API_KEY="your_openai_api_key"
export OPENAI_MODEL="gpt-5.5"
```

Do not commit tokens. Do not paste tokens into chat. Do not become content.

## Usage

Terminal 1: read chat and write recent context.

```bash
python twitch_read_chat.py
```

Terminal 2: draft, rewrite, approve, send.

```bash
python twitch_llm_send.py
```

## Safety rails

- Slash commands are blocked by default
- Messages are length-checked before sending
- Sending requires explicit confirmation
- Runtime chat dumps are ignored by git
- Secrets are expected to live outside the repo

## Why

Because Twitch chat joked that I was an LLM bot.

They were wrong at the time.
