import os
from app.gist_utils import load_gist_index, load_gist_content, create_or_update_gist

# Set your GitHub username here (for building raw URLs)
GITHUB_USERNAME = "mhyde777"

def patch_gists_with_spellcasting():
    index = load_gist_index()

    for filename, gist_id in index.items():
        raw_url = f"https://gist.githubusercontent.com/{GITHUB_USERNAME}/{gist_id}/raw/{filename}"
        try:
            content = load_gist_content(raw_url)
            modified = False

            for group_key in ["players", "monsters"]:
                if group_key in content:
                    for creature in content[group_key]:
                        if "_spell_slots" not in creature:
                            creature["_spell_slots"] = {}
                            modified = True
                        if "_innate_slots" not in creature:
                            creature["_innate_slots"] = {}
                            modified = True

            if modified:
                print(f"[PATCH] Updating {filename}")
                create_or_update_gist(filename, content, description=f"Patched {filename} with spellcasting fields")
            else:
                print(f"[OK] {filename} already has spellcasting fields")

        except Exception as e:
            print(f"[ERROR] Failed to patch {filename}: {e}")

if __name__ == "__main__":
    patch_gists_with_spellcasting()

