> [!WARNING]
> This project is fully vibecoded, probably inefficient, but it does what I wanted lol

# Tag System v1.1.0

A small self-hosted service for saving text, URLs, and files under tag names and retrieving them through a command-line client, including clipboard copies and file downloads.

**[Full manual](MANUAL.md)** — complete server/client setup, commands, clipboard behavior, API reference, backups, and dependency updates, preserved from the original README.

## Quickstart

Requires **Python 3.9+**. On each server/client machine, clone the repository and install it in a virtual environment. This installs the server dependencies and the `tag` client command:

```sh
git clone https://github.com/RotatingWires/tag-system.git
cd tag-system
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows Command Prompt, use `py -m venv .venv` and `.venv\Scripts\activate.bat` instead of the environment creation/activation commands above.

On the **server**, edit `BASE_DIR` in `server/tag-server.py` to your private data directory, then start the service:

```sh
cd server
uvicorn tag-server:app --host 0.0.0.0 --port 8710
```

On first startup, copy the API key printed **once** in the server console. The server saves only its hash. Restrict firewall access to trusted devices/networks.

On the **client**, with the environment activated:

```sh
tag configure
tag add notes --text "remember this"
tag show notes
tag list
tag get notes
```

`configure` asks for the server address, such as `http://192.168.1.50:8710` (`http://127.0.0.1:8710` for the same machine), and the API key. The key is entered without echoing and stored in your OS keyring; the address is saved in `~/.config/tag-system/config.json` (`%APPDATA%\tag-system\config.json` on Windows). Leave the key empty to keep the one already saved for that address. The Linux client needs an unlocked desktop keyring, `wl-copy` on Wayland or `xclip` on X11, and `xdg-open` for opening files. Image copies use PySide6 and require X11/XWayland with `DISPLAY` available. Run clipboard commands inside your desktop session. See [requirements](MANUAL.md#requirements) for helper installation and [client setup](MANUAL.md#client-setup) to run `tag` without activating the environment.

Upgrading from v1.0.x: run `python -m pip install .` again, then `tag configure` and enter the address you previously set as `BASE_URL`, leaving the key empty. The key you already saved is kept. Any old copy of `client/tag` (for example `~/bin/tag`) can be deleted.

Back up `tags.json` and `tag-cache/` together from `BASE_DIR`. Include `api-key.sha256` to keep the same client key after a restore. Use only one server instance per data directory.

## Security and privacy

This is a lightweight personal tool, not a hardened internet-facing service.

- The API key is generated with Python's `secrets` module on first startup instead of being committed or hardcoded.
- The server persists only a SHA-256 hash of the API key and compares hashes with `hmac.compare_digest`.
- The client persists the real API key in the operating-system keyring rather than in a file.
- Five failed API-key attempts from one IP address within a minute block that address (HTTP 429) for the rest of the minute, including requests with the correct key. Behind a reverse proxy, all clients share the proxy's address.
- `api-key.sha256`, `tags.json`, `tag-cache/`, and runtime `logs/` are ignored by Git.
- Plain HTTP still exposes the API key and payloads to someone capable of sniffing the network path. This project assumes a trusted LAN/VPN unless HTTPS is added separately.
- Restrict the firewall so port `8710` is not publicly reachable unless that is intentional.
- File downloads are authorized with the same API key as other requests.
- `tags.json` and `tag-cache/` may contain private material; back them up appropriately.
- The server does not enable CORS because the provided client is a CLI and does not need browser cross-origin access.
- Only run this service for users/devices you trust.

Use HTTPS through a reverse proxy across untrusted networks. The API key authorizes all tag/file operations; this service uses an `x-api-key` header rather than login cookies or session tokens. FastAPI's `/docs`, `/redoc`, and `/openapi.json` are publicly readable, while tag/file requests still require the key.

The generated API key is console-only and excluded from runtime logging. `logs/console.log` can still contain client IPs, tag names, endpoint paths, and filenames; keep it private. Downloaded files use temporary directories, and clipboard history may retain copied material according to your desktop's settings.

See the manual for [all commands](MANUAL.md#commands), [API-key rotation](MANUAL.md#rotating-the-api-key), [HTTP endpoints](MANUAL.md#http-endpoints), and [backup behavior](MANUAL.md#data-and-backup-behavior).
