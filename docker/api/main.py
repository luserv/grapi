"""FastAPI app — instalado como paquete grapi-core."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sync
import threading
import uuid
import requests as req_lib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from grapi_core import repository
from grapi_core.config import settings
from grapi_core.database import SessionLocal, session_scope, engine, Base
from grapi_core.instagram import autenticar_instagram, obtener_usuarios
from grapi_core.downloader import download_user, download_many, list_downloads, pacing_for, _now_iso

# Create DB tables on first startup (SQLite idempotente)
Base.metadata.create_all(bind=engine)

@app.get("/api/health")
def health():
    """Health check endpoint para el sidecar de Tauri."""
    return {"status": "ok", "db": "ok" if engine else "unknown"}

app = FastAPI(title="Instagram Followers Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
