"""FastAPI (ASGI) — web framework benchmark, idiomatic defaults (stdlib JSONResponse).

Endpoint spec is shared by all web-* stacks (see docker/web-*/): /plaintext, /json, /compute,
/health, /version. /compute = 2000 chained SHA-256 rounds over a fixed seed (same work units
in every language, not the same wall time).
"""
import hashlib
import platform
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

SEED = b"benchmark-seed"
ROUNDS = 2000
VERSION = (
    f"python {platform.python_version()} fastapi {version('fastapi')} "
    f"uvicorn {version('uvicorn')} uvloop {version('uvloop')}"
)


@app.get("/plaintext", response_class=PlainTextResponse)
async def plaintext():
    return "Hello, World!"


@app.get("/json")
async def json_endpoint():
    return JSONResponse({"message": "Hello, World!"})


@app.get("/compute", response_class=PlainTextResponse)
async def compute():
    # CPU-bound work blocks the event loop on purpose: mirrors a real handler doing sync work.
    h = SEED
    for _ in range(ROUNDS):
        h = hashlib.sha256(h).digest()
    return h.hex()


@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"


@app.get("/version", response_class=PlainTextResponse)
async def version_endpoint():
    return VERSION
