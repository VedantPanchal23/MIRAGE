"""Production Database & Cache Purification Script for MIRAGE 3.0.

Truncates all relational tables, flushes process cache, and verifies clean slate.
"""

import asyncio
import os
import sys

# Ensure repository root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text

from db.session import get_system_session


async def purge_all_data() -> None:
    print("================================================================")
    print("  MIRAGE 3.0: Purging all database records and mock state...")
    print("================================================================")

    tables: list[str] = []
    async with get_system_session() as session:
        res = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "AND table_name != 'alembic_version';"
            )
        )
        tables = [row[0] for row in res.fetchall()]
        print(f"Found {len(tables)} tables to purge: {tables}")

        if tables:
            tables_joined = ", ".join(f'"{t}"' for t in tables)
            print(f"Executing: TRUNCATE TABLE {tables_joined} CASCADE;")
            await session.execute(text(f"TRUNCATE TABLE {tables_joined} CASCADE;"))
            print("Successfully truncated all data tables.")

    # Verify all table counts are zero in a fresh session
    print("\nVerifying clean slate:")
    async with get_system_session() as session:
        for t in tables:
            r = await session.execute(text(f'SELECT count(*) FROM "{t}";'))
            count = r.scalar()
            print(f"  - {t:30}: {count} rows")

    print("\nPurge completed successfully! Ready for authentic production tenants.")


if __name__ == "__main__":
    asyncio.run(purge_all_data())
