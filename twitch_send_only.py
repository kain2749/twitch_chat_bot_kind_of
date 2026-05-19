#!/usr/bin/env python

import os
import ssl
import socket
import time

SERVER = "irc.chat.twitch.tv"
PORT = 6697

USERNAME = os.environ["TWITCH_USERNAME"].lower()
TOKEN = os.environ["TWITCH_OAUTH_TOKEN"]
CHANNEL = os.environ.get("TWITCH_CHANNEL", "piratesoftware").lower().lstrip("#")

if not TOKEN.startswith("oauth:"):
    TOKEN = f"oauth:{TOKEN}"

last_sent_at = 0.0


def send_line(sock, line):
    sock.sendall((line + "\r\n").encode("utf-8"))


def send_chat(sock, message):
    global last_sent_at

    message = message.strip()

    if not message:
        return

    if message == "/quit":
        raise KeyboardInterrupt

    if message.startswith("/"):
        print("[blocked] slash commands disabled")
        return

    if len(message) > 450:
        print("[blocked] too long; keep it under 450 chars")
        return

    now = time.time()
    wait = 1.1 - (now - last_sent_at)
    if wait > 0:
        time.sleep(wait)

    send_line(sock, f"PRIVMSG #{CHANNEL} :{message}")
    last_sent_at = time.time()

    print(f"[sent] {message}")


def main():
    raw_sock = socket.create_connection((SERVER, PORT))
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=SERVER)

    send_line(sock, f"PASS {TOKEN}")
    send_line(sock, f"NICK {USERNAME}")
    send_line(sock, f"JOIN #{CHANNEL}")

    print(f"send-only connected to #{CHANNEL} as {USERNAME}")
    print("type message + Enter to send")
    print("type /quit to exit")

    try:
        while True:
            message = input("> ")
            send_chat(sock, message)
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
