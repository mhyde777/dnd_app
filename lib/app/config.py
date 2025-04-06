# app/config.py
import os
import json
from dotenv import load_dotenv

load_dotenv()  # Automatically load .env in project root

CONFIG_DIR = os.path.expanduser("~/.dnd_tracker_config")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")

def get_github_token():
    # 1. Try token.json
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "r") as f:
            return json.load(f).get("token")
    
    # 2. Try .env fallback
    return os.getenv("GITHUB_TOKEN")

def save_github_token(token: str):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        json.dump({"token": token}, f)
