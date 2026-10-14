> [!WARNING]
> This project is fully vibecoded, probably inefficient, but it does what I wanted lol

# Tag System

A small self-hosted tagging service for saving **text, URLs, and files** under simple tag names and retrieving them from a command-line client. It is designed for a personal LAN/VPN workflow: a FastAPI server runs on one machine (for example a Windows NAS), while the `tag` client runs on Linux or another computer and talks to that server over HTTP.

## What it does

A tag can contain multiple items. Items can be plain text, URLs, or uploaded files. The client can add items, list tags, show one tag, show all tags, search tag names, delete a tag, retrieve tag contents to the clipboard, download stored files, and optionally open downloaded files.

Project layout:

```text
server/tag-server.py   FastAPI server and JSON/file storage
client/tag             command-line client
requirements.txt       Python dependencies
```

## Requirements

Server:

- Python 3
- FastAPI
- Uvicorn
- `python-multipart` for file uploads

Client:

- Python 3
- `requests`
- `keyring` for storing the API key in the operating system credential store
- Linux clipboard/open helpers used by some commands: `wl-copy` (Wayland) or `xclip` (X11), and `xdg-open`

Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

For KDE/Hyprland or another Wayland session, install `wl-copy`:

```bash
# Fedora
sudo dnf install wl-clipboard
# Arch
sudo pacman -S wl-clipboard
```

For an X11 session, install `xclip` instead (Fedora: `sudo dnf install xclip`; Arch: `sudo pacman -S xclip`). The client uses `wl-copy` when `WAYLAND_DISPLAY` is set, including sessions that also have XWayland; otherwise it uses `xclip`. Run `tag get` inside your desktop session so the clipboard service is reachable. A missing/failed helper reports an error instead of claiming the copy succeeded.

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

The client is different: it must send the original API key with every request, so it needs a recoverable copy. Instead of keeping that secret directly in `client/tag`, the client stores it in the operating system's credential/keyring service.

Using Windows Credential Manager on the NAS would not improve this server design. The server only needs a verifier, so storing a recoverable copy of the secret would expose more secret material than necessary and can complicate unattended service startup.

## Client setup

Edit only the server address near the top of `client/tag`:

```python
BASE_URL = "http://192.168.1.50:8710"
```

Do **not** put the API key in the script.

Make the client executable and optionally put it on your PATH:

```bash
chmod +x client/tag
mkdir -p ~/bin
cp client/tag ~/bin/tag
```

Then store the API key generated by the server:

```bash
tag configure
```

The client prompts without echoing the key:

```text
API key:
API key saved to system keyring
```

Running `tag configure` again replaces the stored key for the configured `BASE_URL`.

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

Save or replace the server API key in the client's operating-system keyring. The API key is entered interactively so it does not need to be written into the client source or passed as a normal command-line argument.

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

Retrieve **all entries** in the tag and copy them together to the Linux clipboard in one operation, in their stored order, separated by newlines. The client uses `wl-copy` on Wayland or `xclip` on X11 and preserves Unicode and leading/trailing whitespace. Empty tags leave the clipboard unchanged.

For text and URL items, the actual text/URL is copied.

For file items, the client downloads the file into the local temporary directory. The clipboard text includes the downloaded path. If the downloaded file is UTF-8-readable text, its text contents are appended too. Binary file bytes are **not** placed on the clipboard as a native file object by the current client; binary entries are represented by their downloaded path plus a note that their contents are not displayed.

Use:

```bash
tag get NAME --open-files
```

to also open each downloaded file with `xdg-open`.

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

The CLI converts commands such as `tag add` or `tag show` into HTTP requests to the server. Before making an authenticated request, it reads the API key from the operating-system keyring and sends it in the `x-api-key` request header.

Uploaded filenames are reduced to their basename before storage so a supplied path cannot directly choose an arbitrary server directory. File records store only the filename; the server resolves the current path from `BASE_DIR/tag-cache/` when downloading or deleting a file.

On startup, the server also removes legacy `"path"` fields from older file records in `tags.json`. This migration does not move or delete files. It only removes stale absolute-path metadata so the database remains portable if `BASE_DIR` changes.

## HTTP endpoints

The examples use `http://localhost:8710`. All six tag/file endpoints require the `x-api-key` header, containing the key generated during first server setup. This API uses a key header rather than login cookies or session tokens. A missing header returns 422 validation details; an incorrect key returns 403. URL-encode tag names, filenames, and search text as individual path components.

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

## Security

This is a lightweight personal tool, not a hardened internet-facing service.

- The API key is generated with Python's `secrets` module on first startup instead of being committed or hardcoded.
- The server persists only a SHA-256 hash of the API key and compares hashes with `hmac.compare_digest`.
- The client persists the real API key in the operating-system keyring rather than in `client/tag`.
- `api-key.sha256`, `tags.json`, `tag-cache/`, and runtime `logs/` are ignored by Git.
- Plain HTTP still exposes the API key and payloads to someone capable of sniffing the network path. This project assumes a trusted LAN/VPN unless HTTPS is added separately.
- Restrict the firewall so port `8710` is not publicly reachable unless that is intentional.
- File downloads are authorized with the same API key as other requests.
- `tags.json` and `tag-cache/` may contain private material; back them up appropriately.
- The server does not enable CORS because the provided client is a CLI and does not need browser cross-origin access.
- Only run this service for users/devices you trust.

## Updating dependencies

The Python packages used by this repository are listed in `requirements.txt`:

```text
fastapi
keyring
python-multipart
requests
uvicorn
```

To update the installed packages used by this setup:

```bash
python3 -m pip install --upgrade -r requirements.txt
```

After updating FastAPI/Uvicorn, Python, or the client keyring package, restart the server and test `tag list`, `tag add`, and `tag get` once.

## Development checks

Run clipboard regression tests without a live server or desktop clipboard:

```bash
python3 -m unittest discover -s tests -v
```
