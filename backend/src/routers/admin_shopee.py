import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query

from ..models import User, ShopeeConfigUnlockRequest, ShopeeConfigUpdateRequest
from ..dependencies import require_admin
from ..services.managers import redis_mgr, token_mgr, cache_mgr
from ..services.auth_service import verify_password

logger = logging.getLogger("backend.routers.admin_shopee")

shopee_config_router = APIRouter(prefix="/shopee-config", tags=["admin_shopee_config"])


@shopee_config_router.post("/unlock")
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
    except Exception as e:
        logger.error(f"Failed to save shopee config temporary token in Redis: {e}")
        raise HTTPException(status_code=500, detail="Redis connection failed")

    return {"token": config_token, "expires_in": 120}


@shopee_config_router.post("/lock")
async def lock_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    try:
        await redis_mgr.delete(redis_key)
        logger.info(
            f"Admin {current_user.username} manually locked Shopee config session."
        )
    except Exception as e:
        logger.error(f"Failed to delete shopee config token from Redis: {e}")

    return {"message": "Config locked successfully"}


@shopee_config_router.get("")
async def get_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    token_user = await redis_mgr.get(redis_key)
    if not token_user:
        raise HTTPException(status_code=401, detail="Secure session expired or invalid")

    access_token = await token_mgr.get_token("ACCESS_TOKEN")
    refresh_token = await token_mgr.get_token("REFRESH_TOKEN")
    current_ip = await redis_mgr.get("shopee:current_ip")

    return {
        "access_token": access_token or "",
        "refresh_token": refresh_token or "",
        "current_ip": current_ip or "unknown",
    }


@shopee_config_router.post("")
async def save_shopee_config(
    body: ShopeeConfigUpdateRequest,
    token: str = Query(...),
    current_user: User = Depends(require_admin),
):
    redis_key = f"cfg_token:{token}"
    token_user = await redis_mgr.get(redis_key)
    if not token_user:
        raise HTTPException(status_code=401, detail="Secure session expired or invalid")

    await token_mgr.set_token("ACCESS_TOKEN", body.access_token)
    await token_mgr.set_token("REFRESH_TOKEN", body.refresh_token)

    cache_mgr.set_token_fatal(False)
    cache_mgr.invalidate()

    logger.info(f"Admin {current_user.username} updated Shopee credentials.")
    return {"message": "Config saved successfully"}
