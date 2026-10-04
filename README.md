> [!WARNING]
> This project is fully vibecoded, probably inefficient, but it does what I wanted lol

# Tag System

A small self-hosted tagging service for saving **text, URLs, and files** under simple tag names and retrieving them from a command-line client. It is designed for a personal LAN/VPN workflow: a FastAPI server runs on one machine (for example a NAS), while the `tag` client can run on Linux or another computer and talk to that server over HTTP.

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
- Linux clipboard/open helpers used by some commands: `xclip` and `xdg-open`

Install the Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

A virtual environment is optional; the project does not require one.

On Fedora, the clipboard helper can be installed with:

```bash
sudo dnf install xclip
```

`xdg-open` is normally provided by the desktop environment / `xdg-utils` package.

## Server setup

Open `server/tag-server.py` and set:

```python
BASE_DIR = r"C:\path\to\tag-system-data"
API_KEY = "replace-with-a-long-random-key"
```

`BASE_DIR` is where runtime data is stored. The server creates/uses:

```text
tags.json    tag database
tag-cache/   stored file uploads
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

Allow TCP port `8710` through the server firewall only from networks/devices that should reach it.

## Client setup

Edit the top of `client/tag` so it points at your server and uses the same API key:

```python
BASE_URL = "http://192.168.1.50:8710"
API_KEY = "the-same-key-used-by-the-server"
```

Make it executable and optionally put it on your PATH:

```bash
chmod +x client/tag
mkdir -p ~/bin
cp client/tag ~/bin/tag
```

## Commands

```bash
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

### `tag add NAME`

Add one or more items to a tag. `--text`, `--url`, and `--file` are repeatable, so one command can append several items without replacing items already stored under that tag.

Examples:

```bash
tag add links --url "https://example.com/a" --url "https://example.com/b"
tag add mixed --text "hello" --url "https://example.com" --file ./photo.png
```

### `tag show NAME`

Print the items stored under one tag. File entries show their filename and the server-side Windows path recorded in `tags.json`.

### `tag show-all`

Print every tag and its items.

### `tag get NAME`

Retrieve the tag and copy a text representation to the Linux clipboard with `xclip`.

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

The server exposes HTTP endpoints for tag creation/retrieval, search, deletion, and file downloads. Every request must include the configured `x-api-key` header. Metadata is stored in a JSON database; uploaded files are copied into `tag-cache/`.

Main endpoints:

```text
GET    /tags
GET    /tags/{tag_name}
POST   /tags/{tag_name}/add
DELETE /tags/{tag_name}
GET    /tags/search/{query}
GET    /download/{tag_name}/{filename}
```

The CLI converts commands such as `tag add` or `tag show` into HTTP requests to the server. File items are downloaded from the server's `/download/...` endpoint when `tag get` needs them.

Uploaded filenames are reduced to their basename before storage so a supplied path cannot directly choose an arbitrary server directory. The actual cached file path is stored in the JSON entry.

## Data and backup behavior

The important runtime data is:

```text
BASE_DIR/
├── tags.json
└── tag-cache/
```

Back up both together. `tags.json` contains metadata and paths, while `tag-cache` contains the uploaded file data.

Because the database is a JSON file rather than a transactional database, avoid running multiple independent server instances against the same `BASE_DIR` at the same time.

## Security

This is a lightweight personal tool, not a hardened internet-facing service.

- The API key is a shared secret. Use a long random value and do not commit the real key.
- Plain HTTP exposes the API key and payloads to anyone who can sniff that network path. Prefer a trusted LAN, WireGuard/Tailscale/other VPN, or put the service behind HTTPS before using it across untrusted networks.
- Restrict the firewall so port `8710` is not open to the public internet unless you intentionally add proper TLS/reverse-proxy/access controls.
- `tags.json` and `tag-cache/` can contain private material and are ignored by Git. Back them up separately if needed.
- The current server enables permissive CORS (`allow_origins=["*"]`). The API key still protects the endpoints, but this configuration is intended for a trusted personal environment rather than public exposure.
- File downloads are authorized with the same API key as other requests.
- Only run this service for users/devices you trust.

## Updating dependencies

The Python packages used by this repository are listed in `requirements.txt`:

```text
fastapi
python-multipart
requests
uvicorn
```

To update the globally installed copies used by this setup:

```bash
python3 -m pip install --upgrade -r requirements.txt
```

After updating FastAPI/Uvicorn or Python itself, restart the server and test `tag list`, `tag add`, and `tag get` once.
