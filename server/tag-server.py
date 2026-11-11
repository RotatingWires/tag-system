from collections import OrderedDict
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Request
from fastapi.responses import FileResponse
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time

from runtime_logging import configure_runtime_logging

configure_runtime_logging()

# No /docs, /redoc, or /openapi.json: FastAPI serves those without the API key.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

BASE_DIR = r"C:\path\to\folder\with\this\file"
TMP_DIR = os.path.join(BASE_DIR, "tag-cache")
os.makedirs(TMP_DIR, exist_ok=True)

DB_FILE = os.path.join(BASE_DIR, "tags.json")
API_KEY_HASH_FILE = os.path.join(BASE_DIR, "api-key.sha256")

AUTH_FAILURE_LIMIT = 5
AUTH_FAILURE_WINDOW_SECONDS = 60
MAX_TRACKED_ADDRESSES = 1024
auth_failures = OrderedDict()  # client address -> (window start, failed attempts)
auth_failures_lock = threading.Lock()

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)

def migrate_legacy_file_paths():
    db = load_db()
    changed = False

    for items in db.values():
        for item in items:
            if item.get("type") == "file" and "path" in item:
                item.pop("path", None)
                changed = True

    if changed:
        save_db(db)

def hash_api_key(api_key):
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

def load_or_create_api_key_hash():
    if os.path.exists(API_KEY_HASH_FILE):
        with open(API_KEY_HASH_FILE, "r", encoding="utf-8") as f:
            stored_hash = f.read().strip()
        if len(stored_hash) != 64:
            raise RuntimeError(f"Invalid API key hash file: {API_KEY_HASH_FILE}")
        return stored_hash

    api_key = secrets.token_urlsafe(32)
    api_key_hash = hash_api_key(api_key)

    with open(API_KEY_HASH_FILE, "x", encoding="utf-8") as f:
        f.write(api_key_hash)

    print()
    print("=" * 72)
    print("TAG SYSTEM FIRST-TIME SETUP")
    print()
    print("A new API key was generated:")
    print(api_key)
    print()
    print("Save this key on each client with: tag configure")
    print("The server stores only its SHA-256 hash and will not show this key again.")
    print("=" * 72)
    print()

    return api_key_hash

API_KEY_HASH = load_or_create_api_key_hash()
migrate_legacy_file_paths()

def auth(request, x_api_key):
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with auth_failures_lock:
        start, failures = auth_failures.get(address, (now, 0))
        if now - start >= AUTH_FAILURE_WINDOW_SECONDS:
            start, failures = now, 0
            auth_failures.pop(address, None)
        # Once locked out, reject every request (even the right key) so the
        # response cannot reveal whether a guess was correct.
        if failures >= AUTH_FAILURE_LIMIT:
            retry = max(1, math.ceil(AUTH_FAILURE_WINDOW_SECONDS - (now - start)))
            raise HTTPException(429, detail="Too many failed API key attempts. Try again later.",
                                headers={"Retry-After": str(retry)})

    if hmac.compare_digest(hash_api_key(x_api_key), API_KEY_HASH):
        return

    with auth_failures_lock:
        auth_failures.pop(address, None)
        auth_failures[address] = (start, failures + 1)
        while len(auth_failures) > MAX_TRACKED_ADDRESSES:
            auth_failures.popitem(last=False)
    raise HTTPException(status_code=403)

@app.post("/tags/{tag_name}/add")
async def add_tag(
    tag_name: str,
    request: Request,
    text: Optional[List[str]] = Form(None),
    url: Optional[List[str]] = Form(None),
    file: Optional[List[UploadFile]] = File(None),
    x_api_key: str = Header(...),
):
    auth(request, x_api_key)
    db = load_db()
    if tag_name not in db:
        db[tag_name] = []

    for text_item in text or []:
        if text_item:
            db[tag_name].append({"type": "text", "content": text_item})

    for url_item in url or []:
        if url_item:
            db[tag_name].append({"type": "url", "content": url_item})

    for uploaded_file in file or []:
        if not uploaded_file.filename:
            continue
        safe_name = os.path.basename(uploaded_file.filename)
        filepath = os.path.join(TMP_DIR, safe_name)
        with open(filepath, "wb") as destination:
            destination.write(await uploaded_file.read())
        db[tag_name].append({"type": "file", "filename": safe_name})

    save_db(db)
    return {"status": "saved", "items": db[tag_name]}

@app.get("/tags")
def list_tags(request: Request, x_api_key: str = Header(...)):
    auth(request, x_api_key)
    db = load_db()
    return list(db.keys())

@app.get("/tags/{tag_name}")
def get_tag(tag_name: str, request: Request, x_api_key: str = Header(...)):
    auth(request, x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")
    return {"items": db[tag_name]}

@app.delete("/tags/{tag_name}")
def delete_tag(tag_name: str, request: Request, x_api_key: str = Header(...)):
    auth(request, x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")

    for item in db[tag_name]:
        if item["type"] == "file":
            filepath = os.path.join(TMP_DIR, item["filename"])
            if os.path.exists(filepath):
                os.remove(filepath)

    del db[tag_name]
    save_db(db)
    return {"status": "deleted"}

@app.get("/tags/search/{query}")
def search_tags(query: str, request: Request, x_api_key: str = Header(...)):
    auth(request, x_api_key)
    db = load_db()
    return [k for k in db.keys() if query.lower() in k.lower()]

@app.get("/download/{tag_name}/{filename}")
def download_file(tag_name: str, filename: str, request: Request, x_api_key: str = Header(...)):
    auth(request, x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")
    for item in db[tag_name]:
        if item["type"] == "file" and item["filename"] == filename:
            filepath = os.path.join(TMP_DIR, item["filename"])
            if not os.path.isfile(filepath):
                raise HTTPException(404, detail="File not found on disk")
            return FileResponse(filepath, filename=filename)
    raise HTTPException(404, detail="File not found")
