#!/usr/bin/env bash
# Builds the PyInstaller sidecar and copies it to src-tauri/binaries/grapi-api-<triple>.
set -euo pipefail

cd "$(dirname "$0")"

TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
PY="env/bin/python"
PYI="env/bin/pyinstaller"

[ -x "$PY" ] || { echo "env/bin/python not found" >&2; exit 1; }
[ -x "$PYI" ] || "$PY" -m pip install pyinstaller

# grapi_core is imported as a package: put core/ and backend/ on the search path.
"$PYI" --noconfirm --clean --onefile \
  --name grapi-api \
  --paths core --paths backend \
  --distpath dist --workpath build --specpath build \
  --collect-all instagrapi \
  --collect-submodules grapi_core \
  --collect-submodules sqlalchemy.dialects.postgresql \
  --collect-submodules uvicorn \
  --collect-submodules pydantic \
  --collect-all psycopg \
  --collect-all psycopg_binary \
  --hidden-import cryptography \
  --hidden-import dotenv \
  --hidden-import multipart \
  backend/serve.py

mkdir -p src-tauri/binaries
rm -f "src-tauri/binaries/grapi-api-$TRIPLE"
cp dist/grapi-api "src-tauri/binaries/grapi-api-$TRIPLE"
chmod +x "src-tauri/binaries/grapi-api-$TRIPLE"
echo "sidecar -> src-tauri/binaries/grapi-api-$TRIPLE"
