#!/usr/bin/env python

import os
import re
import ssl
import socket
import json
from collections import deque
from datetime import datetime
from pathlib import Path

CONTEXT_PATH = Path("runtime/recent_chat.json")
CONTEXT_PATH.parent.mkdir(exist_ok=True)

SERVER = "irc.chat.twitch.tv"
PORT = 6697

USERNAME = os.environ["TWITCH_USERNAME"].lower()
TOKEN = os.environ["TWITCH_OAUTH_TOKEN"]
CHANNEL = os.environ.get("TWITCH_CHANNEL", "piratesoftware").lower().lstrip("#")

if not TOKEN.startswith("oauth:"):
    TOKEN = f"oauth:{TOKEN}"

recent_chat = deque(maxlen=100)

privmsg_re = re.compile(
    r"^(?:@(?P<tags>[^ ]+) )?:(?P<user>[^!]+)![^ ]+ PRIVMSG #(?P<channel>[^ ]+) :(?P<message>.*)$"
)

def send(sock, line):
    sock.sendall((line + "\r\n").encode("utf-8"))

def parse_tags(raw_tags):
    tags = {}
    if not raw_tags:
        return tags

    for item in raw_tags.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            tags[key] = value
    return tags

def main():
    raw_sock = socket.create_connection((SERVER, PORT))
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=SERVER)

    send(sock, f"PASS {TOKEN}")
    send(sock, f"NICK {USERNAME}")

    # Tags gives message IDs, display names, badges, timestamps, etc.
    send(sock, "CAP REQ :twitch.tv/tags twitch.tv/commands")

    send(sock, f"JOIN #{CHANNEL}")

    print(f"connected to #{CHANNEL} as {USERNAME}")

    buffer = ""

    while True:
        data = sock.recv(4096).decode("utf-8", errors="replace")
        if not data:
            print("disconnected")
            break

        buffer += data

        while "\r\n" in buffer:
            line, buffer = buffer.split("\r\n", 1)

            if line.startswith("PING"):
                send(sock, "PONG :tmi.twitch.tv")
                continue

            match = privmsg_re.match(line)
            if not match:
                continue

            tags = parse_tags(match.group("tags"))
            user = tags.get("display-name") or match.group("user")
            message = match.group("message")
            msg_id = tags.get("id")
            timestamp = datetime.now().strftime("%H:%M:%S")

            item = {
                "time": timestamp,
                "user": user,
                "message": message,
                "id": msg_id,
            }

            recent_chat.append(item)

            tmp_path = CONTEXT_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(
            json.dumps(list(recent_chat), indent=2, ensure_ascii=False),
            encoding="utf-8",
            )
            tmp_path.replace(CONTEXT_PATH)

            print(f"[{timestamp}] {user}: {message}")

if __name__ == "__main__":
    main()
