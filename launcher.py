"""Windows entry point for the packaged PDF Reader application."""

import socket
import threading
import time
import webbrowser

import uvicorn

import server

HOST = "127.0.0.1"
PORT = 8123
URL = f"http://{HOST}:{PORT}"


def _server_is_running() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, PORT)) == 0


def _open_browser_when_ready() -> None:
    for _ in range(100):
        if _server_is_running():
            webbrowser.open(URL)
            return
        time.sleep(0.1)


def main() -> None:
    if _server_is_running():
        webbrowser.open(URL)
        return

    server.auto_import_default_books()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    # A --windowed PyInstaller build has no stdout/stderr; Uvicorn's default
    # formatter calls isatty() on those streams and crashes during startup.
    uvicorn.run(server.app, host=HOST, port=PORT, log_config=None)


if __name__ == "__main__":
    main()
