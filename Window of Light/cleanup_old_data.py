#!/usr/bin/env python3
"""
Cleanup script for old database records (older than 30 days)
Run daily via cron: 0 3 * * * /path/to/cleanup_old_data.py

The database URL MUST be supplied via the ``DATABASE_URL`` env var; the script
intentionally does NOT ship a hardcoded fallback credential.
"""
import os
import re
import sys
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cleanup")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.error(
        "DATABASE_URL is not set. Export it before running cleanup, e.g.\n"
        "  export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/window_of_light'"
    )
    sys.exit(2)

# Allow-list of table names used by the stats query below.
_STATS_TABLES = ("products", "price_history", "raw_posts", "categories", "channels")
_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
for _t in _STATS_TABLES:
    if not _SAFE_IDENT.match(_t):
        raise RuntimeError(f"Unsafe stats table name: {_t!r}")

DAYS_TO_KEEP = 30
CUTOFF_DATE = datetime.utcnow() - timedelta(days=DAYS_TO_KEEP)


def cleanup():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    results = {}

    try:
        # 1. Delete old price history
        result = session.execute(
            text("""
                DELETE FROM price_history
                WHERE timestamp < :cutoff
            """),
            {"cutoff": CUTOFF_DATE}
        )
        results["price_history_deleted"] = result.rowcount
        logger.info(f"Deleted {result.rowcount} old price history records")

        # 2. Delete old raw posts
        result = session.execute(
            text("""
                DELETE FROM raw_posts
                WHERE date < :cutoff
            """),
            {"cutoff": CUTOFF_DATE}
        )
        results["raw_posts_deleted"] = result.rowcount
        logger.info(f"Deleted {result.rowcount} old raw posts")

        # 3. Delete products with old timestamp that have no active tracking
        result = session.execute(
            text("""
                DELETE FROM products
                WHERE timestamp < :cutoff
                AND id NOT IN (
                    SELECT DISTINCT product_id
                    FROM tracked_products
                    WHERE is_active = true
                )
            """),
            {"cutoff": CUTOFF_DATE}
        )
        results["products_deleted"] = result.rowcount
        logger.info(f"Deleted {result.rowcount} old products")

        # 4. Vacuum to reclaim space
        session.execute(text("VACUUM"))
        logger.info("Vacuum completed")

        session.commit()
        logger.info(f"Cleanup completed successfully: {results}")

        return results

    except Exception as e:
        session.rollback()
        logger.error(f"Cleanup failed: {e}")
        raise
    finally:
        session.close()


def get_db_stats():
    """Get current database statistics"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        stats = {}

        # Total rows per table. Table names are validated against a static
        # allow-list + identifier regex, never from user input.
        for table in _STATS_TABLES:
            if not _SAFE_IDENT.match(table):
                continue
            result = session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            stats[f"{table}_count"] = result.scalar()

        # Old records count
        result = session.execute(
            text("SELECT COUNT(*) FROM price_history WHERE timestamp < :cutoff"),
            {"cutoff": CUTOFF_DATE}
        )
        stats["old_price_history"] = result.scalar()

        result = session.execute(
            text("SELECT COUNT(*) FROM raw_posts WHERE date < :cutoff"),
            {"cutoff": CUTOFF_DATE}
        )
        stats["old_raw_posts"] = result.scalar()

        return stats

    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cleanup old database records")
    parser.add_argument("--stats", action="store_true", help="Show current DB stats")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    args = parser.parse_args()

    if args.stats:
        stats = get_db_stats()
        print("\n=== Database Statistics ===")
        for key, value in stats.items():
            print(f"{key}: {value}")
    elif args.dry_run:
        stats = get_db_stats()
        print(f"\n=== Dry Run - Would Delete ===")
        print(f"Old price history records: {stats.get('old_price_history', 0)}")
        print(f"Old raw posts: {stats.get('old_raw_posts', 0)}")
    else:
        cleanup()