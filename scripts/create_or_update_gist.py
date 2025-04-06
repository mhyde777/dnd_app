import os
import json
from app.gist_utils import create_or_update_gist
from app.creature import CustomEncoder

def main():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    if not os.path.exists(data_dir):
        print("[ERROR] data/ directory does not exist.")
        return

    for filename in os.listdir(data_dir):
        if not filename.endswith(".json"):
            continue

        file_path = os.path.join(data_dir, filename)
        try:
            with open(file_path, "r") as f:
                content = json.load(f)

            print(f"[INFO] Uploading {filename} to Gist...")
            gist = create_or_update_gist(filename, content, description=f"Gist for {filename}")
            print(f"[OK] {filename} uploaded: {gist['html_url']}")

        except Exception as e:
            print(f"[ERROR] Failed to upload {filename}: {e}")

if __name__ == "__main__":
    main()
