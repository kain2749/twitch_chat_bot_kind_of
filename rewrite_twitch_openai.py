#!/usr/bin/env python

import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
CONTEXT_PATH = Path("runtime/recent_chat.json")
STYLE_PATH = Path("prompts/kain_style.txt")

MAX_CHAT_MESSAGES = 25
MAX_OUTPUT_TOKENS = 120

client = OpenAI()


DEFAULT_STYLE = """
You are rewriting a Twitch chat draft for the user.

Core job:
- Preserve the user's meaning.
- Preserve the user's attitude.
- Preserve the user's style of typing.
- Fix obvious typos.
- Lightly fix grammar only when it makes the message clearer.
- Do not "professionalize" the message.
- Do not sanitize it into corporate/customer-support voice.
- Do not add new claims.
- Do not add context the user did not provide.
- Do not change capitalization style unless it is clearly an accidental typo.
- Do not add formal punctuation.
- Do not remove casual punctuation unless it is clearly accidental.
- Do not use em dashes.
- Do not use hashtags.
- Do not make it sound like an AI wrote it.
- Do not escalate insults, harassment, threats, or moderation evasion.
- Keep it under 450 characters.
- Return only the rewritten Twitch message. No quotes. No explanation.

Style target:
Blunt, casual, dry, slightly tired, technically literate, and conversational.
The user often writes like they are talking to another person in real time, not composing a post.
"""


def load_style():
    if STYLE_PATH.exists():
        custom = STYLE_PATH.read_text(encoding="utf-8").strip()
        if custom:
            return DEFAULT_STYLE.strip() + "\n\nAdditional local style notes/examples:\n" + custom

    return DEFAULT_STYLE.strip()


def load_recent_chat(limit=MAX_CHAT_MESSAGES):
    if not CONTEXT_PATH.exists():
        return []

    try:
        data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return data[-limit:]


def format_chat_context(messages):
    if not messages:
        return "No recent chat context available."

    lines = []

    for item in messages:
        user = str(item.get("user", "unknown")).strip()
        message = str(item.get("message", "")).strip()

        if not message:
            continue

        # Keep context small. Twitch chat is a trash fire; do not feed the whole landfill.
        message = message.replace("\n", " ")
        lines.append(f"{user}: {message}")

    return "\n".join(lines) if lines else "No recent chat context available."


def clean_model_output(text):
    text = text.strip()

    # Strip common wrapper mistakes.
    text = re.sub(r"^```(?:text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Strip matching quotes only if the model wrapped the whole thing.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()

    return text


def rewrite_message(draft):
    chat_context = format_chat_context(load_recent_chat())
    style = load_style()

    user_input = f"""
Recent Twitch chat context:
{chat_context}

User's raw draft:
{draft}

Rewrite the raw draft for Twitch chat.
"""

    response = client.responses.create(
        model=MODEL,
        instructions=style,
        input=user_input,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    return clean_model_output(response.output_text)


def main():
    if len(sys.argv) > 1:
        draft = " ".join(sys.argv[1:]).strip()
    else:
        draft = input("raw draft> ").strip()

    if not draft:
        print("[blocked] empty draft")
        return

    rewritten = rewrite_message(draft)

    print()
    print("rewritten:")
    print(rewritten)


if __name__ == "__main__":
    main()
