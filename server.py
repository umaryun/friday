"""Jarvis server. Run locally:  .venv/bin/python server.py   (listens on port 8787)"""
import asyncio
import hmac
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

import agent
import cloud_tools
import config
from mac_bridge import mac
from mcp_hub import hub


@asynccontextmanager
async def lifespan(app):
    if not config.JARVIS_TOKEN or not config.GEMINI_API_KEY:
        raise SystemExit("Set JARVIS_TOKEN and GEMINI_API_KEY in .env first (see .env.example).")
    task = asyncio.create_task(cloud_tools.reminder_loop())
    hub.start()  # MCP servers from mcp_servers.json (GitHub, ...)
    yield
    task.cancel()
    await hub.close()


app = FastAPI(lifespan=lifespan)


def _authorized(token: str | None) -> bool:
    token = (token or "").removeprefix("Bearer ").strip()
    return bool(config.JARVIS_TOKEN) and hmac.compare_digest(token, config.JARVIS_TOKEN)


class AskRequest(BaseModel):
    text: str
    session: str = ""


@app.post("/ask")
async def ask(req: AskRequest, authorization: str | None = Header(None)):
    if not _authorized(authorization):
        raise HTTPException(401, "Wrong token")
    print(f"<- {req.text!r}")
    return await agent.handle(req.text.strip(), req.session)  # empty text (silence) ends the conversation


@app.get("/health")
async def health():
    return {"ok": True, "mac_online": mac.online, "mcp": hub.connected()}


@app.websocket("/mac")
async def mac_socket(ws: WebSocket):
    if not _authorized(ws.headers.get("authorization")):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        await mac.serve(ws)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8787")))
