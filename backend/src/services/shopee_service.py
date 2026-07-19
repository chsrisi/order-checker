import asyncio
import hashlib
import hmac
import logging
import re
import time
from typing import Any, Optional, cast
import aiohttp
from fastapi import HTTPException

from .redis_service import redis_mgr
from .manager import token_mgr
from ..cache import shopee_cache
from ..config import get_config_value
from ..models import (
    ShopeeResponse,
    ShopeeTokenResponse,
    ShpOrderList,
    OrderListT,
    ShpMassTrackingNumber,
    ShpOrderDetails,
)

logger = logging.getLogger("backend.services.shopee")


# Global session container to avoid circular imports with 'app'
class ShopeeClientSession:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None


shopee_client_session = ShopeeClientSession()

# Global lock to prevent concurrent workers from refreshing the token at the same time
TOKEN_REFRESH_LOCK = asyncio.Lock()

# Limit concurrent Shopee requests to respect rate limits (e.g., max 5 at once)
SHOPEE_SEMAPHORE = asyncio.Semaphore(5)


async def refresh_shopee_token() -> tuple[str, str] | tuple[None, None]:
    logger.info("[TOKEN SYSTEM] Attempting to refresh Shopee access token...")
    shop_id_env = get_config_value("SHOP_ID")
    partner_id_env = get_config_value("PARTNER_ID")
    partner_key_env = get_config_value("PARTNER_KEY")
    refresh_token = await token_mgr.get_token("REFRESH_TOKEN")

    if not all([shop_id_env, partner_id_env, partner_key_env, refresh_token]):
        logger.error(
            "[TOKEN SYSTEM] Missing Shopee environment variables/secrets/tokens for token refresh"
        )
        return None, None

    shop_id = int(cast(str, shop_id_env))
    partner_id = int(cast(str, partner_id_env))
    partner_key = cast(str, partner_key_env).encode()

    timest = int(time.time())
    host = get_config_value("SHOPEE_URL")
    path = "/api/v2/auth/access_token/get"
    body = {
        "shop_id": shop_id,
        "refresh_token": refresh_token,
        "partner_id": partner_id,
    }

    tmp_base_string = f"{partner_id}{path}{timest}"
    base_string = tmp_base_string.encode()
    sign = hmac.new(partner_key, base_string, hashlib.sha256).hexdigest()
    url = f"{host}{path}?partner_id={partner_id}&timestamp={timest}&sign={sign}"

    headers = {"Content-Type": "application/json"}
    try:
        if shopee_client_session.session is None:
            raise RuntimeError("Shopee aiohttp session not initialized")
        async with shopee_client_session.session.post(
            url, json=body, headers=headers
        ) as resp:
            ret = ShopeeTokenResponse.model_validate(await resp.json())

            if ret.error:
                logger.error(
                    f"[TOKEN SYSTEM FAILED] Shopee Auth Server rejected refresh token: {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                )
                return None, None

            if ret.access_token and ret.refresh_token:
                await token_mgr.set_token("ACCESS_TOKEN", ret.access_token)
                await token_mgr.set_token("REFRESH_TOKEN", ret.refresh_token)
                logger.info(
                    "[TOKEN SYSTEM SUCCESS] Shopee tokens successfully updated in Redis keystore."
                )
                return ret.access_token, ret.refresh_token

    except Exception as e:
        logger.error(
            f"[TOKEN SYSTEM EXCEPTION] Exception during Shopee token refresh network call: {str(e)}"
        )
        return None, None

    return None, None


async def shopee_request(
    path: str,
    params: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    method: str = "GET",
    retry_on_expiry: bool = True,
    max_429_retries: int = 3,
) -> Optional[ShopeeResponse]:

    # 1. Top-Level Circuit Breaker Check
    if shopee_cache.is_token_fatal():
        logger.critical(
            f"[CIRCUIT BREAKER] Aborting request to {path}. Token infrastructure is flagged as completely dead."
        )
        raise HTTPException(
            status_code=500,
            detail="Shopee API authentication infrastructure is broken. Re-authorization required.",
        )

    backoff_delay = 1.5  # Starting delay for 429 backoff

    for attempt in range(max_429_retries + 1):
        host = get_config_value("SHOPEE_URL")
        partner_id = get_config_value("PARTNER_ID")
        partner_key = get_config_value("PARTNER_KEY")
        shop_id = get_config_value("SHOP_ID")
        access_token = await token_mgr.get_token("ACCESS_TOKEN")

        if host is None:
            logger.error("Shopee host URL is missing.")
            return None
        if partner_id is None:
            logger.error("Shopee PARTNER_ID is missing.")
            return None
        if partner_key is None:
            logger.error("Shopee PARTNER_KEY is missing.")
            return None
        if shop_id is None:
            logger.error("Shopee SHOP_ID is missing.")
            return None
        if access_token is None:
            logger.error("Shopee ACCESS_TOKEN is not initialized.")
            return None

        timest = int(time.time())
        tmp_base_string = f"{partner_id}{path}{timest}{access_token}{shop_id}"
        base_string = tmp_base_string.encode()
        sign = hmac.new(partner_key.encode(), base_string, hashlib.sha256).hexdigest()

        query_params = {
            "partner_id": partner_id,
            "timestamp": timest,
            "access_token": access_token,
            "shop_id": shop_id,
            "sign": sign,
        }
        if params:
            query_params.update(params)

        url = f"{host}{path}"
        headers = {"Content-Type": "application/json"}

        logger.debug(
            f"[REQ ENQUEUE] {method} {path} | Token snippet: ...{access_token[-6:] if access_token else 'None'}"
        )

        try:
            if shopee_client_session.session is None:
                raise RuntimeError("Shopee aiohttp session not initialized")

            if method.upper() == "GET":
                req_coro = shopee_client_session.session.get(
                    url, params=query_params, headers=headers
                )
            else:
                req_coro = shopee_client_session.session.post(
                    url, params=query_params, json=body, headers=headers
                )

            async with req_coro as resp:
                # Handle Gateway 429 errors
                if resp.status == 429:
                    if attempt < max_429_retries:
                        logger.warning(
                            f"[429 TOO MANY REQUESTS] Gateway rate limit hit on {path}. Retrying in {backoff_delay}s... (Attempt {attempt + 1}/{max_429_retries})"
                        )
                        await asyncio.sleep(backoff_delay)
                        backoff_delay *= 2
                        continue
                    else:
                        logger.error(
                            f"[429 EXHAUSTED] Max retries reached for rate limit on path: {path}"
                        )
                        return None

                ret = ShopeeResponse.model_validate(await resp.json())

                if ret.error:
                    logger.error(
                        f"[SHOPEE API ERROR] {ret.error} - {ret.message} (ReqID: {ret.request_id})"
                    )

                    if ret.error == "source_ip_undeclared":
                        if ret.message is None:
                            raise RuntimeError(
                                "Shopee API returned an error with no message."
                            )
                        ip_match = re.search(
                            r"\b(?:\d{1,3}\.){3}\d{1,3}\b", ret.message
                        )
                        if ip_match:
                            current_ip = ip_match.group(0)
                        else:
                            ipv6_match = re.search(
                                r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
                                ret.message,
                            )
                            current_ip = (
                                ipv6_match.group(0) if ipv6_match else "unknown"
                            )
                        try:
                            await redis_mgr.set("shopee:current_ip", current_ip)
                            logger.info(
                                f"Updated Shopee current IP in Redis: {current_ip}"
                            )
                        except Exception as e:
                            logger.error(f"Failed to set current IP in Redis: {e}")

                    # Handle Payload-level Rate Limits
                    if ret.error in ["request_limit_exceeded", "frequency_limited"]:
                        if attempt < max_429_retries:
                            logger.warning(
                                f"[429 API LIMIT] Application rate limit '{ret.error}' on {path}. Retrying in {backoff_delay}s..."
                            )
                            await asyncio.sleep(backoff_delay)
                            backoff_delay *= 2
                            continue
                        return ret

                    # Token Expiry handling with Double-Checked Locks and Circuit Breaking
                    if retry_on_expiry and ret.error in [
                        "invalid_access_token",
                        "invalid_acceess_token",
                        "error_access_token",
                    ]:
                        logger.warning(
                            f"[TOKEN EXPIRED] Detected expired token on task executing {path}."
                        )

                        async with TOKEN_REFRESH_LOCK:
                            # Worker check 1: Did a previous worker fail catastrophically while we were waiting?
                            if shopee_cache.is_token_fatal():
                                logger.critical(
                                    f"[FAIL FAST] Worker on {path} woke up and detected fatal token state. Aborting."
                                )
                                raise HTTPException(
                                    status_code=500,
                                    detail="Shopee authentication token refresh failed globally.",
                                )

                            # Worker check 2: Are we the chosen one to execute the refresh?
                            current_at = await token_mgr.get_token("ACCESS_TOKEN")
                            if current_at == access_token:
                                logger.info(
                                    "[TOKEN REFRESH] Lock acquired. Executing token renewal..."
                                )
                                new_at, _ = await refresh_shopee_token()

                                if not new_at:
                                    logger.critical(
                                        "[FATAL AUTH FAILURE] Refresh token is invalid/expired! Tripping circuit breaker."
                                    )
                                    shopee_cache.set_token_fatal()
                                    raise HTTPException(
                                        status_code=500,
                                        detail="Shopee Refresh Token has expired or is invalid. Manual merchant re-auth required.",
                                    )
                            else:
                                logger.info(
                                    "[TOKEN REFRESH SKIPPED] Token was already successfully updated by a concurrent worker."
                                )

                        logger.info(
                            f"[RETRYING REQUEST] Re-executing {path} with the active token configuration."
                        )
                        return await shopee_request(
                            path, params, body, method, retry_on_expiry=False
                        )

                logger.debug(f"[REQ SUCCESS] {path} | ReqID: {ret.request_id}")
                return ret

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"[EXCEPTION] Critical error during Shopee call to {path}: {str(e)}",
                exc_info=True,
            )
            return None

    return None


