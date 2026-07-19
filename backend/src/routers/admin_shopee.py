import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query

from ..models import (
    MessageResponse,
    ShopeeConfigResponse,
    ShopeeConfigUnlockRequest,
    ShopeeConfigUpdateRequest,
    TemporaryTokenResponse,
    User,
)
from ..dependencies import require_admin
from ..services.managers import redis_mgr, token_mgr, cache_mgr
from ..services.auth_service import verify_password

logger = logging.getLogger("backend.routers.admin_shopee")

shopee_config_router = APIRouter(prefix="/shopee-config", tags=["shopee configuration"])


@shopee_config_router.post(
    "/unlock",
    response_model=TemporaryTokenResponse,
    summary="Unlock Shopee credentials",
    description="Re-authenticates the administrator and returns a separate two-minute configuration token.",
    responses={
        401: {"description": "Incorrect admin password"},
        503: {"description": "Redis unavailable"},
    },
)
async def unlock_shopee_config(
    body: ShopeeConfigUnlockRequest,
    current_user: User = Depends(require_admin),
):
    if not verify_password(body.password, current_user.password_hash or ""):
        logger.warning(
            f"Shopee config unlock failed: Incorrect password for admin {current_user.username}"
        )
        raise HTTPException(status_code=401, detail="Incorrect password")

    config_token = secrets.token_hex(32)
    redis_key = f"cfg_token:{config_token}"
    try:
        await redis_mgr.set(redis_key, current_user.username, ex=120)
        logger.info(
            f"Admin {current_user.username} unlocked Shopee config view. Temporary token generated."
        )
    except Exception as exc:
        logger.exception("shopee_config_unlock_store_failed")
        raise HTTPException(status_code=503, detail="Redis connection failed") from exc

    return {"token": config_token, "expires_in": 120}


@shopee_config_router.post(
    "/lock",
    response_model=MessageResponse,
    summary="Lock Shopee credentials",
    description="Immediately invalidates a temporary configuration session.",
)
async def lock_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    try:
        await redis_mgr.delete(redis_key)
        logger.info(f"Admin {current_user.username} manually locked Shopee config session.")
    except Exception:
        logger.exception("shopee_config_lock_delete_failed")

    return {"message": "Config locked successfully"}


@shopee_config_router.get(
    "",
    response_model=ShopeeConfigResponse,
    summary="Read Shopee credentials",
    description="Returns credentials only when the temporary configuration token belongs to the current administrator.",
    responses={401: {"description": "Configuration session invalid or expired"}},
)
async def get_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    token_user = await redis_mgr.get(redis_key)
    if token_user != current_user.username:
        raise HTTPException(status_code=401, detail="Secure session expired or invalid")

    access_token = await token_mgr.get_token("ACCESS_TOKEN")
    refresh_token = await token_mgr.get_token("REFRESH_TOKEN")
    current_ip = await redis_mgr.get("shopee:current_ip")

    return {
        "access_token": access_token or "",
        "refresh_token": refresh_token or "",
        "current_ip": current_ip or "unknown",
    }


@shopee_config_router.post(
    "",
    response_model=MessageResponse,
    summary="Update Shopee credentials",
    description="Stores new tokens in Redis and resets synchronization circuit/cache state.",
    responses={401: {"description": "Configuration session invalid or expired"}},
)
async def save_shopee_config(
    body: ShopeeConfigUpdateRequest,
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    token_user = await redis_mgr.get(redis_key)
    if token_user != current_user.username:
        raise HTTPException(status_code=401, detail="Secure session expired or invalid")

    await token_mgr.set_token("ACCESS_TOKEN", body.access_token)
    await token_mgr.set_token("REFRESH_TOKEN", body.refresh_token)

    cache_mgr.set_token_fatal(False)
    cache_mgr.invalidate()

    logger.info(f"Admin {current_user.username} updated Shopee credentials.")
    return {"message": "Config saved successfully"}
