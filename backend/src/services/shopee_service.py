import asyncio
import hashlib
import hmac
import logging
import re
import time
from typing import Any, Optional, cast
import aiohttp
from fastapi import HTTPException

from ..exceptions import DomainException

from .redis_service import redis_mgr
from .managers import token_mgr, cache_mgr, conn_mgr
from ..config import get_config_value, get_config_int, get_config_float, get_config_bool
from ..models import (
    ShopeeResponse,
    ShopeeTokenResponse,
    ShpOrderList,
    OrderListT,
    ShpMassTrackingNumber,
    ShpOrderDetails,
    ShopeeOrder,
    ShopeeOrderResponse,
    WSMessageType,
)
from ..timezone import SHOPEE_AUTO_SYNC_PAUSE, in_daily_window
from . import queries
from .order_payload import build_order_responses

logger = logging.getLogger("backend.services.shopee")

SHOPEE_MAX_CONCURRENCY = get_config_int("SHOPEE_MAX_CONCURRENCY", 5)
SHOPEE_MAX_RETRIES = get_config_int("SHOPEE_MAX_RETRIES", 3)
SHOPEE_BACKOFF_DELAY = get_config_float("SHOPEE_BACKOFF_DELAY", 1.5)
SHOPEE_PAGE_SIZE = get_config_int("SHOPEE_PAGE_SIZE", 100)
SHOPEE_ORDER_CHUNK_SIZE = get_config_int("SHOPEE_ORDER_CHUNK_SIZE", 50)
SHOPEE_PACKAGE_CHUNK_SIZE = get_config_int("SHOPEE_PACKAGE_CHUNK_SIZE", 50)
SHOPEE_SYNC_WINDOW_DAYS = get_config_int("SHOPEE_SYNC_WINDOW_DAYS", 2)
# V2_ORDERS_DELTA Q48: background sync interval in seconds; 0 turns it off.
SHOPEE_AUTO_SYNC_SECONDS = get_config_int("SHOPEE_AUTO_SYNC_SECONDS", 300)
MOCK_ORDER_BYPASS = get_config_bool("MOCK_ORDER_BYPASS", False)



# Global session container to avoid circular imports with 'app'
class ShopeeClientSession:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None


shopee_client_session = ShopeeClientSession()

TOKEN_REFRESH_LOCK = asyncio.Lock()
SHOPEE_SEMAPHORE = asyncio.Semaphore(SHOPEE_MAX_CONCURRENCY)


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
        async with shopee_client_session.session.post(url, json=body, headers=headers) as resp:
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
            "[TOKEN SYSTEM EXCEPTION] Exception during Shopee token refresh network call: "
            f"{type(e).__name__}: {redact(e)}"
        )
        return None, None

    return None, None


