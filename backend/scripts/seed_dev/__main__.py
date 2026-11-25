"""Seed synthetic development data.

    cd backend
    APP_ENV=development uv run python -m scripts.seed_dev            # add (idempotent)
    APP_ENV=development uv run python -m scripts.seed_dev --reset    # remove, then add
    APP_ENV=development uv run python -m scripts.seed_dev --stock-mode single
    APP_ENV=development uv run python -m scripts.seed_dev --scenario picking  # orders with picks

Refuses to run unless APP_ENV=development (production rules otherwise apply).
"""

import argparse
import sys

from .seed import SeedRefused, remove_seed, seed, seed_picking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="remove seeded rows first")
    parser.add_argument(
        "--stock-mode",
        choices=("multi", "single"),
        default="multi",
        help="stock layout: several bins per item (multi) or one (single)",
    )
    parser.add_argument(
        "--scenario", choices=("picking",), help="also add scannable orders with picks"
    )
    args = parser.parse_args(argv)
    try:
        if args.reset:
            print(f"removed: {remove_seed()}")
        print(f"seeded: {seed(stock_mode=args.stock_mode)}")
        if args.scenario == "picking":
            print(f"picking scenario: {seed_picking()} orders")
    except SeedRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
