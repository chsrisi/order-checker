"""Q4 cutover (delta D5, T4.4): delete ALL open pick entries WITHOUT restoring stock.

Run once, in the maintenance window that ships the allocation table, after operators have
finished their open picks (docs/RELEASE.md). Entries from before that release carry no
allocation data, so a delete could not restore them correctly; clearing avoids guessing.

    docker compose -f compose.yaml -f compose.prod.yaml exec server \\
        python -m scripts.clear_open_pick_entries --confirm
"""

import argparse
import sys

from sqlalchemy import func, select

from src.models import PickItemEntry
from src.services.queries.engine import get_db
from src.services.queries.pick_items import clear_open_pick_entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="really delete the entries")
    args = parser.parse_args(argv)
    if not args.confirm:
        with get_db() as db:
            count = db.execute(select(func.count()).select_from(PickItemEntry)).scalar_one()
        print(f"{count} open pick entr(y/ies) would be deleted; re-run with --confirm")
        return 2
    count = clear_open_pick_entries(actor="cutover")
    print(f"deleted {count} open pick entr(y/ies); stock unchanged; logged as cutover_clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
