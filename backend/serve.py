"""Sidecar entrypoint: runs the FastAPI app with uvicorn on 127.0.0.1.

Port comes from GRAPI_PORT (default 8765). Used by PyInstaller so the bundled
binary starts the API instead of importing a library module.
"""
import os
import threading
import time

import uvicorn

from main import app


def _exit_when_orphaned() -> None:
    """The onefile bootloader is our parent; if it is killed, exit too."""
    parent = os.getppid()
    while True:
        time.sleep(1)
        if os.getppid() != parent:
            os._exit(0)


def run() -> None:
    threading.Thread(target=_exit_when_orphaned, daemon=True).start()
    port = int(os.getenv("GRAPI_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    run()
