from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os, json

app = FastAPI()

# Windows-safe paths
BASE_DIR = r"C:\path\to\folder\with\this\file"
TMP_DIR = os.path.join(BASE_DIR, "tag-cache")
os.makedirs(TMP_DIR, exist_ok=True)

DB_FILE = os.path.join(BASE_DIR, "tags.json")
API_KEY = "key-here"

# CORS (optional)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- helpers ---
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def auth(x_api_key):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403)

# --- Add / append items ---
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

        db[tag_name].append({
            "type": "file",
            "filename": safe_name,
            "path": filepath,
        })

    save_db(db)
    return {"status": "saved", "items": db[tag_name]}

# --- List tags ---
@app.get("/tags")
def list_tags(x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    return list(db.keys())

# --- Show tag ---
@app.get("/tags/{tag_name}")
def get_tag(tag_name: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")
    return {"items": db[tag_name]}

# --- Delete tag ---
@app.delete("/tags/{tag_name}")
def delete_tag(tag_name: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    if tag_name not in db:
        raise HTTPException(404, detail="Tag not found")

    # Delete uploaded files
    for item in db[tag_name]:
        if item["type"] == "file":
            filepath = item["path"]
            if os.path.exists(filepath):
                os.remove(filepath)

    del db[tag_name]
    save_db(db)
    return {"status": "deleted"}

# --- Search tags ---
@app.get("/tags/search/{query}")
def search_tags(query: str, x_api_key: str = Header(...)):
    auth(x_api_key)
    db = load_db()
    return [k for k in db.keys() if query.lower() in k.lower()]

# --- Download file ---
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
