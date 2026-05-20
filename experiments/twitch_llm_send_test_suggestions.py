#!/usr/bin/env python

import json
import os
import re
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

SERVER = "irc.chat.twitch.tv"
PORT = 6697

USERNAME = os.environ["TWITCH_USERNAME"].lower()
TOKEN = os.environ["TWITCH_OAUTH_TOKEN"]
CHANNEL = os.environ.get("TWITCH_CHANNEL", "piratesoftware").lower().lstrip("#")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.5")
AUTO_SEND = os.environ.get("TWITCH_AUTO_SEND", "").lower() in {"1", "true", "yes", "y"}

CONTEXT_PATH = Path("runtime/recent_chat.json")
STYLE_PATH = Path("prompts/kain_style.txt")

MAX_CHAT_MESSAGES = 25
MAX_OUTPUT_TOKENS = 200
TOPIC_OUTPUT_TOKENS = 180
SUGGESTION_OUTPUT_TOKENS = 700
MAX_SUGGESTIONS = 8
MAX_TWITCH_CHARS = 450
SEND_THROTTLE_SECONDS = 1.1

if not TOKEN.startswith("oauth:"):
    TOKEN = f"oauth:{TOKEN}"

client = OpenAI()
send_lock = threading.Lock()
stop_reader = threading.Event()

DEFAULT_REWRITE_STYLE = """
You rewrite Twitch chat drafts for the user.

Hard rules:
- Preserve the user's meaning.
- Preserve the user's typing style.
- Preserve casual lowercase if the user wrote lowercase.
- Preserve punctuation style unless it is obviously accidental.
- Fix obvious typos.
- Lightly fix grammar only when it helps clarity.
- Do not professionalize the message.
- Do not make it sound like customer support, marketing, reddit debate club, or an AI assistant.
- Do not add new facts.
- Do not invent context.
- Do not add jokes the user did not imply.
- Do not over-polish.
- Do not use em dashes.
- Do not add hashtags.
- Do not escalate harassment, threats, slurs, or moderation evasion.
- Keep it under 450 characters.
- Return only the rewritten Twitch message. No quotes. No explanation.

Target style:
Blunt, casual, dry, technically literate, slightly tired, conversational.
The user writes like they are talking in real time, not composing a polished post.
"""

SUGGESTION_STYLE = """
You suggest possible Twitch chat messages for the user.

Rules:
- Read the recent Twitch chat context.
- Suggest things the user could plausibly say right now.
- Match the user's style: blunt, casual, dry, technically literate, slightly tired.
- Keep casual lowercase where natural.
- Do not sound like an AI assistant.
- Do not over-polish.
- Do not invent facts.
- Use general knowledge only for explaining concepts.
- Do not claim something is happening on stream unless recent chat clearly supports it.
- Do not escalate harassment, threats, slurs, or moderation evasion.
- Do not suggest slash commands.
- Keep every suggestion under 300 characters.
- Return only a JSON array of strings.
"""

TOPIC_STYLE = """
You write one Twitch chat message for the user.

Rules:
- The user provides the topic.
- Write one short Twitch chat message about that topic.
- Match the user's style: blunt, casual, dry, technically literate, slightly tired.
- Preserve casual lowercase where natural.
- Do not sound like an AI assistant.
- Do not over-polish.
- Do not add formal punctuation unless needed.
- Do not use em dashes.
- Do not use hashtags.
- Do not invent facts.
- Use general knowledge only for explaining concepts.
- Use recent chat only as ambient context.
- Do not claim something is happening on stream unless the topic says it or recent chat clearly supports it.
- Do not escalate harassment, threats, slurs, or moderation evasion.
- Keep it under 300 characters.
- Return only the Twitch message. No quotes. No explanation.
"""


def send_line(sock: ssl.SSLSocket, line: str) -> None:
    with send_lock:
        sock.sendall((line + "\r\n").encode("utf-8"))


def connect_twitch() -> ssl.SSLSocket:
    raw_sock = socket.create_connection((SERVER, PORT), timeout=20)
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=SERVER)
    sock.settimeout(None)

    send_line(sock, f"PASS {TOKEN}")
    send_line(sock, f"NICK {USERNAME}")
    send_line(sock, "CAP REQ :twitch.tv/commands")
    send_line(sock, f"JOIN #{CHANNEL}")

    return sock


