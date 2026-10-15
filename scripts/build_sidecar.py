#!/usr/bin/env python3
"""Builds the PyInstaller sidecar and copies it to src-tauri/binaries.

Cross-platform (Linux/Windows/macOS), stdlib only. The output name is
``grapi-api-<rust target triple>[.exe]``, which is what Tauri's ``externalBin``
expects. Run it with the interpreter that has backend/requirements.txt and
backend/requirements-build.txt installed.

If the repo has a local venv at ``env/`` and this script was started from a
plain system interpreter (not inside any venv), it re-executes itself with the
venv interpreter so ``cargo tauri build`` keeps working on a dev machine. In CI
there is no ``env/``, so ``sys.executable`` is used as is.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"


def _venv_python() -> Path | None:
    rel = Path("Scripts/python.exe") if IS_WINDOWS else Path("bin/python")
    cand = ROOT / "env" / rel
    return cand if cand.exists() else None


def _maybe_reexec_in_venv() -> None:
    venv_py = _venv_python()
    in_venv = sys.prefix != sys.base_prefix
    if venv_py is None or in_venv or os.environ.get("GRAPI_NO_VENV"):
        return
    raise SystemExit(subprocess.call([str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("could not find 'host:' in `rustc -vV` output")


def main() -> None:
    _maybe_reexec_in_venv()
    triple = target_triple()
    ext = ".exe" if IS_WINDOWS else ""

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "grapi-api",
        # grapi_core is imported as a package: put core/ and backend/ on the search path.
        "--paths", "core", "--paths", "backend",
        "--distpath", "dist", "--workpath", "build", "--specpath", "build",
        "--collect-all", "instagrapi",
        "--collect-submodules", "grapi_core",
        "--collect-submodules", "sqlalchemy.dialects.postgresql",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "pydantic",
        "--collect-all", "psycopg",
        "--collect-all", "psycopg_binary",
        "--hidden-import", "cryptography",
        "--hidden-import", "dotenv",
        "--hidden-import", "multipart",
        "backend/serve.py",
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)

    dest_dir = ROOT / "src-tauri" / "binaries"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"grapi-api-{triple}{ext}"
    dest.unlink(missing_ok=True)
    shutil.copy2(ROOT / "dist" / f"grapi-api{ext}", dest)
    dest.chmod(0o755)
    print(f"sidecar -> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
