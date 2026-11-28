"""Delete every pick entry without an order and return its stock (V2_PICKING_SPEC §4.5, Q66).

The v2 app has no such entries and does not show them; they come from v1. Run it when the last v1
device stops, or when a v1 pool row is stuck. Picks that belong to an order are not touched.

    docker compose -f compose.yaml -f compose.prod.yaml exec server \\
        python -m scripts.release_unassigned_picks            # count only
    docker compose -f compose.yaml -f compose.prod.yaml exec server \\
        python -m scripts.release_unassigned_picks --confirm
"""

import argparse
import sys

from src.services.queries.pick_items import count_unassigned_picks, release_unassigned_picks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="really release the entries")
    args = parser.parse_args(argv)
    if not args.confirm:
        count = count_unassigned_picks()
        print(f"{count} unassigned pick entr(y/ies) would be released; re-run with --confirm")
        return 2
    count = release_unassigned_picks(actor="release_unassigned_picks")
    print(f"released {count} unassigned pick entr(y/ies); their stock is back (pick_restore)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
