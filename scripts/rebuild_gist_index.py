from app.gist_utils import list_gists, save_gist_index

def rebuild_index():
    index = {}

    gists = list_gists()
    for gist in gists:
        gist_id = gist["id"]
        for filename in gist.get("files", {}):
            if filename.endswith(".json"):
                index[filename] = gist_id

    save_gist_index(index)

if __name__ == "__main__":
    rebuild_index()