async def shopee_request(
    path: str,
    params: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    method: str = "GET",
    retry_on_expiry: bool = True,
    max_429_retries: Optional[int] = None,
) -> Optional[ShopeeResponse]:

    # 1. Top-Level Circuit Breaker Check
    if cache_mgr.is_token_fatal():
        logger.critical(
            f"[CIRCUIT BREAKER] Aborting request to {path}. Token infrastructure is flagged as completely dead."
        )
        raise HTTPException(  # circuit open (F-M4): unavailable until re-authorized
            status_code=503,
            detail="Shopee API authentication infrastructure is broken. Re-authorization required.",
        )

    retries_limit = max_429_retries if max_429_retries is not None else SHOPEE_MAX_RETRIES
    backoff_delay = SHOPEE_BACKOFF_DELAY  # Starting delay for 429 backoff

    for attempt in range(retries_limit + 1):
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
            "shopee_request_enqueued",
            extra={"event": "shopee.request.enqueued", "method": method, "path": path},
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
                    if attempt < retries_limit:
                        logger.warning(
                            f"[429 TOO MANY REQUESTS] Gateway rate limit hit on {path}. Retrying in {backoff_delay}s... (Attempt {attempt + 1}/{retries_limit})"
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
                            raise RuntimeError("Shopee API returned an error with no message.")
                        ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", ret.message)
                        if ip_match:
                            current_ip = ip_match.group(0)
                        else:
                            ipv6_match = re.search(
                                r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
                                ret.message,
                            )
                            current_ip = ipv6_match.group(0) if ipv6_match else "unknown"
                        try:
                            await redis_mgr.set("shopee:current_ip", current_ip)
                            logger.info(f"Updated Shopee current IP in Redis: {current_ip}")
                        except Exception as e:
                            logger.error(f"Failed to set current IP in Redis: {e}")

                    # Handle Payload-level Rate Limits
                    if ret.error in ["request_limit_exceeded", "frequency_limited"]:
                        if attempt < retries_limit:
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
                            if cache_mgr.is_token_fatal():
                                logger.critical(
                                    f"[FAIL FAST] Worker on {path} woke up and detected fatal token state. Aborting."
                                )
                                raise HTTPException(
                                    status_code=503,
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
                                    cache_mgr.set_token_fatal()
                                    raise HTTPException(
                                        status_code=503,
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
            # No exc_info: the traceback repr would carry the signed URL.
            logger.error(
                f"[EXCEPTION] Critical error during Shopee call to {path}: "
                f"{type(e).__name__}: {redact(e)}"
            )
            return None

    return None


_URL_QUERY = re.compile(r"(https?://[^\s'\"?]+)\?[^\s'\"]*")
_SECRET_PARAM = re.compile(
    r"\b(access_token|refresh_token|sign|partner_key|code)=[^&\s'\"]+", re.IGNORECASE
)


def redact(value: object) -> str:
    """Strip query strings and credential parameters before text reaches the logs (F-H9).

    aiohttp errors embed the full request URL, which for Shopee carries ``access_token``
    and ``sign``. Log the exception type, path and Shopee request id instead.
    """
    text = str(value)
    text = _URL_QUERY.sub(r"\1?<redacted>", text)
    return _SECRET_PARAM.sub(r"\1=<redacted>", text)


async def fetch_sns_for_status(status: str, time_from: int, now: int) -> list[str]:
    """Worker to fetch order SNs for a specific status with pagination."""
    cursor = ""
    status_sns = []

    while True:
        params: dict[str, Any] = {
            "page_size": SHOPEE_PAGE_SIZE,
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
            raise HTTPException(  # upstream failure (F-M4)
                status_code=502,
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
        or not isinstance(detail_resp.response.order_list, list)
    ):
        logger.error(
            "shopee_order_chunk_failed",
            extra={"event": "shopee.order_chunk.failed", "order_count": len(chunk)},
        )
        # F-M3: a failed chunk must not count as synced; sync_shopee_orders stores the other
        # chunks, skips mark_synced and reports 502.
        raise HTTPException(status_code=502, detail="Failed to fetch order details from Shopee")

    order_details_list = detail_resp.response.order_list

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
        max_packages_per_req = SHOPEE_PACKAGE_CHUNK_SIZE
        for i in range(0, len(processed_packages), max_packages_per_req):
            package_chunk = processed_packages[i : i + max_packages_per_req]
            async with SHOPEE_SEMAPHORE:
                tracking_resp = await shopee_request(
                    path="/api/v2/logistics/get_mass_tracking_number",
                    method="POST",
                    body={"package_list": package_chunk},
                )

            if not (
                tracking_resp
                and not tracking_resp.error
                and isinstance(tracking_resp.response, ShpMassTrackingNumber)
            ):
                # Keep the stored tracking numbers of these packages rather than nulling them.
                fail_pkgs.update(p["package_number"] for p in package_chunk)
                continue
            for success_item in tracking_resp.response.success_list:
                tracking_map[success_item.package_number] = (
                    success_item.tracking_number,
                    success_item.pickup_code,
                )
            for fail_item in tracking_resp.response.fail_list:
                fail_pkgs.add(fail_item.package_number)

    return order_details_list, tracking_map, fail_pkgs


def build_shopee_order_responses(orders: list[ShopeeOrder]) -> list[ShopeeOrderResponse]:
    """Batched payloads for many orders (T4.5): bounded queries, independent of len(orders)."""
    with queries.get_db() as db:
        return build_order_responses(db, orders)


def build_shopee_order_response(order: ShopeeOrder) -> ShopeeOrderResponse:
    return build_shopee_order_responses([order])[0]


def _orders_visible_to(username: str, scope: str) -> list[ShopeeOrderResponse]:
    """Operators see only their own claimed orders, as on the WebSocket (A-9, F-M7)."""
    orders = (
        queries.get_all_shopee_order_data()
        if scope == "admin"
        else queries.get_shopee_order_data(username)
    )
    return build_shopee_order_responses(orders)


async def sync_shopee_orders(
    refresh: bool, username: Optional[str], scope: str = "client"
) -> list[ShopeeOrderResponse]:
    """Sync from Shopee unless the cache is fresh, then return the caller's orders.

    ``username`` is None for the background auto-sync: admins get the frame, nobody else.
    """
    start_time = time.perf_counter()

    if refresh:
        cache_mgr.invalidate()

    if cache_mgr.is_valid():
        return await asyncio.to_thread(_orders_visible_to, username, scope)

    async with cache_mgr.lock:
        if cache_mgr.is_valid():
            return await asyncio.to_thread(_orders_visible_to, username, scope)

        now = int(time.time())
        time_from = now - (SHOPEE_SYNC_WINDOW_DAYS * 24 * 60 * 60)
        STATUSES = ["READY_TO_SHIP", "PROCESSED", "SHIPPED", "COMPLETED", "CANCELLED"]

        # ==============================================================================
        # MOCK-DATA BYPASS
        # ==============================================================================
        # The Shopee fetch is wrapped in a try/except block. When MOCK_ORDER_BYPASS is
        # enabled (MOCK_ORDER_BYPASS=1/true), an offline or failed Shopee API does not
        # raise an exception or block serving orders from the database. This keeps the
        # synthetic orders (seeded via `python -m scripts.seed_dev`)
        # visible on both the client (WebSocket) and admin (HTTP) paths even when the
        # Shopee API is unreachable. sync_shopee_orders_to_db only ever inserts/updates
        # API orders and never deletes, so the unique mock order_sn survives syncs.
        #
        # When MOCK_ORDER_BYPASS is disabled (MOCK_ORDER_BYPASS=0, default), any exception
        # during the Shopee API sync is re-raised so upstream callers receive the error.
        #
        # HOW TO REMOVE THIS BYPASS COMPLETELY (Code Cleanup):
        # To remove this bypass mechanism entirely without relying on environment variables:
        # 1. In this function (`sync_shopee_orders`), remove the `try:` and `except Exception:`
        #    block wrapper, executing the fetch, chunk queries, `queries.sync_shopee_orders_to_db`,
        #    and `cache_mgr.mark_synced()` directly at the outer function scope.
        # 2. Remove `MOCK_ORDER_BYPASS = get_config_bool("MOCK_ORDER_BYPASS", False)` and its
        #    import if no longer used.
        # 3. Remove `MOCK_ORDER_BYPASS` from `.env` and `.env.example`.
        # 4. (Optional) Purge synthetic rows: `python -m scripts.seed_dev --reset` (dev only).
        # ==============================================================================
        try:
            tasks = [fetch_sns_for_status(status, time_from, now) for status in STATUSES]
            results = await asyncio.gather(*tasks)

            all_order_sns = []
            for status, res_list in zip(STATUSES, results):
                all_order_sns.extend(res_list)

            order_sns = list(dict.fromkeys(all_order_sns))
            # F-M2: also refresh orders still open locally but older than the list window,
            # so a cancellation or shipment upstream reaches the database.
            order_sns += await asyncio.to_thread(queries.local_active_order_sns, order_sns)

            if order_sns:
                chunk_size = SHOPEE_ORDER_CHUNK_SIZE
                chunks = [
                    order_sns[i : i + chunk_size] for i in range(0, len(order_sns), chunk_size)
                ]

                chunk_tasks = [fetch_chunk_details(chunk) for chunk in chunks]
                outcomes = await asyncio.gather(*chunk_tasks, return_exceptions=True)
                chunk_results = [o for o in outcomes if not isinstance(o, BaseException)]
                failures = [o for o in outcomes if isinstance(o, BaseException)]

                if chunk_results:
                    stale = await asyncio.to_thread(queries.sync_shopee_orders_to_db, chunk_results)
                    # C1: also after a partial sync, for what it did store.
                    closed = await asyncio.to_thread(queries.close_shipped_outbound)
                    if closed["outbound"]:
                        await conn_mgr.broadcast(WSMessageType.OUTBOUNDS, scope="admin")
                    for owner in sorted({*stale, *closed["owners"]}):  # V2_PICKING_DELTA Q81, Q83
                        await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, username=owner)
                if failures:  # partial sync: keep what arrived, never mark it complete
                    logger.warning(
                        "shopee_sync_partial",
                        extra={
                            "event": "shopee.sync.partial",
                            "failed_chunks": len(failures),
                            "total_chunks": len(chunks),
                        },
                    )
                    raise failures[0]

            cache_mgr.mark_synced()
        except Exception as exc:
            # If bypass is disabled (default), re-raise the exception
            if not get_config_bool("MOCK_ORDER_BYPASS", MOCK_ORDER_BYPASS):
                raise

            # The bypass lives here: swallow the API failure, skip mark_synced()
            # (so the next request retries the API), and fall through to serve
            # database orders.
            logger.warning(
                "shopee_sync_fallback",
                extra={
                    "event": "shopee.sync.fallback",
                    "reason": "Shopee API unreachable; serving database orders (mock order bypass enabled)",
                    "error": f"{type(exc).__name__}: {redact(exc)}",
                },
            )

        # Messaging systems
        await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")
        if username is not None:
            await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, username=username)

        return await asyncio.to_thread(_orders_visible_to, username or "", scope)


async def auto_sync_task(interval: Optional[float] = None) -> None:
    """Background Shopee sync every ``SHOPEE_AUTO_SYNC_SECONDS`` (V2_ORDERS_DELTA Q48).

    Same path as *Sync Shopee*, so it shares the sync lock and the cache: a sync that just ran
    is not repeated. It skips while the token circuit is open, until *Reset sync state* or a
    token save clears it, and in the nightly ``SHOPEE_AUTO_SYNC_PAUSE`` (C3); requested syncs
    still run then. A failed run is logged and the loop goes on.
    """
    seconds = SHOPEE_AUTO_SYNC_SECONDS if interval is None else interval
    if seconds <= 0:
        logger.info("shopee_auto_sync_disabled", extra={"event": "shopee.auto_sync.disabled"})
        return
    try:
        while True:
            await asyncio.sleep(seconds)
            if cache_mgr.is_token_fatal() or in_daily_window(SHOPEE_AUTO_SYNC_PAUSE):
                continue
            try:
                await sync_shopee_orders(refresh=False, username=None, scope="admin")
            except Exception as exc:
                logger.warning(
                    "shopee_auto_sync_failed",
                    extra={
                        "event": "shopee.auto_sync.failed",
                        "error": f"{type(exc).__name__}: {redact(exc)}",
                    },
                )
    except asyncio.CancelledError:
        logger.info("Shopee auto-sync task cancelled")
        raise


async def acquire_order(order_sn: str, username: str) -> None:
    try:
        success = await asyncio.to_thread(queries.acquire_order, order_sn, username)
    except ValueError as exc:
        raise DomainException(status_code=409, detail=str(exc)) from exc
    if not success:
        raise DomainException(
            status_code=404,
            detail="Order not found in database. Please fetch orders first.",
        )

    cache_mgr.invalidate()

    await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, username=username)
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")
