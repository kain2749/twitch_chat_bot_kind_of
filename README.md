# twitch_chat_bot_kind_of

A small local Twitch chat helper.

It reads recent chat, lets me write a draft, uses OpenAI to lightly rewrite the draft in my style, and then posts through Twitch IRC after the configured local flow.

The point is not autonomous posting. I still provide the intent. The script is just a local drafting layer.

## What it does

- Reads Twitch chat from a target channel
- Stores recent chat context in `runtime/recent_chat.json`
- Lets me write a raw draft locally
- Uses recent chat context while rewriting
- Preserves meaning, tone, casual punctuation, and capitalization style where possible
- Supports normal review mode
- Supports a faster no-review mode with `TWITCH_AUTO_SEND=1`
- Supports suggestion mode from the `raw>` prompt with `s`

## Current status

Prototype.

Current files:

- `twitch_read_chat.py` reads Twitch chat and writes recent context
- `twitch_llm_send.py` handles drafts, rewrites, suggestions, review, and posting
- `prompts/kain_style.txt` contains local style examples

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

Optional no-review mode:

```bash
export TWITCH_AUTO_SEND=1
```

Do not commit tokens, API keys, `.env` files, shell export scripts, runtime dumps, or anything else with secrets in it.

## Usage

Terminal 1: read Twitch chat and write recent context.

```bash
python twitch_read_chat.py
```

Terminal 2: draft, rewrite, review, and post.

```bash
python twitch_llm_send.py
```

Normal review flow:

```text
raw> this man built an entire moral philosophy around not reading the quest text

rewrite:
this man built an entire moral philosophy around not reading the quest text

[y] send / [e] edit / [r] retry / [n] cancel >
```

## Suggestion mode

At the `raw>` prompt, type:

```text
s
```

The script reads `runtime/recent_chat.json`, asks OpenAI for context-aware message suggestions in the configured style, and prints a numbered list.

Example:

```text
raw> s

suggestions:
1. wait, are we fixing the problem or creating a second, more annoying problem
2. this feels like infrastructure built specifically to lose an argument faster
3. i respect the commitment to making this more complicated than it needed to be

pick 1-8 / [r] regenerate / [n] cancel >
```

After selecting a suggestion, the normal configured flow continues.

## No-review mode

No-review mode skips the manual review prompt. You type the draft, the rewrite happens, and the script uses the result immediately.

```bash
TWITCH_AUTO_SEND=1 python twitch_llm_send.py
```

This is still not fully autonomous. The user still types the draft or selects a suggestion.

## Guard rails

Kept in both normal and no-review mode:

- Empty messages are blocked
- Slash commands are blocked by default
- Messages are length-checked
- Sends are throttled
- Runtime chat dumps are ignored by git
- Secrets are expected to live outside the repo

Skipped only in no-review mode:

- Manual review of the LLM output

## File layout

```text
.
├── twitch_read_chat.py       # reads Twitch chat and writes runtime/recent_chat.json
├── twitch_llm_send.py        # draft -> rewrite/suggestions -> review/post
├── prompts/
│   └── kain_style.txt        # local style notes/examples
├── runtime/
│   └── recent_chat.json      # generated live chat context, ignored by git
├── README.md
├── LICENSE
└── .gitignore
```

## Notes

This is a local personal tool. Keep secrets out of the repo, keep runtime files ignored, and assume anything posted to Twitch is public immediately.
