import uvicorn

if __name__ == "__main__":
    # IMPORTANT: reload must ignore data files the app writes at runtime
    # (local_db.json, uploads, logs). Otherwise every job progress write
    # triggers a server restart that KILLS running extraction jobs.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_includes=["*.py"],
        reload_excludes=[
            "local_db.json",
            "saved_projects.json",
            "uploads/*",
            "*.log",
            "*.txt",
        ],
    )
