"""Application FastAPI : page statique et route de reformulation en flux."""

import json
import logging
import os
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from execwrite.rewriter import DEFAULT_MODEL, Adjustment, RewriteError, stream_rewrite

load_dotenv()

logger = logging.getLogger("execwrite")

MAX_WORDS = 2000
# Garde-fou contre un texte énorme sans espaces, que le comptage de mots laisserait passer.
MAX_CHARS = 30_000

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="ExecWrite", docs_url=None, redoc_url=None, openapi_url=None)


class RewriteRequest(BaseModel):
    text: str = Field(max_length=MAX_CHARS)
    adjustment: Adjustment | None = None
    previous: str | None = Field(default=None, max_length=MAX_CHARS)


@lru_cache
def get_client() -> anthropic.AsyncAnthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="La clé API n'est pas configurée sur le serveur (ANTHROPIC_API_KEY).",
        )
    return anthropic.AsyncAnthropic(timeout=60, max_retries=1)


@app.post("/api/rewrite")
async def rewrite(
    request: RewriteRequest,
    client: Annotated[anthropic.AsyncAnthropic, Depends(get_client)],
) -> StreamingResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Collez d'abord un texte à reformuler.")
    if len(text.split()) > MAX_WORDS:
        raise HTTPException(status_code=422, detail=f"Le texte dépasse {MAX_WORDS} mots.")
    if request.adjustment and not request.previous:
        raise HTTPException(status_code=422, detail="Aucune version à ajuster.")

    model = os.getenv("EXECWRITE_MODEL") or DEFAULT_MODEL

    async def events() -> AsyncIterator[str]:
        try:
            async for chunk in stream_rewrite(
                client,
                text=text,
                adjustment=request.adjustment,
                previous=request.previous,
                model=model,
            ):
                yield _event(type="delta", text=chunk)
        except RewriteError as exc:
            # Le texte de l'utilisateur n'est jamais journalisé.
            logger.warning("Échec de reformulation : %s", exc.__cause__ or exc)
            yield _event(type="error", message=str(exc))
        else:
            yield _event(type="done")

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _event(**fields: str) -> str:
    return json.dumps(fields, ensure_ascii=False) + "\n"


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
