"""Firebase ID token verification dependency for GolaClips."""

import os
import json

import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from fastapi import Header, HTTPException

import database

_firebase_app = None


def _init_firebase():
    global _firebase_app
    if _firebase_app is not None:
        return

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON no está configurado en .env"
        )

    cred_dict = json.loads(service_account_json)
    cred = credentials.Certificate(cred_dict)
    _firebase_app = firebase_admin.initialize_app(cred)


async def get_current_user(authorization: str = Header(None)) -> dict:
    """FastAPI dependency: verify Firebase ID token and return the DB user dict."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Token de autenticación requerido. Iniciá sesión primero."
        )

    token = authorization.split(" ", 1)[1]

    try:
        _init_firebase()
        decoded = firebase_auth.verify_id_token(token)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {str(e)}")

    user = database.upsert_user(
        firebase_uid=decoded["uid"],
        email=decoded.get("email", ""),
        name=decoded.get("name", ""),
        avatar_url=decoded.get("picture", ""),
    )
    # Apply monthly free credits on every login (DB check prevents more than once/month)
    try:
        database.apply_monthly_free_credits(user["id"])
    except Exception:
        pass
    return user
