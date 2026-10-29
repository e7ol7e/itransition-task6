"""Windows-compatible local server, after configuring .env and a database."""

import asyncio
import os
from pathlib import Path

import uvicorn

for line in Path(".env").read_text().splitlines():
    key, value = line.split("=", 1)
    os.environ.setdefault(key, value)
server = uvicorn.Server(uvicorn.Config("app:app", host="127.0.0.1", port=8066))
asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
