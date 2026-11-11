"""Tag System command-line client, installed as the `tag` command."""

import argparse
import ast
from contextlib import closing
import getpass
import json
import mimetypes
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit

VERSION = "1.1.1"
KEYRING_SERVICE = "tag-system"
CLIPBOARD_SETTLE_SECONDS = 0.5
CLIPBOARD_HISTORY_QUERY_SECONDS = 0.1
IMAGE_CLIPBOARD_HOLD_MS = 2000
IMAGE_CLIPBOARD_START_TIMEOUT_SECONDS = 5


def config_path():
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "tag-system" / "config.json"


def saved_server_url():
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))["server_url"]
    except FileNotFoundError:
        return ""
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Could not read {config_path()}: {exc}. Run: tag configure")


def server_url():
    url = saved_server_url()
    if not url:
        raise SystemExit("No server configured. Run: tag configure")
    return url


def normalize_server_url(url):
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        raise SystemExit("Enter the server address as http://HOST:PORT, for example http://192.168.1.50:8710")
    return url


def get_api_key(url):
    import keyring
    from keyring.errors import KeyringError

    # The keyring entry is keyed by server URL, so each server keeps its own key.
    try:
        api_key = keyring.get_password(KEYRING_SERVICE, url)
    except KeyringError as exc:
        raise SystemExit(f"Could not read API key from system keyring: {exc}")

    if not api_key:
        raise SystemExit("No API key configured. Run: tag configure")

    return api_key


def headers(url):
    return {"x-api-key": get_api_key(url)}


def configure(args):
    import keyring
    from keyring.errors import KeyringError

    current = saved_server_url()
    prompt = f"Server URL [{current}]: " if current else "Server URL (http://HOST:PORT): "
    url = normalize_server_url(input(prompt).strip() or current)
    api_key = getpass.getpass("API key (leave empty to keep the saved key): ").strip()

    try:
        if api_key:
            keyring.set_password(KEYRING_SERVICE, url, api_key)
        elif not keyring.get_password(KEYRING_SERVICE, url):
            raise SystemExit(f"No API key is saved for {url}; run tag configure again and enter it.")
    except KeyringError as exc:
        raise SystemExit(f"Could not access the system keyring: {exc}")

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"server_url": url}) + "\n", encoding="utf-8")
    print(f"Server set to {url}")
    print("API key saved to system keyring" if api_key else "Kept the saved API key")


def add(args):
    import requests

    base_url = server_url()
    data = []
    files = []
    opened_files = []

    for text in args.text or []:
        data.append(("text", text))

    for url in args.url or []:
        data.append(("url", url))

    try:
        for file_path in args.file or []:
            path = os.path.expanduser(file_path)
            if not os.path.isfile(path):
                print("File does not exist:", path)
                return

            handle = open(path, "rb")
            opened_files.append(handle)
            files.append(("file", (os.path.basename(path), handle)))

        res = requests.post(
            f"{base_url}/tags/{args.name}/add",
            data=data,
            files=files,
            headers=headers(base_url),
        )
        res.raise_for_status()
        print("Saved")
    finally:
        for handle in opened_files:
            handle.close()


def show(args):
    import requests

    base_url = server_url()
    res = requests.get(f"{base_url}/tags/{args.name}", headers=headers(base_url))
    if res.status_code != 200:
        print(res.json().get("detail"))
        return
    tag = res.json()
    if not tag["items"]:
        print("No items in tag")
        return
    for i, item in enumerate(tag["items"]):
        t = item["type"]
        if t in ["text", "url"]:
            print(f"[{i}] {t.upper()}: {item['content']}")
        elif t == "file":
            print(f"[{i}] FILE: {item['filename']}")


def show_all(args):
    import requests

    base_url = server_url()
    auth_headers = headers(base_url)
    res = requests.get(f"{base_url}/tags", headers=auth_headers)
    tags = res.json()

    if not tags:
        print("No tags found")
        return

    for name in tags:
        print(f"\n=== {name} ===")
        res = requests.get(f"{base_url}/tags/{name}", headers=auth_headers)
        if res.status_code != 200:
            print("Error:", res.json().get("detail"))
            continue

        tag = res.json()
        if not tag["items"]:
            print("No items")
            continue

        for i, item in enumerate(tag["items"]):
            t = item["type"]
            if t in ["text", "url"]:
                print(f"[{i}] {t.upper()}: {item['content']}")
            elif t == "file":
                print(f"[{i}] FILE: {item['filename']}")