def irc_background_reader(sock: ssl.SSLSocket) -> None:
    """
    Keep the Twitch IRC connection alive.

    This intentionally does not print normal chat. It only handles PING and prints
    server NOTICE lines, which are useful when a message silently fails because of
    auth, permissions, rate limits, slow mode, etc.
    """
    buffer = ""

    while not stop_reader.is_set():
        try:
            data = sock.recv(4096).decode("utf-8", errors="replace")
        except OSError:
            break

        if not data:
            print("[irc] disconnected")
            break

        buffer += data

        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)

            if not line:
                continue

            if line.startswith("PING"):
                try:
                    send_line(sock, "PONG :tmi.twitch.tv")
                except OSError:
                    return
                continue

            if " NOTICE " in line:
                print(f"[twitch notice] {line}")
                continue

            if " USERNOTICE " in line:
                print(f"[twitch usernotice] {line}")
                continue


def load_style_notes() -> str:
    if STYLE_PATH.exists():
        return STYLE_PATH.read_text(encoding="utf-8").strip()
    return ""


def with_style_notes(base: str) -> str:
    notes = load_style_notes()
    if notes:
        return base.strip() + "\n\nLocal style notes/examples:\n" + notes
    return base.strip()


def load_recent_chat(limit: int = MAX_CHAT_MESSAGES) -> list[dict]:
    if not CONTEXT_PATH.exists():
        return []

    try:
        data = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    return data[-limit:]


def format_chat_context(messages: list[dict]) -> str:
    if not messages:
        return "No recent chat context available."

    lines = []

    for item in messages:
        user = str(item.get("user", "unknown")).strip()
        message = str(item.get("message", "")).strip().replace("\n", " ")

        if user and message:
            lines.append(f"{user}: {message}")

    return "\n".join(lines) if lines else "No recent chat context available."


def clean_model_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json|text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()

    return text


def validate_message(message: str) -> tuple[bool, str]:
    message = message.strip()

    if not message:
        return False, "empty message"

    if message.startswith("/"):
        return False, "slash commands are blocked"

    if len(message) > MAX_TWITCH_CHARS:
        return False, f"too long: {len(message)} chars"

    return True, ""


def rewrite_message(draft: str) -> str:
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
        instructions=with_style_notes(DEFAULT_REWRITE_STYLE),
        input=prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    return clean_model_output(response.output_text)


def generate_topic_comment(topic: str) -> Optional[str]:
    topic = topic.strip()

    if not topic:
        return None

    chat_context = format_chat_context(load_recent_chat())

    prompt = f"""
Recent Twitch chat context:
{chat_context}

User topic:
{topic}

Write one Twitch chat message about the user topic.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=with_style_notes(TOPIC_STYLE),
        input=prompt,
        max_output_tokens=TOPIC_OUTPUT_TOKENS,
    )

    return clean_model_output(response.output_text)


def suggest_messages() -> list[str]:
    chat_context = format_chat_context(load_recent_chat())

    prompt = f"""
Recent Twitch chat context:
{chat_context}

Return {MAX_SUGGESTIONS} possible Twitch chat messages.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=with_style_notes(SUGGESTION_STYLE),
        input=prompt,
        max_output_tokens=SUGGESTION_OUTPUT_TOKENS,
    )

    text = clean_model_output(response.output_text)

    try:
        suggestions = json.loads(text)
    except json.JSONDecodeError:
        # Fallback if the model returns bullets instead of JSON.
        suggestions = []
        for line in text.splitlines():
            line = line.strip()
            line = re.sub(r"^[-*\d.)\s]+", "", line).strip()
            if line:
                suggestions.append(line)

    cleaned = []

    for suggestion in suggestions:
        suggestion = str(suggestion).strip()

        if not suggestion:
            continue

        ok, _reason = validate_message(suggestion)
        if ok:
            cleaned.append(suggestion)

    return cleaned[:MAX_SUGGESTIONS]


def pick_suggestion() -> Optional[str]:
    while True:
        try:
            suggestions = suggest_messages()
        except Exception as exc:
            print(f"[openai suggestion error] {exc}")
            return None

        if not suggestions:
            print("[no usable suggestions]")
            return None

        print("\nsuggestions:")

        for index, suggestion in enumerate(suggestions, start=1):
            print(f"{index}. {suggestion}")

        choice = input("\npick 1-8 / [r] regenerate / [n] cancel > ").strip().lower()

        if choice == "n":
            print("[cancelled]")
            return None

        if choice == "r":
            continue

        if choice.isdigit():
            index = int(choice)

            if 1 <= index <= len(suggestions):
                return suggestions[index - 1]

        print("[pick a number, r, or n]")


def send_chat(sock: ssl.SSLSocket, message: str) -> None:
    send_line(sock, f"PRIVMSG #{CHANNEL} :{message}")


def maybe_throttle(last_sent_at: float) -> float:
    now = time.time()
    wait = SEND_THROTTLE_SECONDS - (now - last_sent_at)

    if wait > 0:
        time.sleep(wait)

    return time.time()


