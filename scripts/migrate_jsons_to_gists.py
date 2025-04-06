import os
import json
from app.gist_utils import create_or_update_gist
from dotenv import load_dotenv

load_dotenv()

LOCAL_JSON_DIR = os.path.join(os.path.dirname(__file__), "data")
ENCOUNTER_FILES = [f for f in os.listdir(LOCAL_JSON_DIR) if f.endswith(".json")]

for filename in ENCOUNTER_FILES:
    filepath = os.path.join(LOCAL_JSON_DIR, filename)
    with open(filepath, "r") as f:
        try:
            data = json.load(f)
            gist = create_or_update_gist(filename, data)
            raw_url = list(gist['files'].values())[0]['raw_url']
            print(f"✅ Uploaded {filename} to Gist: {raw_url}")
        except Exception as e:
            print(f"❌ Failed to upload {filename}: {e}")

