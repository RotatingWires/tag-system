> [!WARNING]
> This project is fully vibecoded, probably inefficient, but it does what I wanted lol

# Tag System v1.1.0

A small self-hosted tagging service for saving **text, URLs, and files** under simple tag names and retrieving them from a command-line client. It is designed for a personal LAN/VPN workflow: a FastAPI server runs on one machine (for example a Windows NAS), while the `tag` client runs on Linux or another computer and talks to that server over HTTP.

## What it does

A tag can contain multiple items. Items can be plain text, URLs, or uploaded files. The client can add items, list tags, show one tag, show all tags, search tag names, delete a tag, retrieve tag contents to the clipboard, download stored files, and optionally open downloaded files.

Project layout:

```text
server/tag-server.py   FastAPI server and JSON/file storage
tagsystem/client.py    command-line client, installed as the `tag` command
pyproject.toml         package metadata and Python dependencies
```

## Requirements

Server:

- Python 3.9+
- FastAPI
- Uvicorn
- `python-multipart` for file uploads

Client:

- Python 3.9+
- `requests`
- `PySide6` for native Qt image clipboard data
- `keyring` for storing the API key in the operating system credential store
- Linux clipboard/open helpers for text and file entries: `wl-copy` (Wayland) or `xclip` (X11), and `xdg-open`
- X11 or XWayland with `DISPLAY` available for image copies

From the repository root, install the package into a virtual environment. One install provides both the server dependencies and the `tag` command:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

For KDE/Hyprland or another Wayland session, install `wl-copy`:

```bash
# Fedora
sudo dnf install wl-clipboard
# Arch
sudo pacman -S wl-clipboard
```

For an X11 session, install `xclip` instead (Fedora: `sudo dnf install xclip`; Arch: `sudo pacman -S xclip`). For text/file-URI copies, the client uses `wl-copy` when `WAYLAND_DISPLAY` is set, including sessions that also have XWayland; otherwise it uses `xclip`. Image copies use Qt through PySide6, as described below. Run `tag get` inside your desktop session so the clipboard service is reachable. A missing/failed helper reports an error instead of claiming the copy succeeded.

`xdg-open` is normally provided by the desktop environment / `xdg-utils` package. The Python `keyring` package uses the credential backend provided by the desktop session. On Linux this is normally a Secret Service-compatible keyring/wallet, and your desktop may prompt you to unlock it.

## Server setup

Open `server/tag-server.py` and set only the data directory:

```python
BASE_DIR = r"C:\path\to\tag-system-data"
```

There is no API key in the source code.

The server creates/uses:

```text
tags.json         tag database
tag-cache/        stored file uploads
api-key.sha256    SHA-256 hash of the API key
```

Run the server from the `server` directory:

```bash
cd server
uvicorn tag-server:app --host 0.0.0.0 --port 8710
```

If your Uvicorn/Python import setup dislikes the hyphen in `tag-server.py`, rename it to `tag_server.py` and run:

```bash
uvicorn tag_server:app --host 0.0.0.0 --port 8710
```

### Runtime logging

The server writes its normal Uvicorn/Python runtime log stream to:

```text
logs/console.log
```

The file is created at the repository root, while Uvicorn's normal console output remains unchanged when the server is launched interactively. It includes server startup/shutdown messages, access-request lines and status codes, warnings, errors, and logged exceptions.

Only one log file is kept. When the next log record would push `logs/console.log` over 10 MiB, the server truncates that same file and continues writing from the beginning. It does not create numbered or rotated backup logs. The `logs/` directory is ignored by Git.

Sensitive authentication material is intentionally kept out of the runtime log. The one-time generated API key is still printed directly with `print()` to the interactive console only and is never sent through Python's logging system. Uvicorn's normal access log does not include request headers, so the `x-api-key` header is not written to `console.log`. Request bodies are not logged by this project.

The log can still contain client IP addresses, endpoint paths, tag names, or filenames that appear in URLs, so treat it as private runtime data.

For Windows Task Scheduler, launch the Python interpreter directly with:

```text
Program/script:
<full path to python.exe>

Arguments:
-m uvicorn tag-server:app --host 0.0.0.0 --port 8710

Start in:
<repository path>\server
```

No `cmd.exe` wrapper is required for file logging.

### First server startup

If `api-key.sha256` does not exist, the server generates a cryptographically random API key and prints the real key **once** in the server console:

```text
========================================================================
TAG SYSTEM FIRST-TIME SETUP

A new API key was generated:
<generated key>

Save this key on each client with: tag configure
The server stores only its SHA-256 hash and will not show this key again.
========================================================================
```

Copy that generated key long enough to configure each client. The server writes only the SHA-256 hash to `api-key.sha256`; it does not persist the original API key.

Allow TCP port `8710` through the server firewall only from networks/devices that should reach it.

