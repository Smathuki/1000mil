from __future__ import annotations

import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Partner, Property, Role, User


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    user = db.scalar(select(User).where(User.token_hash == hash_token(authorization[7:].strip())))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return user


def optional_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User | None:
    if not authorization:
        return None
    return current_user(authorization, db)


def require(*roles: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles and user.role != Role.admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return dep


def owned_property(property_id: int, db: Session, user: User) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Property not found")
    if user.role != Role.admin and prop.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your property")
    return prop


def partner_for(user: User, db: Session) -> Partner:
    partner = db.scalar(select(Partner).where(Partner.user_id == user.id))
    if partner is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Partner profile required")
    return partner
