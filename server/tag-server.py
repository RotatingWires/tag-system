from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import FileResponse
import hashlib
import hmac
import json
import os
import secrets

from runtime_logging import configure_runtime_logging

configure_runtime_logging()

app = FastAPI()

BASE_DIR = r"C:\path\to\folder\with\this\file"
TMP_DIR = os.path.join(BASE_DIR, "tag-cache")
os.makedirs(TMP_DIR, exist_ok=True)

DB_FILE = os.path.join(BASE_DIR, "tags.json")
API_KEY_HASH_FILE = os.path.join(BASE_DIR, "api-key.sha256")

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)

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

def auth(x_api_key):
    supplied_hash = hash_api_key(x_api_key)
    if not hmac.compare_digest(supplied_hash, API_KEY_HASH):
        raise HTTPException(status_code=403)

@app.post("/tags/{tag_name}/add")
async def add_tag(
    tag_name: str,
    text: Optional[List[str]] = Form(None),
    url: Optional[List[str]] = Form(None),
    file: Optional[List[UploadFile]] = File(None),
    x_api_key: str = Header(...),
):
    auth(x_api_key)
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
        db[tag_name].append({"type": "file", "filename": safe_name, "path": filepath})

    save_db(db)
    return {"status": "saved", "items": db[tag_name]}

@app.get("/tags")
def list_tags(x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    return list(db.keys())

@app.get("/tags/{tag_name}")
def get_tag(tag_name: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")
    return {"items": db[tag_name]}

@app.delete("/tags/{tag_name}")
def delete_tag(tag_name: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")

    for item in db[tag_name]:
        if item["type"] == "file":
            filepath = item["path"]
            if os.path.exists(filepath):
                os.remove(filepath)

    del db[tag_name]
    save_db(db)
    return {"status": "deleted"}

@app.get("/tags/search/{query}")
def search_tags(query: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    return [k for k in db.keys() if query.lower() in k.lower()]

@app.get("/download/{tag_name}/{filename}")
def download_file(tag_name: str, filename: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")
    for item in db[tag_name]:
        if item["type"] == "file" and item["filename"] == filename:
            return FileResponse(item["path"], filename=filename)
    raise HTTPException(404, detail="File not found")