## Why the server uses a hash but the client uses a keyring

The server never needs to recover the original API key. When a request arrives, it hashes the supplied `x-api-key` value and compares that hash with `api-key.sha256` using `hmac.compare_digest`. Because the generated key has high random entropy, a stolen SHA-256 hash is not practically useful for recovering the original key.

The client is different: it must send the original API key with every request, so it needs a recoverable copy. Instead of keeping that secret in a file, the client stores it in the operating system's credential/keyring service.

Using Windows Credential Manager on the NAS would not improve this server design. The server only needs a verifier, so storing a recoverable copy of the secret would expose more secret material than necessary and can complicate unattended service startup.

## Client setup

`python -m pip install .` installs the `tag` command into the virtual environment. To run it without activating the environment, link it onto your PATH:

```bash
mkdir -p ~/bin
ln -s "$PWD/.venv/bin/tag" ~/bin/tag
```

Then point the client at your server and store the API key it generated:

```bash
tag --version
tag configure
```

The client asks for the server address and then the key, without echoing the key:

```text
Server URL (http://HOST:PORT): http://192.168.1.50:8710
API key (leave empty to keep the saved key):
Server set to http://192.168.1.50:8710
API key saved to system keyring
```

The address is saved in `~/.config/tag-system/config.json` (or `$XDG_CONFIG_HOME/tag-system/config.json`; `%APPDATA%\tag-system\config.json` on Windows). The key is stored in the keyring under that address, so each server keeps its own key. Running `tag configure` again shows the saved address as the default; press Enter to keep it, and leave the key empty to keep the saved key. Do **not** put the API key in any file.

## Rotating the API key

To generate a new key:

1. Stop the Tag System server.
2. Delete `api-key.sha256` from `BASE_DIR`.
3. Start the server again.
4. Copy the newly generated key from the console.
5. Run `tag configure` on every client and enter the new key.

The old key stops working as soon as the server starts with the new hash.

Deleting `api-key.sha256` does **not** delete `tags.json` or anything in `tag-cache`.

## Commands

`tag --version` prints the installed client version without contacting the server or reading the keyring. `VERSION` in `tagsystem/client.py` owns the release number; `pyproject.toml` reads it from there. Reinstall with `python -m pip install .` after updating the repository so the installed command matches.

```bash
tag configure
tag add notes --text "remember this"
tag add docs --url "https://example.com"
tag add manuals --file ./manual.pdf
tag show notes
tag show-all
tag get manuals
tag get manuals --open-files
tag list
tag search router
tag delete old-tag
```

Use:

```bash
tag -h
tag add -h
tag get -h
```

for built-in command and option help.

### `tag configure`

Set the server address and save or replace its API key in the client's operating-system keyring. The API key is entered interactively so it does not need to be written into a file or passed as a normal command-line argument. Other commands report `No server configured. Run: tag configure` until this has been run.

### `tag add NAME`

Add one or more items to a tag. `--text`, `--url`, and `--file` are repeatable, so one command can append several items without replacing items already stored under that tag.

Examples:

```bash
tag add links --url "https://example.com/a" --url "https://example.com/b"
tag add notes --text "one" --text "two"
tag add files --file ./one.txt --file ./two.png
tag add mixed --text "hello" --url "https://example.com" --file ./photo.png
```

### `tag show NAME`

Print the items stored under one tag. File entries show their filename. Absolute server paths are not stored in `tags.json`.

### `tag show-all`

Print every tag and its items.

### `tag get NAME`

Retrieve **all entries** in the tag and combine saved text and URL entries into **one text clipboard item**, separated by newlines in their stored order. Images and other uploaded files are copied as individual items after that text item. For example, two URLs plus a PNG produce one text item containing both URLs and one image item. Use the desktop clipboard-history picker to choose an earlier item; ordinary paste uses the last copied item.

- Saved text and URL entries share one clipboard item, preserving Unicode and whitespace within each entry.
- Image uploads copy a decoded Qt image plus the original encoded image format, allowing Qt to expose native image formats for pasting. The payload also includes KDE's explicit-image marker and a suggested filename, matching Spectacle's image-copy behavior.
- UTF-8 text-file uploads copy the file's contents as a separate text item; they are uploaded files rather than saved text/URL entries.
- Other binary files and empty text files copy a local file URI (`text/uri-list`) for applications that support pasting files.

Files are downloaded into a new `tag-*` temporary directory for each retrieval, so later retrievals do not overwrite files referenced by earlier history entries. Temporary-file retention follows your operating system's cleanup policy. Names containing spaces, `#`, or other URL-special characters are encoded in download requests.