def serve_clipboard_image(data, mime_type, filename):
    try:
        from PySide6.QtCore import QMimeData, QTimer
        from PySide6.QtGui import QClipboard, QGuiApplication, QImage
    except ImportError:
        raise SystemExit("Image copying requires PySide6. Reinstall Tag System with: python -m pip install .")

    image = QImage.fromData(data)
    if image.isNull():
        raise SystemExit("The downloaded image could not be decoded; it was not copied.")
    if not os.environ.get("DISPLAY"):
        raise SystemExit("Image copying requires X11 or XWayland with DISPLAY set.")

    # Qt's X11 clipboard works without a focused window. On Wayland, XWayland
    # bridges these MIME offers to the desktop's Wayland clipboard manager.
    app = QGuiApplication(["tag", "-platform", "xcb"])
    mime = QMimeData()
    mime.setData(mime_type, data)
    mime.setImageData(image)
    # Match Spectacle's explicit-image marker and paste filename metadata.
    mime.setData("x-kde-force-image-copy", b"")
    mime.setData("application/x-kde-suggestedfilename", os.fsencode(filename))
    app.clipboard().setMimeData(mime, QClipboard.Mode.Clipboard)
    # Acknowledge publication from inside the event loop. The caller can exit
    # while this process continues serving image requests from the manager.
    QTimer.singleShot(0, lambda: print("ready", flush=True))
    QTimer.singleShot(IMAGE_CLIPBOARD_HOLD_MS, app.quit)
    app.exec()


def start_image_clipboard(command, data):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, start_new_session=True,
        )
        try:
            process.stdin.write(data)
            process.stdin.close()
            readable, _, _ = select.select(
                [process.stdout], [], [], IMAGE_CLIPBOARD_START_TIMEOUT_SECONDS,
            )
            if not readable:
                raise OSError("Image clipboard provider did not become ready")
            if process.stdout.readline() != b"ready\n":
                raise OSError("Image clipboard provider could not publish the image")
        except (OSError, ValueError) as exc:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            errors.seek(0)
            detail = errors.read(4096).decode("utf-8", errors="replace").strip()
            raise OSError(detail or str(exc)) from exc
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass  # Preserve the provider's error if it closed stdin early.
            process.stdout.close()


def copy_to_clipboard(data, mime_type="text/plain;charset=utf-8", filename=""):
    if mime_type.startswith("image/"):
        command = [
            sys.executable, "-c",
            "import sys; from tagsystem.client import serve_clipboard_image; "
            "serve_clipboard_image(sys.stdin.buffer.read(),sys.argv[1],sys.argv[2])",
            mime_type, filename,
        ]
    elif os.environ.get("WAYLAND_DISPLAY"):
        command = ["wl-copy", "--type", mime_type]
        install_hint = "Install wl-clipboard for Wayland clipboard support."
    else:
        target = "UTF8_STRING" if mime_type.startswith("text/plain") else mime_type
        command = ["xclip", "-selection", "clipboard", "-target", target]
        install_hint = "Install xclip for X11 clipboard support."

    if not mime_type.startswith("image/") and not shutil.which(command[0]):
        raise SystemExit(f"Clipboard helper {command[0]} was not found. {install_hint}")
    try:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        if mime_type.startswith("image/"):
            start_image_clipboard(command, payload)
        else:
            subprocess.run(command, input=payload, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Could not copy tag contents to the clipboard: {exc}") from exc


def read_history_reply(command, timeout):
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
        # Both methods return a GVariant tuple containing exactly one string.
        # This subset uses Python-compatible string/tuple escaping.
        reply = ast.literal_eval(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError):
        return None
    if isinstance(reply, tuple) and len(reply) == 1 and isinstance(reply[0], str):
        return reply[0]
    return None


def clipboard_history_command():
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":"):
        return None
    helper = shutil.which("gdbus")
    if helper is None:
        return None
    owner = read_history_reply([
        helper, "call", "--session", "--dest", "org.freedesktop.DBus",
        "--object-path", "/org/freedesktop/DBus",
        "--method", "org.freedesktop.DBus.GetNameOwner", "org.kde.klipper",
    ], CLIPBOARD_HISTORY_QUERY_SECONDS)
    if owner is None or not owner.startswith(":"):
        return None
    # A unique owner address cannot activate an absent/restarting Klipper.
    return [helper, "call", "--session", "--dest", owner, "--object-path", "/klipper",
            "--method", "org.kde.klipper.klipper.getClipboardContents"]