def confirm_or_send(sock: ssl.SSLSocket, message: str, last_sent_at: float) -> tuple[bool, float]:
    ok, reason = validate_message(message)
    if not ok:
        print(f"[blocked] {reason}")
        print(f"message was: {message}")
        return False, last_sent_at

    if AUTO_SEND:
        last_sent_at = maybe_throttle(last_sent_at)
        send_chat(sock, message)
        print(f"[auto-sent] {message}")
        return True, last_sent_at

    print("\nmessage:")
    print(message)

    while True:
        choice = input("\n[y] send / [e] edit / [r] rewrite / [n] cancel > ").strip().lower()

        if choice == "y":
            last_sent_at = maybe_throttle(last_sent_at)
            send_chat(sock, message)
            print(f"[sent] {message}")
            return True, last_sent_at

        if choice == "e":
            edited = input("edit> ").strip()
            ok, reason = validate_message(edited)

            if not ok:
                print(f"[blocked edit] {reason}")
                continue

            last_sent_at = maybe_throttle(last_sent_at)
            send_chat(sock, edited)
            print(f"[sent edited] {edited}")
            return True, last_sent_at

        if choice == "r":
            return False, last_sent_at

        if choice == "n":
            print("[cancelled]")
            return True, last_sent_at

        print("[pick y/e/r/n]")


def main() -> None:
    print(f"LLM Twitch sender target: #{CHANNEL}")
    print(f"model: {OPENAI_MODEL}")

    if AUTO_SEND:
        print("mode: no-review. draft/topic/suggestion -> final message -> send")
    else:
        print("mode: review. draft/topic/suggestion -> final message -> approve/edit/cancel")

    print("local commands:")
    print("  s              suggestions from recent chat")
    print("  t <topic>      generate one comment about topic")
    print("  t              prompt for topic")
    print("  /quit          exit")
    print("slash commands are blocked before sending")

    sock = connect_twitch()
    reader = threading.Thread(target=irc_background_reader, args=(sock,), daemon=True)
    reader.start()

    last_sent_at = 0.0

    try:
        while True:
            raw = input("\nraw> ").strip()

            if not raw:
                continue

            if raw == "/quit":
                break

            final_message: Optional[str] = None

            if raw == "s":
                picked = pick_suggestion()
                if not picked:
                    continue
                final_message = picked
                print(f"\nselected:\n{final_message}")

            elif raw == "t":
                topic = input("topic> ").strip()
                if not topic:
                    print("[cancelled]")
                    continue

                try:
                    final_message = generate_topic_comment(topic)
                except Exception as exc:
                    print(f"[openai topic error] {exc}")
                    continue

                if not final_message:
                    print("[no usable topic comment]")
                    continue

                print(f"\ntopic comment:\n{final_message}")

            elif raw.startswith("t "):
                topic = raw[2:].strip()
                if not topic:
                    print("[missing topic]")
                    continue

                try:
                    final_message = generate_topic_comment(topic)
                except Exception as exc:
                    print(f"[openai topic error] {exc}")
                    continue

                if not final_message:
                    print("[no usable topic comment]")
                    continue

                print(f"\ntopic comment:\n{final_message}")

            else:
                ok, reason = validate_message(raw)
                if not ok:
                    print(f"[blocked raw] {reason}")
                    continue

                current_draft = raw

                # Retry loop for manual "r" rewrite.
                while True:
                    try:
                        final_message = rewrite_message(current_draft)
                    except Exception as exc:
                        print(f"[openai rewrite error] {exc}")
                        final_message = None
                        break

                    sent_or_done, last_sent_at = confirm_or_send(sock, final_message, last_sent_at)

                    if sent_or_done:
                        final_message = None
                        break

                    # User picked [r] rewrite. Re-chew the previous output.
                    current_draft = final_message

                continue

            # Topic and suggestion mode land here. They do NOT get rewritten again.
            sent_or_done, last_sent_at = confirm_or_send(sock, final_message, last_sent_at)

            if not sent_or_done:
                # User picked [r] rewrite for a generated suggestion/topic.
                current_draft = final_message

                while True:
                    try:
                        rewritten = rewrite_message(current_draft)
                    except Exception as exc:
                        print(f"[openai rewrite error] {exc}")
                        break

                    sent_or_done, last_sent_at = confirm_or_send(sock, rewritten, last_sent_at)

                    if sent_or_done:
                        break

                    current_draft = rewritten

    except KeyboardInterrupt:
        print("\nclosing")
    finally:
        stop_reader.set()

        try:
            send_line(sock, f"PART #{CHANNEL}")
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