Text and file-URI copies use `wl-copy` on Wayland or `xclip` on X11. On KDE, before replacing a text item, `tag get` checks Klipper's newest history entry and moves on as soon as the full text matches. That avoids the fixed half-second pause when Klipper captures it quickly. The optional check uses the desktop's `gdbus` executable in a separate process; it does not initialize Qt alongside the keyring in the main CLI process. Qt remains confined to the image provider. If `gdbus` is unavailable, Klipper cannot confirm the text, or the preceding item is an image/file URI, the normal half-second capture window remains. Queries have short timeouts, only read history, and target Klipper's existing D-Bus owner so they cannot start it or modify its settings.

Image copies run a separate Qt clipboard provider that stays in its event loop for two seconds, matching Spectacle's transfer lifetime. That transfer window runs in the background: `tag get` waits only until the provider publishes the image, then finishes without waiting for its two-second lifetime. Image workers skip HTTP/keyring imports; those libraries load only in commands that use them. All downloads in one `tag get` reuse one HTTP session, allowing connection reuse rather than making a new connection for each file. Startup/download errors still stop the command instead of reporting a successful copy. Downloads and any necessary capture wait still take time.

The OS clipboard itself holds one current item: without a running history manager, only the last copy remains available. History limits, duplicate suppression, supported image formats, and recording speed depend on that manager. Empty tags leave the clipboard unchanged.