async def fetch_sns_for_status(status: str, time_from: int, now: int) -> list[str]:
    """Worker to fetch order SNs for a specific status with pagination."""
    cursor = ""
    status_sns = []

    while True:
        params: dict[str, Any] = {
            "page_size": 100,
            "time_range_field": "create_time",
            "time_from": time_from,
            "time_to": now,
            "order_status": status,
        }
        if cursor:
            params["cursor"] = cursor

        async with SHOPEE_SEMAPHORE:
            shopee_resp = await shopee_request(
                path="/api/v2/order/get_order_list",
                params=params,
            )

        if (
            not shopee_resp
            or shopee_resp.error
            or not isinstance(shopee_resp.response, ShpOrderList)
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Failed to fetch {status} orders from Shopee",
            )

        resp_data = shopee_resp.response
        status_sns.extend(item.order_sn for item in resp_data.order_list)

        if not resp_data.more:
            break
        cursor = resp_data.next_cursor or ""

    return status_sns


async def fetch_chunk_details(
    chunk: list[str],
) -> tuple[list[ShpOrderDetails], dict[str, tuple[str, str | None]], set[str]]:
    """Worker to fetch details and tracking numbers for a chunk of 50 orders."""
    sn_str = ",".join(chunk)

    async with SHOPEE_SEMAPHORE:
        detail_resp = await shopee_request(
            path="/api/v2/order/get_order_detail",
            params={
                "order_sn_list": sn_str,
                "response_optional_fields": "recipient_address,note,item_list,split_up,shipping_carrier,package_list,",
            },
        )

    if (
        not detail_resp
        or detail_resp.error
        or not isinstance(detail_resp.response, OrderListT)
    ):
        logger.error(f"Failed to fetch Shopee details for chunk: {sn_str}")
        return [], {}, set()

    order_details_list = detail_resp.response.order_list
    if not isinstance(order_details_list, list):
        return [], {}, set()

    # Prepare batch tracking payload
    processed_packages = [
        {"package_number": pkg.package_number}
        for detail in order_details_list
        if detail.order_status != "READY_TO_SHIP" and detail.package_list
        for pkg in detail.package_list
    ]

    tracking_map = {}
    fail_pkgs = set()

    if processed_packages:
        async with SHOPEE_SEMAPHORE:
            tracking_resp = await shopee_request(
                path="/api/v2/logistics/get_mass_tracking_number",
                method="POST",
                body={"package_list": processed_packages},
            )

        if tracking_resp and not tracking_resp.error and tracking_resp.response:
            if isinstance(tracking_resp.response, ShpMassTrackingNumber):
                for success_item in tracking_resp.response.success_list:
                    tracking_map[success_item.package_number] = (
                        success_item.tracking_number,
                        success_item.pickup_code,
                    )
                for fail_item in tracking_resp.response.fail_list:
                    fail_pkgs.add(fail_item.package_number)

    return order_details_list, tracking_map, fail_pkgs
