import os
import json
from dotenv import load_dotenv

load_dotenv()  # Automatically load .env in project root

CONFIG_DIR = os.path.expanduser("~/.dnd_tracker_config")
TOKEN_PATH = os.path.join(CONFIG_DIR, "token.json")

# def get_github_token():
#  # 1. Try token.json
#  if os.path.exists(TOKEN_PATH):
#      with open(TOKEN_PATH, "r") as f:
#          return json.load(f).get("token")
#  
#  # 2. Try .env fallback
#  return os.getenv("GITHUB_TOKEN")
#
# def save_github_token(token: str):
#  os.makedirs(CONFIG_DIR, exist_ok=True)
#  with open(TOKEN_PATH, "w") as f:
#      json.dump({"token": token}, f)

# ---- Storage API config ----
def get_storage_api_base() -> str:
    """
    Base URL for Storage API, e.g.:
      http://127.0.0.1:8000
      http://100.72.17.103:8000
    """
    return os.getenv("STORAGE_API_BASE", "").rstrip("/")

def use_storage_api_only() -> bool:
    """
    If set, we ignore any Gist codepaths entirely.
    """
    return os.getenv("USE_STORAGE_API_ONLY", "0").strip() not in ("", "0", "false", "False")
