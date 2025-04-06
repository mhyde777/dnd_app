import os
import requests
from dotenv import load_dotenv

# Load the environment variables from the .env file
load_dotenv()

# Get the GitHub personal access token from the environment
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not GITHUB_TOKEN:
    raise ValueError("GitHub token is not set. Please add it to the .env file.")

# The GitHub API URL for listing gists and creating gists
API_URL = "https://api.github.com/gists"

# The path to your local data folder where the JSON files are stored
DATA_FOLDER = "../data"  # Update this path if necessary

def delete_all_gists():
    """
    Deletes all Gists associated with your GitHub account.
    """
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    # Get the list of all gists
    response = requests.get(API_URL, headers=headers)
    if response.status_code == 200:
        gists = response.json()
        for gist in gists:
            gist_id = gist["id"]
            # Send DELETE request to delete the gist
            delete_response = requests.delete(f"{API_URL}/{gist_id}", headers=headers)
            if delete_response.status_code == 204:
                print(f"Gist {gist_id} deleted successfully.")
            else:
                print(f"Failed to delete Gist {gist_id}")
    else:
        print("Failed to fetch gists. Please check your token and try again.")

def create_gist(file_path):
    """
    Creates a new Gist from the given file in the data folder.
    """
    # Read the content of the file
    with open(file_path, 'r') as file:
        file_content = file.read()

    # Prepare Gist data
    gist_data = {
        "description": f"New Gist for {os.path.basename(file_path)}",
        "public": True,  # Set to False for private Gists
        "files": {
            os.path.basename(file_path): {
                "content": file_content
            }
        }
    }

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    # Send a POST request to create the Gist
    response = requests.post(API_URL, json=gist_data, headers=headers)

    if response.status_code == 201:
        print(f"Gist created for {file_path}")
    else:
        print(f"Failed to create Gist for {file_path}. Error: {response.text}")

def push_all_files_as_gists():
    """
    Pushes all JSON files in the data folder as new Gists.
    """
    for root, dirs, files in os.walk(DATA_FOLDER):
        for file in files:
            file_path = os.path.join(root, file)
            if file_path.endswith(".json"):  # Only process JSON files
                create_gist(file_path)

def main():
    """
    Main function to delete all Gists and repush new ones from the data folder.
    """
    # Step 1: Delete all Gists
    delete_all_gists()

    # Step 2: Push new Gists from the local data folder
    push_all_files_as_gists()

if __name__ == "__main__":
    main()

