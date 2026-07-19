import asyncio
import logging
import secrets
import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import (
    User,
    ShopeeOrderResponse,
    ShopeeOrder,
    ShopeeOrderRecipientAddress,
    ShopeeOrderItemList,
    ShopeeOrderInfo,
    WSMessageType,
    ShopeeConfigUnlockRequest,
    ShopeeConfigUpdateRequest,
)
from ..dependencies import get_db, get_current_user
from ..cache import shopee_cache
from ..services.redis_service import redis_mgr
from ..services.manager import conn_mgr, token_mgr
from ..services.queries import get_all_shopee_order_data
from ..services.bom_service import build_shopee_order_response
from ..services.auth_service import verify_password
from ..services.shopee_service import (
    fetch_sns_for_status,
    fetch_chunk_details,
)

logger = logging.getLogger("backend.routers.shopee")

router = APIRouter(tags=["shopee"])


@router.get("/shopee/orders", response_model=List[ShopeeOrderResponse])
async def get_shopee_orders(
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start_time = time.perf_counter()
    logger.info(
        f"[START] User '{current_user.username}' requested Shopee synchronization. (refresh={refresh})"
    )

    if refresh:
        shopee_cache.invalidate()

    # 1. Fast path check
    if shopee_cache.is_valid():
        logger.info(
            "[CACHE HIT] Local order cache valid. Serving directly from database."
        )
        res = get_all_shopee_order_data(db)
        logger.info(
            f"[END] Cache hit pipeline complete. Returned {len(res)} orders in {time.perf_counter() - start_time:.4f}s."
        )
        return [build_shopee_order_response(o, db) for o in res]

    logger.debug(
        "[CACHE MISS] Cache is invalid or expired. Attempting synchronization lock..."
    )

    async with shopee_cache.lock:
        # Double-Checked Locking check
        if shopee_cache.is_valid():
            logger.info(
                "[CACHE HIT] Cache valid inside lock block (parallel sync resolved). Avoiding dual sync."
            )
            return [
                build_shopee_order_response(o, db)
                for o in get_all_shopee_order_data(db)
            ]

        now = int(time.time())
        time_from = now - (2 * 24 * 60 * 60)  # 2 days
        STATUSES = ["READY_TO_SHIP", "PROCESSED", "SHIPPED", "COMPLETED", "CANCELLED"]

        logger.info(
            f"[STAGE 1] Querying order lists for statuses: {STATUSES} in parallel..."
        )
        stage1_start = time.perf_counter()

        tasks = [fetch_sns_for_status(status, time_from, now) for status in STATUSES]
        results = await asyncio.gather(*tasks)

        all_order_sns = []
        for status, res_list in zip(STATUSES, results):
            logger.debug(
                f" -> Found {len(res_list)} matching items for status [{status}]"
            )
            all_order_sns.extend(res_list)

        order_sns = list(dict.fromkeys(all_order_sns))
        logger.info(
            f"[STAGE 1 DONE] Discovered {len(order_sns)} unique order SNs across statuses in {time.perf_counter() - stage1_start:.4f}s."
        )

        if order_sns:
            # Step B: Parallel Fetching of Detailed Info
            chunk_size = 50
            chunks = [
                order_sns[i : i + chunk_size]
                for i in range(0, len(order_sns), chunk_size)
            ]
            logger.info(
                f"[STAGE 2] Segmented orders into {len(chunks)} chunks of max {chunk_size}. Processing chunk payloads concurrently..."
            )

            stage2_start = time.perf_counter()
            chunk_tasks = [fetch_chunk_details(chunk) for chunk in chunks]

            chunk_results = await asyncio.gather(*chunk_tasks)
            logger.info(
                f"[STAGE 2 DONE] Fetched details for all chunks in {time.perf_counter() - stage2_start:.4f}s."
            )

            # --- Database Processing Phase (Batching) ---
            logger.info(
                "[STAGE 3] Loading state tables to complete batch processing strategy..."
            )
            stage3_start = time.perf_counter()

            existing_orders = {
                o.order_sn: o
                for o in db.execute(
                    select(ShopeeOrder).filter(ShopeeOrder.order_sn.in_(order_sns))
                )
                .scalars()
                .all()
            }
            logger.debug(
                f" -> Cached {len(existing_orders)} pre-existing ShopeeOrder records from local storage map."
            )

            all_package_nums = [
                pkg.package_number
                for details, _, _ in chunk_results
                for detail in details
                if detail.package_list
                for pkg in detail.package_list
            ]
            existing_infos = {
                info.package_number: info
                for info in db.execute(
                    select(ShopeeOrderInfo).filter(
                        ShopeeOrderInfo.package_number.in_(all_package_nums)
                    )
                )
                .scalars()
                .all()
            }
            logger.debug(
                f" -> Cached {len(existing_infos)} pre-existing ShopeeOrderInfo package rows from local storage map."
            )

            inserted_orders = updated_orders = inserted_packages = updated_packages = 0

            for chunk_idx, (order_details_list, tracking_map, fail_pkgs) in enumerate(
                chunk_results, start=1
            ):
                logger.debug(
                    f" Processing dataset chunk {chunk_idx}/{len(chunks)} ({len(order_details_list)} records)"
                )

                for order_detail in order_details_list:
                    db_order = existing_orders.get(order_detail.order_sn)

                    if not db_order:
                        db_order = ShopeeOrder(
                            order_sn=order_detail.order_sn, owner_user=None
                        )
                        db_order.split_up = order_detail.split_up
                        db_order.status = order_detail.order_status
                        db_order.ship_by = order_detail.ship_by_date
                        db_order.shipping_carrier = (
                            order_detail.package_list[0].shipping_carrier
                            if order_detail.package_list
                            else None
                        )
                        db.add(db_order)
                        inserted_orders += 1

                        if order_detail.recipient_address:
                            addr = ShopeeOrderRecipientAddress(
                                order_sn=order_detail.order_sn,
                                name=order_detail.recipient_address.name,
                                city=order_detail.recipient_address.city,
                            )
                            db.add(addr)

                        for item in order_detail.item_list:
                            if item.model_id == 0:
                                item.model_id = item.model_name = item.model_sku = None
                            db_item = ShopeeOrderItemList(
                                order_sn=order_detail.order_sn,
                                item_id=item.item_id,
                                item_name=item.item_name,
                                item_sku=item.item_sku,
                                model_id=item.model_id,
                                model_name=item.model_name,
                                model_sku=item.model_sku,
                                model_quantity_purchased=item.model_quantity_purchased,
                                image_url=item.image_info.image_url
                                if item.image_info
                                else None,
                            )
                            db.add(db_item)
                    else:
                        db_order.status = order_detail.order_status
                        db_order.shipping_carrier = (
                            order_detail.package_list[0].shipping_carrier
                            if order_detail.package_list
                            else None
                        )
                        updated_orders += 1

                    if order_detail.package_list:
                        for pkg in order_detail.package_list:
                            if pkg.package_number in fail_pkgs:
                                continue

                            info = existing_infos.get(pkg.package_number)
                            tracking_number = pickup_code = None

                            if (
                                order_detail.order_status != "READY_TO_SHIP"
                                and pkg.package_number in tracking_map
                            ):
                                tracking_number, pickup_code = tracking_map[
                                    pkg.package_number
                                ]

                            if not info:
                                info = ShopeeOrderInfo(
                                    order_sn=order_detail.order_sn,
                                    package_number=pkg.package_number,
                                    logistics_status=pkg.logistics_status,
                                    tracking_number=tracking_number,
                                    pickup_code=pickup_code,
                                    note=order_detail.note,
                                )
                                db.add(info)
                                inserted_packages += 1
                            else:
                                info.logistics_status = pkg.logistics_status
                                if order_detail.order_status != "READY_TO_SHIP":
                                    info.tracking_number = tracking_number
                                    info.pickup_code = pickup_code
                                info.note = order_detail.note
                                updated_packages += 1

            logger.info(
                f"[DB MAP COMPLETE] Analytics: Orders (+{inserted_orders}/~{updated_orders}) | Packages (+{inserted_packages}/~{updated_packages})"
            )
            db.commit()
            logger.info(
                f"[STAGE 3 DONE] Persisted all changes to relational storage engine in {time.perf_counter() - stage3_start:.4f}s."
            )

        # Messaging systems
        await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")
        await conn_mgr.send_to_user(
            WSMessageType.SHOPEE_ORDERS, db, current_user.username
        )

        shopee_cache.mark_synced()

        final_orders = get_all_shopee_order_data(db)
        logger.info(
            f"[END] Full sync routine terminated successfully. Total runtime: {time.perf_counter() - start_time:.4f}s. Returning {len(final_orders)} data objects."
        )
        return [build_shopee_order_response(o, db) for o in final_orders]


@router.post("/shopee/orders/acquire")
async def acquire_order(
    order_sn: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logger.info(f"User {current_user.username} acquiring order {order_sn}")

    db_order = (
        db.execute(select(ShopeeOrder).filter(ShopeeOrder.order_sn == order_sn))
        .scalars()
        .first()
    )

    if not db_order:
        raise HTTPException(
            status_code=404,
            detail="Order not found in database. Please fetch orders first.",
        )

    db_order.owner_user = current_user.username
    db.commit()
    shopee_cache.invalidate()

    # broadcast WS updates
    await conn_mgr.send_to_user(WSMessageType.SHOPEE_ORDERS, db, current_user.username)
    await conn_mgr.broadcast(WSMessageType.SHOPEE_ORDERS, db, scope="admin")

    return {"message": "Order assigned successfully", "order_sn": order_sn}


@router.post("/shopee/reset-cache-state")
async def reset_shopee_cache_state(
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    logger.warning(f"Admin {current_user.username} resetting Shopee cache state")
    shopee_cache.set_token_fatal(False)
    shopee_cache.invalidate()
    return {"message": "Shopee cache state reset successfully"}


@router.post("/admin/shopee-config/unlock")
async def unlock_shopee_config(
    body: ShopeeConfigUnlockRequest,
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if not verify_password(body.password, current_user.password_hash or ""):
        logger.warning(
            f"Shopee config unlock failed: Incorrect password for admin {current_user.username}"
        )
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Generate a secure 2-min temporary config token in Redis
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


@router.post("/admin/shopee-config/lock")
async def lock_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    redis_key = f"cfg_token:{token}"
    try:
        await redis_mgr.delete(redis_key)
        logger.info(
            f"Admin {current_user.username} manually locked Shopee config session."
        )
    except Exception as e:
        logger.error(f"Failed to delete shopee config token from Redis: {e}")

    return {"message": "Config locked successfully"}


@router.get("/admin/shopee-config")
async def get_shopee_config(
    token: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    # Verify short-lived token in Redis
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


@router.post("/admin/shopee-config")
async def save_shopee_config(
    body: ShopeeConfigUpdateRequest,
    token: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    if current_user.scope != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    # Verify short-lived token in Redis
    redis_key = f"cfg_token:{token}"
    token_user = await redis_mgr.get(redis_key)
    if not token_user:
        raise HTTPException(status_code=401, detail="Secure session expired or invalid")

    await token_mgr.set_token("ACCESS_TOKEN", body.access_token)
    await token_mgr.set_token("REFRESH_TOKEN", body.refresh_token)

    # Reset Shopee token fatal status / circuit breaker
    shopee_cache.set_token_fatal(False)
    shopee_cache.invalidate()

    logger.info(
        f"Admin {current_user.username} successfully updated Shopee credentials."
    )
    return {"message": "Shopee credentials updated successfully"}
