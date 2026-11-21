# Archive

Archived on **2026-11-21** at commit `2081206` (backend 0.4.0, client contract v1).

These files are historical records: reviews, decision logs and a design discussion whose
outcomes are implemented. They are kept unchanged, apart from a dated banner and fixed
relative links, so references from code comments and the implementation plan still make
sense (for example "delta D4.3", "F-M8", "STOCK_MODEL_DISCUSSION §8").

They are **not maintained** and do not describe the current system. For that, read
[SYSTEM_REFERENCE.md](../SYSTEM_REFERENCE.md) and the guides listed in
[PROJECT.md](../PROJECT.md).

| File | What it was | Dated |
|---|---|---|
| [CODE_REVIEW.md](CODE_REVIEW.md) | First hardening review: resolved findings and remaining risks | 2026-07-19, commit `82a9801` |
| [BRANCH_SPLIT_REVIEW.md](BRANCH_SPLIT_REVIEW.md) | Branch-split readiness review: API/flow map, frozen client contract, findings (F-*), split plan | 2026-11-20, commit `187122c` |
| [BRANCH_SPLIT_DELTA.md](BRANCH_SPLIT_DELTA.md) | Decisions taken after that review (A-*, D1–D5, P-*) | 2026-11-20 |
| [STOCK_MODEL_DISCUSSION.md](STOCK_MODEL_DISCUSSION.md) | Pick deduction/restore design and location-mode policy (implemented in T4.3) | 2026-11-20 |

Finding and decision IDs used across the code (`F-H3`, `A-10b`, `D4.3`, `P-4`, …) are
defined in these files.