def wait_for_clipboard_history(data, mime_type, command):
    deadline = time.monotonic() + CLIPBOARD_SETTLE_SECONDS
    if command is not None and mime_type.startswith("text/plain"):
        expected = data.decode("utf-8") if isinstance(data, bytes) else data
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            reply = read_history_reply(command, min(CLIPBOARD_HISTORY_QUERY_SECONDS, remaining))
            if reply is None:
                break
            # Klipper returns its newest history entry, not the live selection.
            # Matching the full text means it is safe to publish the next item.
            if reply == expected:
                return
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def get(args):
    import requests

    base_url = server_url()
    auth_headers = headers(base_url)
    with requests.Session() as session:
        tag_name = quote(args.name, safe="")
        res = session.get(f"{base_url}/tags/{tag_name}", headers=auth_headers)
        if res.status_code != 200:
            print(res.json().get("detail"))
            return

        tag = res.json()
        if not tag["items"]:
            print("No items in tag")
            return
        clipboard_items = []
        text_entries = []
        download_dir = None

        for item in tag["items"]:
            if item["type"] in ["text", "url"]:
                text_entries.append(item["content"])
            elif item["type"] == "file":
                filename = item["filename"]
                if download_dir is None:
                    download_dir = tempfile.mkdtemp(prefix="tag-")
                tmp_path = Path(download_dir) / os.path.basename(filename)
                file_url = f"{base_url}/download/{tag_name}/{quote(filename, safe='')}"
                with closing(session.get(file_url, headers=auth_headers, stream=True)) as r:
                    r.raise_for_status()

                    with open(tmp_path, "wb") as f:
                        shutil.copyfileobj(r.raw, f)

                mime_type, encoding = mimetypes.guess_type(filename)
                if mime_type and mime_type.startswith("image/") and encoding is None:
                    clipboard_items.append((tmp_path.read_bytes(), mime_type, tmp_path.name))
                else:
                    try:
                        text = tmp_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        text = None
                    if text and "\x00" not in text:
                        clipboard_items.append((text, "text/plain;charset=utf-8", ""))
                    else:
                        clipboard_items.append((tmp_path.resolve().as_uri() + "\r\n", "text/uri-list", ""))

                if args.open_files:
                    subprocess.Popen(["xdg-open", str(tmp_path)])

    if text_entries:
        clipboard_items.insert(0, ("\n".join(text_entries), "text/plain;charset=utf-8", ""))

    history_command = clipboard_history_command() if len(clipboard_items) > 1 else None
    for index, (data, mime_type, filename) in enumerate(clipboard_items):
        if index:
            previous_data, previous_type, _ = clipboard_items[index - 1]
            wait_for_clipboard_history(previous_data, previous_type, history_command)
        copy_to_clipboard(data, mime_type, filename)
    count = len(clipboard_items)
    print(f"Copied {count} {'item' if count == 1 else 'items'} to clipboard")
    if count > 1:
        print("Use clipboard history to select earlier items")


def list_tags(args):
    import requests

    base_url = server_url()
    res = requests.get(f"{base_url}/tags", headers=headers(base_url))
    res.raise_for_status()
    for tag_name in res.json():
        print(tag_name)


def delete(args):
    import requests

    base_url = server_url()
    res = requests.delete(f"{base_url}/tags/{args.name}", headers=headers(base_url))
    if res.status_code == 404:
        print("Tag not found")
    else:
        res.raise_for_status()
        print("Deleted")


def search(args):
    import requests

    base_url = server_url()
    res = requests.get(f"{base_url}/tags/search/{args.query}", headers=headers(base_url))
    res.raise_for_status()
    for tag_name in res.json():
        print(tag_name)


parser = argparse.ArgumentParser(
    description="Store and retrieve text, URLs, and files from the Tag System server."
)
parser.add_argument("--version", action="version", version=f"Tag System {VERSION}")
sub = parser.add_subparsers(dest="command")

p = sub.add_parser("configure", help="Set the server URL and save its API key in the system keyring")
p.set_defaults(func=configure)

p = sub.add_parser("add", help="Add one or more items to a tag")
p.add_argument("name")
p.add_argument("--text", action="append", help="Text item to add; may be repeated")
p.add_argument("--url", action="append", help="URL item to add; may be repeated")
p.add_argument("--file", action="append", help="File to upload; may be repeated")
p.set_defaults(func=add)

p = sub.add_parser("show", help="Show one tag without changing the clipboard")
p.add_argument("name")
p.set_defaults(func=show)

p = sub.add_parser("show-all", help="Show every tag and all stored items")
p.set_defaults(func=show_all)

p = sub.add_parser("get", help="Copy combined text/URLs and separate files to clipboard history")
p.add_argument("name")
p.add_argument("--open-files", action="store_true", help="Open downloaded files with xdg-open")
p.set_defaults(func=get)

p = sub.add_parser("list", help="List tag names")
p.set_defaults(func=list_tags)

p = sub.add_parser("delete", help="Delete a tag and its stored files")
p.add_argument("name")
p.set_defaults(func=delete)

p = sub.add_parser("search", help="Search tag names")
p.add_argument("query")
p.set_defaults(func=search)



def main():
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
