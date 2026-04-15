import httpx
import os
import sys
import time

API_BASE = "http://localhost:5055"


def run_test():
    print("Testing PaperMind Watcher...")
    try:
        httpx.get(f"{API_BASE}/health", timeout=5.0)
        print("API is running.")
    except Exception:
        print("API not running, use make start-all")
        sys.exit(1)

    res = httpx.post(
        f"{API_BASE}/api/notebooks",
        json={"name": "Watcher Test Notebook", "description": "Testing the watcher"},
    )
    notebook_id = res.json()["id"]
    print(f"Notebook created! ID: {notebook_id}")

    watch_path = os.path.join(os.getcwd(), "test_papers")

    # Fetch existing watchers and delete if matching path
    folders_res = httpx.get(f"{API_BASE}/api/papermind/watch")
    if folders_res.status_code == 200:
        for folder in folders_res.json():
            if folder.get("path") == watch_path or folder.get("path") == watch_path + "/":
                print(f"Cleaning up old watcher: {folder.get('id')}")
                httpx.delete(
                    f"{API_BASE}/api/papermind/watch/{folder.get('id').split(':')[-1]}"
                )
                time.sleep(1)

    res = httpx.post(
        f"{API_BASE}/api/papermind/watch",
        json={
            "path": watch_path,
            "notebook_id": notebook_id,
            "recursive": False,
        },
    )

    if res.status_code >= 400:
        print(f"Failed to register watcher: {res.text}")
        sys.exit(1)

    print(f"Watching folder: {watch_path}")
    print("\nNow, drop the sample PDF into the folder to see it ingest!")
    print("   cp sample.pdf test_papers/")


if __name__ == "__main__":
    run_test()
