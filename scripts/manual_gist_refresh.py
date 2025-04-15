from app.gist_utils import load_gist_index, save_gist_index, list_gists

index = load_gist_index()

for gist in list_gists():
    for filename in gist["files"]:
        if filename == "players.json":
            index["players.json"] = gist["id"]

save_gist_index(index)
