# Dungeons & Dragons Combat Tracker

## Dependecy management
This project uses **pipenv** as the primary dependency manager, driven by the `Pipfile`. A minimal `requirements.txt` is also provided for environments that prefer `pip`, and it includes the editable install of the local `lib/` directory (`dnd-app-lib`).
## Setup and running the app 
### Option A: pipenv (recommended)
1. Install pipenv if needed: `pip install --user pipenv`
2. Install dependencies and create the virtual environment (Python 3.10 recommended):
    ```bash
    pipenv install
    ```
3. Run the application:
    ```bash
    pipenv run python main.py 
    ```

### Option B: pip (alternative)
1. Create a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```
2. Install dependencies with pip:
    ```bash
    pip install --upgrade pip
    pip install -r requirements.txt
    ```
3. Launch the application:
    ```bash
    python main.py 
    ```

## Packaging the app {PyInstaller}
The packagin flow builds a standalone binary and Linux or Windows application folder layout.

1. Install dependencies (including PyIntsaller):
    ```bash
    pip install -r requirements.txt pyinstaller 
    ```
2. Build the executable and package directory:
    ```bash
    ../package.sh    
    ```
    or, on Windows (Git-Bash):
    ```bash
    ./package_WIN.sh
    ```
3. The bundled app is availalbe at:
    ```text
    dist/combat_tracker/
    ```
    A Linux-ready folder layout is staged at:
    ```text
    package/
    ```
    A Windows-readh folder layout is staged at:
    ```text
    package_win/
    ```

## Storage API Configuration
The app can optionally persist encounters to a storage API. Configuration is controlled by two environmental variables (e.g., in a `.env` file next to `main.py`):

* `USE_STORAGE_API_ONLY` - When truthy (`1`, `true`, etc.), the app routes all save/load flows through the storage API instead of local JSON files. Defaults to `0` (local files).
* `STORAGE_API_BASE` - Base URL of the Storage serves, such as `http://127.0.0.1:8000`. This is required when `USE_STORAGE_API_ONLY` is enabled.

### Example `.env` snippets

**Local files (default, no Storage service):**
```
USE_STORAGE_API_ONLY=0
```

**Storage API enabled:**
```
USE_STORAGE_API_ONLY=1 
STORAGE_API_BASE=http://127.0.0.1:800
```

### Running without the Storage service

Leave `USE_STORAGE_API_ONLY` unset (or set it to `0`) to kep using the built-in local JSOn files. If you enable `USE_STORAGE_API_ONLY` without providing `STORAGE_API_BASE`, the app will start but show a warning explaining how the to fix the configuration so you are not blocked while the Storage service is offline.
