"""Merge every multi-bin SKU onto one bin before switching to STOCK_LOCATION_MODE=single (A-8b).

    docker compose -f compose.yaml -f compose.prod.yaml exec server \\
        python -m scripts.stock_merge_single --confirm

Each SKU's stock goes to its first bin in location order (unlocated last); every move is
logged as ``mode_merge``. Without --confirm it only reports what would change. Single mode
also merges lazily on the next adjustment, so this only makes the switch explicit.
"""

import argparse
import sys

from sqlalchemy import func, select

from src.models import Stock
from src.services.queries.engine import get_db
from src.services.queries.stocks import merge_all_to_single


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="apply the merge")
    args = parser.parse_args(argv)
    with get_db() as db:
        if not args.confirm:
            skus = (
                db.execute(select(Stock.sku).group_by(Stock.sku).having(func.count() > 1))
                .scalars()
                .all()
            )
            print(f"{len(skus)} SKU(s) have several bins; re-run with --confirm to merge")
            return 2
        merged = merge_all_to_single(db, actor="stock_merge_single")
        db.commit()
    print(f"merged {len(merged)} SKU(s): {merged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
