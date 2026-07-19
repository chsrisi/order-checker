import asyncio
import hashlib
import hmac
import logging
import re
import time
from typing import Any, Optional, cast
import aiohttp
from fastapi import HTTPException
from sqlalchemy import select

from ..exceptions import DomainException

from .redis_service import redis_mgr
from .managers import token_mgr, cache_mgr, conn_mgr
from ..config import get_config_value
from ..models import (
    ShopeeResponse,
    ShopeeTokenResponse,
    ShpOrderList,
    OrderListT,
    ShpMassTrackingNumber,
    ShpOrderDetails,
    ShopeeOrder,
    ShopeeOrderResponse,
    ShopeeOrderItemBOMResponse,
    WSMessageType,
    WarehouseItem,
    ShopeeOrderRecipientResponse,
    ShopeeOrderInfoResponse,
)
from . import queries

logger = logging.getLogger("backend.services.shopee")


# Global session container to avoid circular imports with 'app'
class ShopeeClientSession:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None


shopee_client_session = ShopeeClientSession()

TOKEN_REFRESH_LOCK = asyncio.Lock()
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
    if cache_mgr.is_token_fatal():
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
                            if cache_mgr.is_token_fatal():
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
                                    cache_mgr.set_token_fatal()
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


def build_shopee_order_response(order: ShopeeOrder) -> ShopeeOrderResponse:
    info = order.info
    recipient = None
    item_list = []

    with queries.get_db() as db:
        if order.recipient_address:
            recipient = ShopeeOrderRecipientResponse.model_validate(
                order.recipient_address
            )

        def get_item_info(sku: str) -> tuple[Optional[str], Optional[str]]:
            item = db.execute(
                select(WarehouseItem).filter(WarehouseItem.sku == sku)
            ).scalar_one_or_none()
            if item:
                return item.item_name, item.location
            return None, None

        def flatten_bom_tree(node: dict) -> list[dict]:
            children = node.get("children")
            if children:
                flat = []
                for child in children:
                    flat.extend(flatten_bom_tree(child))
                return flat
            else:
                sku = node.get("sku", "")
                name = node.get("name", "")
                qty = node.get("quantity", 1)
                _, loc = get_item_info(sku)
                return [{
                    "component_sku": sku,
                    "component_name": name,
                    "quantity": qty,
                    "location": loc
                }]

        components_map = {}

        raw_item_list = order.item_list or []
        for raw_item in raw_item_list:
            sku = raw_item.model_sku or raw_item.item_sku or ""
            shopee_id = raw_item.item_id
            qty = raw_item.model_quantity_purchased or 1

            bom_tree = queries.resolve_shopee_order_bom_tree(shopee_id, sku, qty)

            if bom_tree:
                flat_components = flatten_bom_tree(bom_tree)
                for comp in flat_components:
                    comp_sku = comp["component_sku"]
                    comp_name = comp["component_name"]
                    comp_qty = comp["quantity"]
                    comp_loc = comp["location"]
                    key = (comp_sku, comp_name, comp_loc)
                    components_map[key] = components_map.get(key, 0) + comp_qty
            else:
                name, loc = get_item_info(sku)
                if not name:
                    name = raw_item.item_name or sku
                key = (sku, name, loc)
                components_map[key] = components_map.get(key, 0) + qty

        item_list = [
            ShopeeOrderItemBOMResponse(
                component_sku=sku,
                component_name=name,
                quantity=qty,
                location=loc
            )
            for (sku, name, loc), qty in components_map.items()
        ]

    info_response = [ShopeeOrderInfoResponse.model_validate(info)] if info else []

    return ShopeeOrderResponse(
        order_sn=order.order_sn,
        owner_user=order.owner_user,
        done=order.done,
        status=order.status,
        ship_by=order.ship_by,
        info=info_response,
        recipient_address=recipient,
        item_list=item_list,
    )

async def sync_shopee_orders(refresh: bool, username: str) -> list[ShopeeOrderResponse]:
    start_time = time.perf_counter()

    if refresh:
        cache_mgr.invalidate()

    if cache_mgr.is_valid():
        orders = queries.get_all_shopee_order_data()
        return [build_shopee_order_response(o) for o in orders]

    async with cache_mgr.lock:
        if cache_mgr.is_valid():
            orders = queries.get_all_shopee_order_data()
            return [build_shopee_order_response(o) for o in orders]

        now = int(time.time())
        time_from = now - (2 * 24 * 60 * 60)  # 2 days
        STATUSES = ["READY_TO_SHIP", "PROCESSED", "SHIPPED", "COMPLETED", "CANCELLED"]

        tasks = [fetch_sns_for_status(status, time_from, now) for status in STATUSES]
        results = await asyncio.gather(*tasks)

        all_order_sns = []
        for status, res_list in zip(STATUSES, results):
            all_order_sns.extend(res_list)

        order_sns = list(dict.fromkeys(all_order_sns))

        if order_sns:
            chunk_size = 50
            chunks = [
                order_sns[i : i + chunk_size]
                for i in range(0, len(order_sns), chunk_size)
            ]

            chunk_tasks = [fetch_chunk_details(chunk) for chunk in chunks]
            chunk_results = await asyncio.gather(*chunk_tasks)

            queries.sync_shopee_orders_to_db(chunk_results)

        # Messaging systems
        await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")
        await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, username=username)

        cache_mgr.mark_synced()

        orders = queries.get_all_shopee_order_data()
        final_orders = [build_shopee_order_response(o) for o in orders]
        return final_orders

async def acquire_order(order_sn: str, username: str) -> None:
    success = queries.acquire_order(order_sn, username)
    if not success:
        raise DomainException(
            status_code=404,
            detail="Order not found in database. Please fetch orders first.",
        )

    cache_mgr.invalidate()

    await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, username=username)
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, scope="admin")


