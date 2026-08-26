import os
import sys
import uvicorn

if __name__ == "__main__":
    # IMPORTANT: reload must only watch the app/ source directory, and ignore data
    # files (local_db.json*, uploads, logs, cache). Otherwise any file write or
    # test execution in the backend directory triggers an unexpected uvicorn reload
    # that abruptly kills active background extraction/build jobs.
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.join(backend_dir, "app")

    no_reload = "--no-reload" in sys.argv or os.environ.get("NO_RELOAD", "").lower() in ("1", "true")

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=not no_reload,
        reload_dirs=[app_dir] if not no_reload else None,
        reload_includes=["*.py"] if not no_reload else None,
        reload_excludes=[
            "local_db.json*",
            "*.tmp",
            "saved_projects.json",
            "uploads/*",
            "*.log",
            "*.txt",
            "*.png",
            "*.json",
            "*.csv",
            "brace_*",
            "debug/*",
            "scratch/*",
            "*.bak",
            "*.corrupt_backup",
        ] if not no_reload else None,
    )
