"""Sidecar entrypoint: runs the FastAPI app with uvicorn on 127.0.0.1.

Port comes from GRAPI_PORT (default 8765). Used by PyInstaller so the bundled
binary starts the API instead of importing a library module.
"""
import os
import threading
import time

import uvicorn

from main import app


def _parent_alive_windows(parent: int):
    """Returns a callable that is True while process `parent` is still running.

    On Windows os.getppid() never changes after the parent dies (PIDs are not
    re-parented), so the POSIX check below would never fire. Instead we hold a
    SYNCHRONIZE handle on the parent and poll it.
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    handle = kernel32.OpenProcess(0x00100000, 0, parent)  # SYNCHRONIZE
    if not handle:
        return lambda: False  # parent is already gone

    # WAIT_TIMEOUT (0x102) means the process is still running.
    return lambda: kernel32.WaitForSingleObject(handle, 0) == 0x102


def _exit_when_orphaned() -> None:
    """The onefile bootloader is our parent; if it is killed, exit too."""
    parent = os.getppid()
    if os.name == "nt":
        alive = _parent_alive_windows(parent)
    else:
        def alive() -> bool:
            return os.getppid() == parent
    while True:
        time.sleep(1)
        if not alive():
            os._exit(0)


def run() -> None:
    threading.Thread(target=_exit_when_orphaned, daemon=True).start()
    port = int(os.getenv("GRAPI_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    run()
