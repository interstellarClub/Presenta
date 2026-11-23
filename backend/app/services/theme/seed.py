from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Theme
from app.services.theme.manifest import load_all_builtin


async def seed_builtin_themes(session: AsyncSession) -> int:
    manifests = load_all_builtin()
    existing = {
        row.id: row for row in (await session.scalars(select(Theme))).all()
    }
    changed = 0
    for manifest in manifests:
        theme_id = manifest["id"]
        row = existing.get(theme_id)
        if row is None:
            session.add(
                Theme(
                    id=theme_id,
                    owner_id=None,
                    name=manifest.get("name", theme_id),
                    manifest=manifest,
                    status="builtin",
                )
            )
            changed += 1
            continue
        if row.manifest != manifest or row.name != manifest.get("name"):
            row.manifest = manifest
            row.name = manifest.get("name", theme_id)
            changed += 1
    await session.flush()
    return changed