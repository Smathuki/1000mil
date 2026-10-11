"""WhatsApp Cloud API webhook + a sandbox chat endpoint used by the web demo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import MessageLog
from ..services import messaging

router = APIRouter(tags=["messaging"])


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return challenge
    raise HTTPException(403, "Verification failed")


@router.post("/webhooks/whatsapp")
async def inbound(request: Request, db: Session = Depends(get_db)):
    handled = messaging.handle_whatsapp_webhook(db, await request.json())
    db.commit()
    return {"handled": len(handled)}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    peer: str = Field(default="web-demo", max_length=40)


@router.post("/messaging/chat")
def chat(body: ChatIn, db: Session = Depends(get_db)):
    """Same concierge brain as WhatsApp, for the in-app chat and for demos without a Meta account."""
    db.add(MessageLog(channel="web", direction="in", peer=body.peer, body=body.message))
    reply = messaging.reply_for(db, body.message)
    messaging.send(db, "web", body.peer, reply)
    db.commit()
    return {"reply": reply}
