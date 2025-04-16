import requests, time
import json
import os
from typing import Optional
from PyQt5.QtWidgets import QMessageBox
from app.config import get_github_token
from app.creature import CustomEncoder

GITHUB_API_URL = "https://api.github.com"
INDEX_PATH = os.path.expanduser("~/.dnd_tracker_config/gist_index.json")


def load_gist_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r") as f:
            return json.load(f)
    return {}


def save_gist_index(index: dict):
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=4)


def create_or_update_gist(
    filename: str,
    content: dict,
    gist_id: Optional[str] = None,
    description: str = "DnD Encounter"
) -> dict:
    token = get_github_token()
    if not token:
        raise EnvironmentError("GitHub token not found. Please configure your token.")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "description": description,
        "public": False,
        "files": {
            filename: {
                "content": json.dumps(content, indent=4, cls=CustomEncoder)
            }
        }
    }

    index = load_gist_index()
    existing_gist_id = index.get(filename)

    # If this is not "last_state.json" and already exists, confirm overwrite
    if filename != "last_state.json" and existing_gist_id:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        reply = QMessageBox.question(
            None,
            "Overwrite Gist?",
            f"A Gist named '{filename}' already exists. Overwrite it?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            raise RuntimeError("User canceled Gist overwrite.")

    gist_id = gist_id or existing_gist_id

    if gist_id:
        response = requests.patch(f"{GITHUB_API_URL}/gists/{gist_id}", headers=headers, json=payload)
    else:
        response = requests.post(f"{GITHUB_API_URL}/gists", headers=headers, json=payload)

    response.raise_for_status()
    gist_data = response.json()

    # Update index and save
    index[filename] = gist_data["id"]
    save_gist_index(index)

    return gist_data

def load_gist_content(raw_url):
    """Load and return JSON content from a raw gist URL with a cache buster."""
    cache_buster = int(time.time())
    url = f"{raw_url}?t={cache_buster}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def list_gists() -> list:
    token = get_github_token()
    if not token:
        raise EnvironmentError("GitHub token not found. Please configure your token.")

    headers = {
        "Authorization": f"token {token}"
    }

    response = requests.get(f"{GITHUB_API_URL}/gists", headers=headers)
    response.raise_for_status()
    return response.json()

def delete_gist(gist_id: str) -> None:
    token = get_github_token()
    if not token:
        raise EnvironmentError("GitHub token not found. Please configure your token.")

    headers = {
        "Authorization": f"token {token}"
    }

    response = requests.delete(f"{GITHUB_API_URL}/gists/{gist_id}", headers=headers)
    response.raise_for_status()  # Will raise if deletion failed

def ensure_index_is_complete():
    index = load_gist_index()
    updated = False

    try:
        gists = list_gists()
        for gist in gists:
            gist_id = gist["id"]
            for filename in gist.get("files", {}):
                if filename.endswith(".json") and filename not in index:
                    index[filename] = gist_id
                    updated = True
    except Exception as e:
        print(f"[Warning] Failed to check for missing Gist index entries: {e}")
        return

    if updated:
        save_gist_index(index)
        print("[INFO] Gist index updated with missing entries")
