import os
import json
from app.gist_utils import create_or_update_gist
from app.creature import CustomEncoder

def main():
    # Set up the data directory path
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    
    # Check if the data directory exists
    if not os.path.exists(data_dir):
        print("[ERROR] data/ directory does not exist.")
        return

    # Iterate through all files in the data directory
    for filename in os.listdir(data_dir):
        # Only process .json files
        if not filename.endswith(".json"):
            continue

        # Get the full path to the file
        file_path = os.path.join(data_dir, filename)

        try:
            # Load the JSON content from the file
            with open(file_path, "r") as f:
                content = json.load(f)

            # Set the description to something meaningful for each file
            description = f"Gist for {filename}"

            print(f"[INFO] Uploading {filename} to Gist...")

            # Create a new Gist every time without overwriting
            gist = create_or_update_gist(filename, content, description=description)

            # Print the URL to the created Gist
            print(f"[OK] {filename} uploaded: {gist['html_url']}")

        except Exception as e:
            # Print error if there was an issue uploading the file
            print(f"[ERROR] Failed to upload {filename}: {e}")

if __name__ == "__main__":
    main()
