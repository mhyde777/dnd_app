import requests
import json
import os
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = "https://api.github.com"


def create_or_update_gist(
    filename: str,
    content: dict,
    gist_id: Optional[str] = None,
    description: str = "DnD Encounter"
) -> dict:
    if not GITHUB_TOKEN:
        raise EnvironmentError("GITHUB_TOKEN environment variable not set.")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    payload = {
        "description": description,
        "public": False,
        "files": {
            filename: {
                "content": json.dumps(content, indent=4)
            }
        }
    }

    if gist_id:
        response = requests.patch(f"{GITHUB_API_URL}/gists/{gist_id}", headers=headers, json=payload)
    else:
        response = requests.post(f"{GITHUB_API_URL}/gists", headers=headers, json=payload)

    response.raise_for_status()
    return response.json()


def load_gist_content(raw_url: str) -> dict:
    response = requests.get(raw_url)
    response.raise_for_status()
    return json.loads(response.text)


def list_gists() -> list:
    if not GITHUB_TOKEN:
        raise EnvironmentError("GITHUB_TOKEN environment variable not set.")

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}"
    }

    response = requests.get(f"{GITHUB_API_URL}/gists", headers=headers)
    response.raise_for_status()
    return response.json()
