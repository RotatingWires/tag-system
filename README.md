> [!WARNING]
> This project is fully vibecoded, probably inefficient, but it does what I wanted lol

# Tag System

A small self-hosted tagging service for saving **text, URLs, and files** under simple tag names and retrieving them from a command-line client. It is designed for a personal LAN/VPN workflow: a FastAPI server runs on one machine (for example a NAS), while the `tag` client can run on Linux or another computer and talk to that server over HTTP.

## What it does

A tag can contain multiple items. Items can be plain text, URLs, or uploaded files. The client can add items, list tags, show one tag, search all tags, delete a tag, copy retrieved data to the clipboard, download files, and optionally open downloaded files.

Project layout:

```text
server/tag-server.py   FastAPI server and JSON/file storage
client/tag             Command-line client
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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Fedora, the optional clipboard helper can be installed with:

```bash
sudo dnf install xclip
```

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

If your Uvicorn version dislikes the hyphen in `tag-server.py`, rename it to `tag_server.py` and run:

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

## Example commands

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

Multiple `--text`, `--url`, and `--file` values can be supplied to one `add` command.

## How it works

The server exposes HTTP endpoints for tag creation/retrieval, search, deletion, and file downloads. Every request must include the configured `x-api-key` header. Metadata is stored in a JSON database; uploaded files are copied into `tag-cache/`.

The CLI converts commands such as `tag add` or `tag show` into HTTP requests to the server. For `get`, it can combine text/URL/file contents into clipboard-friendly output. File items are downloaded from the server's `/download/...` endpoint.

Deleting a tag removes its database entry and also deletes uploaded files for that tag when those files are still present on disk.

## Security

This is a lightweight personal tool, not a hardened internet-facing service. Important points:

- The API key is a shared secret. Use a long random value and do not commit the real key.
- Plain HTTP exposes the API key and payloads to anyone who can sniff that network path. Prefer a trusted LAN, WireGuard/Tailscale/other VPN, or put the service behind HTTPS before using it across untrusted networks.
- Restrict the firewall so port `8710` is not open to the public internet unless you intentionally add proper TLS/reverse-proxy/access controls.
- `tags.json` and `tag-cache/` can contain private material and are ignored by Git. Back them up separately if needed.
- Uploaded filenames are handled by the server and stored on disk; only run this service for users you trust.
