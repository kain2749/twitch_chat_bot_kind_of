#!/usr/bin/env python

import json
import os
import re
import socket
import ssl
import time
from pathlib import Path

from openai import OpenAI

SERVER = "irc.chat.twitch.tv"
PORT = 6697

USERNAME = os.environ["TWITCH_USERNAME"].lower()
TOKEN = os.environ["TWITCH_OAUTH_TOKEN"]
CHANNEL = os.environ.get("TWITCH_CHANNEL", "piratesoftware").lower().lstrip("#")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")

CONTEXT_PATH = Path("runtime/recent_chat.json")
STYLE_PATH = Path("prompts/kain_style.txt")

MAX_CHAT_MESSAGES = 25
MAX_OUTPUT_TOKENS = 200
MAX_TWITCH_CHARS = 450

if not TOKEN.startswith("oauth:"):
    TOKEN = f"oauth:{TOKEN}"

client = OpenAI()

DEFAULT_STYLE = """
You rewrite Twitch chat drafts for the user.

Hard rules:
- Preserve the user's meaning.
- Preserve the user's typing style.
- Preserve casual lowercase if the user wrote lowercase.
- Preserve punctuation style unless it is obviously accidental.
- Fix obvious typos.
- Lightly fix grammar only when it helps clarity.
- Do not professionalize the message.
- Do not make it sound like customer support, marketing, reddit-brained debate club, or an AI assistant.
- Do not add new facts.
- Do not invent context.
- Do not add jokes the user did not imply.
- Do not over-polish.
- Do not use em dashes.
- Do not add hashtags.
- Do not escalate harassment, threats, or moderation evasion.
- Keep it under 450 characters.
- Return only the rewritten Twitch message. No quotes. No explanation.

Target style:
Blunt, casual, dry, technically literate, slightly tired, conversational.
The user writes like they are talking in real time, not composing a polished post.
"""


def send_line(sock, line):
    sock.sendall((line + "\r\n").encode("utf-8"))


def connect_twitch():
    raw_sock = socket.create_connection((SERVER, PORT))
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=SERVER)

    send_line(sock, f"PASS {TOKEN}")
    send_line(sock, f"NICK {USERNAME}")
    send_line(sock, f"JOIN #{CHANNEL}")

    return sock


def load_style():
    if STYLE_PATH.exists():
        extra = STYLE_PATH.read_text(encoding="utf-8").strip()
        if extra:
            return DEFAULT_STYLE.strip() + "\n\nLocal style notes/examples:\n" + extra

    return DEFAULT_STYLE.strip()


def load_recent_chat():
    if not CONTEXT_PATH.exists():
        return []

    try:
        data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return data[-MAX_CHAT_MESSAGES:]


def format_chat_context(messages):
    if not messages:
        return "No recent chat context available."

    lines = []

    for item in messages:
        user = str(item.get("user", "unknown")).strip()
        message = str(item.get("message", "")).strip().replace("\n", " ")

        if message:
            lines.append(f"{user}: {message}")

    return "\n".join(lines) if lines else "No recent chat context available."


def clean_model_output(text):
    text = text.strip()

    text = re.sub(r"^```(?:text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()

    return text


def rewrite_message(draft):
    chat_context = format_chat_context(load_recent_chat())

    prompt = f"""
Recent Twitch chat context:
{chat_context}

User's raw draft:
{draft}

Rewrite the raw draft for Twitch chat.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=load_style(),
        input=prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    return clean_model_output(response.output_text)


def validate_message(message):
    message = message.strip()

    if not message:
        return False, "empty message"

    if message.startswith("/"):
        return False, "slash commands are blocked"

    if len(message) > MAX_TWITCH_CHARS:
        return False, f"too long: {len(message)} chars"

    return True, ""


def send_chat(sock, message):
    send_line(sock, f"PRIVMSG #{CHANNEL} :{message}")


def main():
    print(f"LLM Twitch sender connected target: #{CHANNEL}")
    print("type raw draft, review rewrite, then choose y/e/r/n")
    print("commands: /quit exits; slash commands are not sent")

    sock = connect_twitch()
    last_sent_at = 0.0

    try:
        while True:
            draft = input("\nraw> ").strip()

            if draft == "/quit":
                break

            ok, reason = validate_message(draft)
            if not ok:
                print(f"[blocked raw] {reason}")
                continue

            current_draft = draft

            while True:
                try:
                    rewritten = rewrite_message(current_draft)
                except Exception as exc:
                    print(f"[openai error] {exc}")
                    break

                ok, reason = validate_message(rewritten)
                if not ok:
                    print(f"[blocked rewrite] {reason}")
                    print(f"rewrite was: {rewritten}")
                    break

                print("\nrewrite:")
                print(rewritten)

                choice = input("\n[y] send / [e] edit / [r] retry / [n] cancel > ").strip().lower()

                if choice == "y":
                    now = time.time()
                    wait = 1.1 - (now - last_sent_at)

                    if wait > 0:
                        time.sleep(wait)

                    send_chat(sock, rewritten)
                    last_sent_at = time.time()
                    print(f"[sent] {rewritten}")
                    break

                if choice == "e":
                    edited = input("edit> ").strip()
                    ok, reason = validate_message(edited)

                    if not ok:
                        print(f"[blocked edit] {reason}")
                        continue

                    now = time.time()
                    wait = 1.1 - (now - last_sent_at)

                    if wait > 0:
                        time.sleep(wait)

                    send_chat(sock, edited)
                    last_sent_at = time.time()
                    print(f"[sent edited] {edited}")
                    break

                if choice == "r":
                    current_draft = rewritten
                    continue

                if choice == "n":
                    print("[cancelled]")
                    break

                print("[pick y/e/r/n, boss]")

    except KeyboardInterrupt:
        print("\nclosing")
    finally:
        try:
            send_line(sock, f"PART #{CHANNEL}")
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
