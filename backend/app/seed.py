"""
Seed Firestore with the dummy BFSI dataset.

    python -m app.seed            # seed if not already seeded
    python -m app.seed --force    # overwrite
    python -m app.seed --dry-run  # print counts only

Uses Application Default Credentials (``gcloud auth application-default login``)
and ``GOOGLE_CLOUD_PROJECT``. Works against the Firestore emulator too when
``FIRESTORE_EMULATOR_HOST`` is set.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import get_settings
from app.core.datastore import load_seed, seed_firestore


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="re-seed even if already seeded")
    p.add_argument("--dry-run", action="store_true", help="only print what would be written")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    if a.dry_run:
        seed = load_seed(get_settings().time_shift_data)
        print({k: len(v) for k, v in seed.items() if isinstance(v, list)})
        return
    from google.cloud import firestore

    s = get_settings()
    db = firestore.AsyncClient(project=s.gcp_project, database=s.firestore_database)
    counts = await seed_firestore(db, force=a.force)
    print("Seeded:" if counts else "Already seeded (use --force to overwrite).", counts or "")


if __name__ == "__main__":
    asyncio.run(main())
