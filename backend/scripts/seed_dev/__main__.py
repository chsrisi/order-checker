"""Seed synthetic development data.

    cd backend
    APP_ENV=development uv run python -m scripts.seed_dev            # add (idempotent)
    APP_ENV=development uv run python -m scripts.seed_dev --reset    # remove, then add
    APP_ENV=development uv run python -m scripts.seed_dev --stock-mode single

Refuses to run unless APP_ENV=development (production rules otherwise apply).
"""

import argparse
import sys

from .seed import SeedRefused, remove_seed, seed


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
    args = parser.parse_args(argv)
    try:
        if args.reset:
            print(f"removed: {remove_seed()}")
        print(f"seeded: {seed(stock_mode=args.stock_mode)}")
    except SeedRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
