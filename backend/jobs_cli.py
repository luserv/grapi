#!/usr/bin/env python3
"""
Estado de las descargas masivas de galerías, desde la terminal.

Consulta el backend (FastAPI) por HTTP, así que el server tiene que estar
corriendo. Usa solo la stdlib (no necesita instalar nada).

Uso:
    python jobs_cli.py                 # lista los jobs una vez
    python jobs_cli.py --watch         # refresca cada 2s (Ctrl-C para salir)
    python jobs_cli.py --cancel <id>   # cancela un job en curso

Variables de entorno:
    API_BASE   URL del backend (default http://localhost:8000)
    WATCH_SECS Segundos entre refrescos en --watch (default 2)
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

API = os.getenv("API_BASE", "http://localhost:8000").rstrip("/")
WATCH_SECS = float(os.getenv("WATCH_SECS", "2"))

# Colores ANSI (se desactivan si la salida no es una terminal).
_TTY = sys.stdout.isatty()
def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s

STATUS_STYLE = {
    "running":   ("36", "▶ corriendo"),
    "done":      ("32", "✓ listo"),
    "cancelled": ("33", "■ cancelado"),
    "error":     ("31", "✗ error"),
}


def _get(path):
    with urllib.request.urlopen(API + path, timeout=10) as r:
        return json.load(r)


def _post(path):
    req = urllib.request.Request(API + path, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _bar(idx, total, width=24):
    if not total:
        return "·" * width
    filled = int(width * idx / total)
    return _c("32", "█" * filled) + "·" * (width - filled)


def _fmt_job(j):
    code, label = STATUS_STYLE.get(j["status"], ("0", j["status"]))
    head = f"{_c(code, label):<22} {_c('2', j['id'][:8])}"
    pct = f"{(j['idx'] / j['total'] * 100):4.0f}%" if j["total"] else "  –"
    line = f"  {head}  [{_bar(j['idx'], j['total'])}] {j['idx']}/{j['total']} {pct}"
    counts = (f"     ↳ {_c('32', str(j['downloaded']) + ' bajados')} · "
              f"{j['skipped']} salteados · {_c('31', str(j['failed']) + ' fallaron')}")
    parts = [line, counts]
    if j["status"] == "running" and (j.get("current") or j.get("detail")):
        cur = f"@{j['current']}" if j.get("current") else ""
        parts.append(f"     {_c('36', cur)}  {_c('2', j.get('detail') or '')}")
    if j.get("error"):
        parts.append(f"     {_c('31', j['error'])}")
    return "\n".join(parts)


def show():
    try:
        data = _get("/api/download-jobs")
    except urllib.error.URLError as e:
        print(_c("31", f"No se pudo conectar a {API} — ¿está el backend corriendo? ({e})"))
        return
    jobs = data.get("jobs", [])
    if not jobs:
        print(_c("2", "  (no hay descargas registradas)"))
        return
    # corriendo primero, luego por inicio descendente
    jobs.sort(key=lambda j: (j["status"] != "running", j.get("started_at") or ""), reverse=False)
    for j in jobs:
        print(_fmt_job(j))
        print()


def main():
    args = sys.argv[1:]
    if "--cancel" in args:
        try:
            jid = args[args.index("--cancel") + 1]
        except IndexError:
            print("Uso: python jobs_cli.py --cancel <job_id>")
            return 2
        try:
            _post(f"/api/download-all/cancel?job_id={jid}")
            print(_c("33", f"Cancelación enviada a {jid[:8]}"))
        except urllib.error.HTTPError as e:
            print(_c("31", f"No se pudo cancelar: {e}"))
        return 0

    if "--watch" in args:
        try:
            while True:
                os.system("clear" if os.name != "nt" else "cls")
                print(_c("1", f"Descargas masivas — {API}") +
                      _c("2", f"   (refresca cada {WATCH_SECS:g}s · Ctrl-C para salir)\n"))
                show()
                time.sleep(WATCH_SECS)
        except KeyboardInterrupt:
            return 0

    show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