The image payload follows [Spectacle's export implementation](https://github.com/KDE/spectacle/blob/master/src/ExportManager.cpp): an image MIME format, a Qt image object, `x-kde-force-image-copy`, and `application/x-kde-suggestedfilename`. Klipper recognizes the explicit-image marker and can retain these images even when ordinary image-history recording is disabled.

The image provider uses Qt's X11 clipboard without opening a window. On a Wayland desktop, XWayland bridges those clipboard offers to the Wayland clipboard; `DISPLAY` must be available. Install PySide6 with the client dependencies, or your distro's Python PySide6 package. A Wayland-only session without XWayland cannot use this image provider; text/file copies still use their normal Wayland helper. Other desktops need a clipboard-history manager configured to capture image data.

Use:

```bash
tag get NAME --open-files
```

to also open each downloaded file with `xdg-open`.

After updating the repo, run `python -m pip install .` again in its environment so the installed `tag` command is updated.

Upgrading from v1.0.x, where the client was the `client/tag` script with a hardcoded `BASE_URL`: reinstall as above, then run `tag configure`, enter the address you previously set as `BASE_URL`, and leave the key empty. Keys saved by the old client are stored under that same address, so they keep working. Delete any old copy of the script, such as `~/bin/tag`, and link the new command as described in Client setup.

### `tag list`

Print tag names only.

### `tag search QUERY`

Search tag **names** case-insensitively. This does not currently full-text-search the contents of saved text/files.

### `tag delete NAME`

Delete the tag's database entry. Uploaded files belonging to that tag are also removed from `tag-cache` when they are still present on disk.

## How it works

The server exposes HTTP endpoints for tag creation/retrieval, search, deletion, and file downloads. Every request must include the `x-api-key` header.

On startup, the server loads the stored API-key hash. For each request it hashes the key supplied by the client and compares the two hashes. The real API key is therefore not required in the server source code or persistent server storage.

Metadata is stored in a JSON database; uploaded files are copied into `tag-cache/`.

The CLI converts commands such as `tag add` or `tag show` into HTTP requests to the server address saved by `tag configure`. Before making an authenticated request, it reads that server's API key from the operating-system keyring and sends it in the `x-api-key` request header.

The server counts failed API-key attempts per client IP address. After five failures within one minute, every request from that address receives HTTP 429 with a `Retry-After` header until the minute ends, including requests with the correct key, so a lockout cannot reveal whether a guess was right. The count is kept in memory and resets when the server restarts. Behind a reverse proxy, every client appears as the proxy's address and shares one limit.

Uploaded filenames are reduced to their basename before storage so a supplied path cannot directly choose an arbitrary server directory. File records store only the filename; the server resolves the current path from `BASE_DIR/tag-cache/` when downloading or deleting a file.

On startup, the server also removes legacy `"path"` fields from older file records in `tags.json`. This migration does not move or delete files. It only removes stale absolute-path metadata so the database remains portable if `BASE_DIR` changes.

## HTTP endpoints

The examples use `http://localhost:8710`. All six tag/file endpoints require the `x-api-key` header, containing the key generated during first server setup. This API uses a key header rather than login cookies or session tokens. A missing header returns 422 validation details; an incorrect key returns 403. After five incorrect keys from one IP address within a minute, that address receives 429 for the rest of the minute. URL-encode tag names, filenames, and search text as individual path components.

| Method | Path | Request | Response / effect |
| --- | --- | --- | --- |
| GET | `/tags` | API-key header; no body. | JSON array of tag names in database insertion order. |
| GET | `/tags/{tag_name}` | API-key header; no body. | `{items: [...]}` containing every stored entry in order; 404 with `detail: "Tag not found"` when absent. |
| POST | `/tags/{tag_name}/add` | API-key header; form fields `text`, `url`, and uploaded `file`, each repeatable. | Creates a tag if needed and appends items. Returns `{status: "saved", items: [...]}` containing the complete tag after the append. Text-only requests can be form-urlencoded; file uploads use multipart form data. This endpoint does not accept a JSON item array. |
| DELETE | `/tags/{tag_name}` | API-key header; no body. | Deletes the tag and its stored files, returning `{status: "deleted"}`; absent tags return 404. |
| GET | `/tags/search/{query}` | API-key header; no body. | JSON array of tag names containing the query, case-insensitively. Searches names, not saved content; no matches gives `[]`. |
| GET | `/download/{tag_name}/{filename}` | API-key header; no body. | Raw file bytes with an attachment filename. The file must be recorded under that tag and exist on disk; otherwise 404. |

All successful tag operations return 200. Text/URL entries are `{type: "text" or "url", content: "..."}`; file entries are `{type: "file", filename: "..."}`. Empty text/URL fields are skipped. Empty add requests can create an empty tag. URLs are stored as supplied text, without fetching or validating their targets. Reads/searches are not paginated, and no single-item delete/update route exists.

Uploads use the filename's basename in a shared `tag-cache` directory. Uploading the same filename replaces that file's bytes, including when another tag references it. Deleting a tag removes its referenced files even if another tag references those same filenames. JSON metadata and file operations are not a single atomic transaction.

Examples (replace the address and placeholder key):

```bash
curl -H "x-api-key: YOUR_KEY" "http://localhost:8710/tags"
curl -H "x-api-key: YOUR_KEY" "http://localhost:8710/tags/notes"
curl -H "x-api-key: YOUR_KEY" -F "text=first entry" -F "text=second entry" -F "file=@./notes.txt" "http://localhost:8710/tags/notes/add"
curl -H "x-api-key: YOUR_KEY" -o notes.txt "http://localhost:8710/download/notes/notes.txt"
curl -X DELETE -H "x-api-key: YOUR_KEY" "http://localhost:8710/tags/notes"
```

FastAPI also serves `/openapi.json` (machine-readable schema), `/docs` (Swagger UI), and `/redoc` (ReDoc) without API-key authentication. These documentation pages describe the routes; requests to the tag/file routes still need the key. HTTP errors normally use a JSON `detail` field; validation errors use a `detail` array, and unexpected server/filesystem errors can return 500 without that shape.

## Data and backup behavior

The important runtime data is:

```text
BASE_DIR/
├── tags.json
├── tag-cache/
└── api-key.sha256
```

Back up `tags.json` and `tag-cache/` together. `tags.json` contains tag metadata and stored filenames, while `tag-cache` contains the uploaded file data. Because file records no longer contain absolute paths, moving the complete data directory does not require rewriting file entries in the database.

`api-key.sha256` can also be backed up if you want a restored server to keep accepting the same client key. If it is lost, start the server without it to generate a new key and run `tag configure` again on the clients.

Because the database is a JSON file rather than a transactional database, avoid running multiple independent server instances against the same `BASE_DIR` at the same time.

## Security and privacy

This is a lightweight personal tool, not a hardened internet-facing service.

- The API key is generated with Python's `secrets` module on first startup instead of being committed or hardcoded.
- The server persists only a SHA-256 hash of the API key and compares hashes with `hmac.compare_digest`.
- The client persists the real API key in the operating-system keyring rather than in a file.
- Five failed API-key attempts from one IP address within a minute block that address (HTTP 429) for the rest of the minute.
- `api-key.sha256`, `tags.json`, `tag-cache/`, and runtime `logs/` are ignored by Git.
- Plain HTTP still exposes the API key and payloads to someone capable of sniffing the network path. This project assumes a trusted LAN/VPN unless HTTPS is added separately.
- Restrict the firewall so port `8710` is not publicly reachable unless that is intentional.
- File downloads are authorized with the same API key as other requests.
- `tags.json` and `tag-cache/` may contain private material; back them up appropriately.
- The server does not enable CORS because the provided client is a CLI and does not need browser cross-origin access.
- Only run this service for users/devices you trust.

## Updating dependencies

The Python packages used by this repository are listed under `dependencies` in `pyproject.toml`:

```text
fastapi
uvicorn
python-multipart
requests
keyring
PySide6
```

To update the installed packages used by this setup, from the repository root with the environment activated:

```bash
python -m pip install --upgrade .
```

After updating FastAPI/Uvicorn, Python, or the client keyring package, restart the server and test `tag list`, `tag add`, and `tag get` once.

## Development checks

Run the client regression tests (clipboard and `tag configure`) without a live server or desktop clipboard, from the repository root:

```bash
python3 -m unittest discover -s tests -v
```
