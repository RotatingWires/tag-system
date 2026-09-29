# Tag System

A small self-hosted tag service for saving and retrieving text, URLs, and files from a command-line client.

The project has two parts:

- `server/tag-server.py` — FastAPI server that stores tag metadata in `tags.json` and uploaded files in `tag-cache/`.
- `client/tag` — command-line client for adding, showing, searching, deleting, copying, and opening tagged items.

## Server setup

Install the server dependencies:

```bash
python -m pip install -r requirements.txt
```

Edit these values in `server/tag-server.py` before running it:

```python
BASE_DIR = r"C:\\path\\to\\tag-system-data"
API_KEY = "replace-with-a-long-random-key"
```

Run the server, for example:

```bash
uvicorn server.tag-server:app --host 0.0.0.0 --port 8710
```

Because the filename contains a hyphen, an alternative is to run it from the `server` directory:

```bash
cd server
uvicorn tag-server:app --host 0.0.0.0 --port 8710
```

If your Uvicorn version does not accept the hyphenated module name, rename `tag-server.py` to `tag_server.py` and run `uvicorn tag_server:app ...`.

## Client setup

Install the client dependency:

```bash
python -m pip install requests
```

Edit the connection settings near the top of `client/tag`:

```python
BASE_URL = "http://server-ip:8710"
API_KEY = "the-same-key-used-by-the-server"
```

On Linux, make the client executable and optionally place it somewhere on your `PATH`:

```bash
chmod +x client/tag
cp client/tag ~/bin/tag
```

The `get` command uses `xclip` for clipboard support and `xdg-open` when `--open-files` is used.

## Commands

```text
tag add NAME --text "some text"
tag add NAME --url "https://example.com"
tag add NAME --file ./example.txt
tag show NAME
tag show-all
tag get NAME
tag get NAME --open-files
tag list
tag search QUERY
tag delete NAME
```

Multiple `--text`, `--url`, and `--file` arguments can be supplied to one `add` command.

## Security

The API key is sent in the `x-api-key` HTTP header. Do not commit a real key to this repository. If the service is reachable outside a trusted LAN/VPN, put it behind HTTPS and appropriate firewall/access controls.

Runtime data (`tags.json` and `tag-cache/`) is ignored by Git and should remain private.
