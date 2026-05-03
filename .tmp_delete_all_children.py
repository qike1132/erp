import asyncio

from sqlalchemy import text

from fastapi_app.core.database import _AsyncSessionLocal


async def main():
    async with _AsyncSessionLocal() as db:
        # Find all child permissions (parent_id IS NOT NULL)
        result = await db.execute(text(
            "SELECT id, code, name, parent_id FROM permission WHERE parent_id IS NOT NULL ORDER BY parent_id, id"
        ))
        rows = result.fetchall()
        print(f"Found {len(rows)} child permissions:")
        for r in rows:
            print(f"  id={r[0]} code={r[1]} name={r[2]} parent_id={r[3]}")

        if not rows:
            print("No child permissions to delete")
            return

        child_ids = [r[0] for r in rows]

        # Delete user_permission refs
        result = await db.execute(text(
            "DELETE FROM user_permission WHERE permission_id = ANY(:ids)"
        ), {"ids": child_ids})
        print(f"Deleted {result.rowcount} user_permission refs")

        # Delete child permissions
        result = await db.execute(text(
            "DELETE FROM permission WHERE parent_id IS NOT NULL"
        ))
        print(f"Deleted {result.rowcount} child permissions")

        await db.commit()
        print("Done!")

asyncio.run(main())
