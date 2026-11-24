"""round4 hardening: usage call id, export degraded details, indexes

Revision ID: c4d5e6f70819
Revises: b717060f2795
Create Date: 2026-11-24 10:00:00.000000
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f70819"
down_revision: str | None = "b717060f2795"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _parse_meta(raw: object) -> dict[str, object]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _rewrite_asset_refs(obj: object, remap: dict[str, str]) -> tuple[object, bool]:
    """Recursively rewrite assetId values in a JSON-like structure. Returns (new_obj, changed)."""
    if isinstance(obj, dict):
        changed = False
        new: dict[str, object] = {}
        for key, value in obj.items():
            if key == "assetId" and isinstance(value, str) and value in remap:
                new[key] = remap[value]
                changed = True
            else:
                child, child_changed = _rewrite_asset_refs(value, remap)
                new[key] = child
                changed = changed or child_changed
        return new, changed
    if isinstance(obj, list):
        changed = False
        new_list: list[object] = []
        for item in obj:
            child, child_changed = _rewrite_asset_refs(item, remap)
            new_list.append(child)
            changed = changed or child_changed
        return new_list, changed
    return obj, False


def _dedup_doc_assets() -> None:
    """Merge duplicate doc_assets rows (same document_id + sha256) before adding unique constraint.

    Keeps the row with the smallest id per group, merges aliases from duplicates into it,
    remaps assetId references in deck_versions snapshots/patches, then deletes the duplicates.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, document_id, sha256, meta, storage_key, source_ref FROM doc_assets "
            "ORDER BY document_id, sha256, id"
        )
    ).fetchall()
    groups: dict[
        tuple[str, str],
        list[tuple[object, object, object, object, object, object]],
    ] = {}
    for row in rows:
        key = (str(row[1]), str(row[2]))
        groups.setdefault(key, []).append(tuple(row))
    remap: dict[str, str] = {}
    for group in groups.values():
        if len(group) <= 1:
            continue
        keep = group[0]
        keep_id = str(keep[0])
        keep_meta = _parse_meta(keep[3])
        keep_aliases = dict(keep_meta.get("aliases") or {})
        keep_source_refs = list(keep_meta.get("sourceRefs") or [])
        changed = False
        for dup in group[1:]:
            dup_id = str(dup[0])
            dup_meta = _parse_meta(dup[3])
            dup_aliases = dup_meta.get("aliases") or {}
            if isinstance(dup_aliases, dict) and dup_aliases:
                keep_aliases.update(dup_aliases)
                changed = True
            dup_storage = dup[4]
            if dup_storage is not None:
                keep_aliases[dup_id] = dup_storage
                changed = True
            dup_source_ref = dup[5]
            if dup_source_ref:
                parsed_ref = _parse_meta(dup_source_ref)
                if parsed_ref and parsed_ref not in keep_source_refs:
                    keep_source_refs.append(parsed_ref)
                    changed = True
            remap[dup_id] = keep_id
        if changed:
            keep_meta["aliases"] = keep_aliases
            if keep_source_refs:
                keep_meta["sourceRefs"] = keep_source_refs
            meta_json = json.dumps(keep_meta, ensure_ascii=False)
            if bind.dialect.name == "postgresql":
                bind.execute(
                    sa.text("UPDATE doc_assets SET meta = CAST(:meta AS JSONB) WHERE id = :id"),
                    {"meta": meta_json, "id": keep_id},
                )
            else:
                bind.execute(
                    sa.text("UPDATE doc_assets SET meta = :meta WHERE id = :id"),
                    {"meta": meta_json, "id": keep_id},
                )
    if remap:
        documents = bind.execute(
            sa.text("SELECT id, normalized_md, ast, outline FROM documents")
        ).fetchall()
        for document in documents:
            document_id = str(document[0])
            normalized_md = document[1]
            ast = document[2]
            outline = document[3]
            new_md = normalized_md
            if isinstance(normalized_md, str):
                for old_id, keep_id in remap.items():
                    new_md = str(new_md).replace(f"asset://{old_id}", f"asset://{keep_id}")
            new_ast, ast_changed = _rewrite_asset_refs(ast, remap)
            new_outline, outline_changed = _rewrite_asset_refs(outline, remap)
            md_changed = new_md != normalized_md
            if not md_changed and not ast_changed and not outline_changed:
                continue
            ast_json = json.dumps(new_ast, ensure_ascii=False) if ast_changed else None
            outline_json = (
                json.dumps(new_outline, ensure_ascii=False) if outline_changed else None
            )
            if bind.dialect.name == "postgresql":
                if md_changed:
                    bind.execute(
                        sa.text("UPDATE documents SET normalized_md = :md WHERE id = :id"),
                        {"md": new_md, "id": document_id},
                    )
                if ast_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE documents SET ast = CAST(:ast AS JSONB) WHERE id = :id"
                        ),
                        {"ast": ast_json, "id": document_id},
                    )
                if outline_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE documents SET outline = CAST(:outline AS JSONB) WHERE id = :id"
                        ),
                        {"outline": outline_json, "id": document_id},
                    )
            else:
                values: dict[str, object] = {"id": document_id}
                assignments: list[str] = []
                if md_changed:
                    assignments.append("normalized_md = :md")
                    values["md"] = new_md
                if ast_changed:
                    assignments.append("ast = :ast")
                    values["ast"] = ast_json
                if outline_changed:
                    assignments.append("outline = :outline")
                    values["outline"] = outline_json
                bind.execute(
                    sa.text(
                        f"UPDATE documents SET {', '.join(assignments)} WHERE id = :id"
                    ),
                    values,
                )
        versions = bind.execute(
            sa.text("SELECT id, snapshot, patch FROM deck_versions")
        ).fetchall()
        for version in versions:
            version_id = str(version[0])
            snapshot = version[1]
            patch = version[2]
            new_snapshot, snap_changed = _rewrite_asset_refs(snapshot, remap)
            new_patch, patch_changed = _rewrite_asset_refs(patch, remap)
            if not snap_changed and not patch_changed:
                continue
            snap_json = json.dumps(new_snapshot, ensure_ascii=False) if snap_changed else None
            patch_json = json.dumps(new_patch, ensure_ascii=False) if patch_changed else None
            if bind.dialect.name == "postgresql":
                if snap_changed and patch_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET snapshot = CAST(:snap AS JSONB), "
                            "patch = CAST(:patch AS JSONB) WHERE id = :id"
                        ),
                        {"snap": snap_json, "patch": patch_json, "id": version_id},
                    )
                elif snap_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET snapshot = CAST(:snap AS JSONB) WHERE id = :id"
                        ),
                        {"snap": snap_json, "id": version_id},
                    )
                else:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET patch = CAST(:patch AS JSONB) WHERE id = :id"
                        ),
                        {"patch": patch_json, "id": version_id},
                    )
            else:
                if snap_changed and patch_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET snapshot = :snap, patch = :patch WHERE id = :id"
                        ),
                        {"snap": snap_json, "patch": patch_json, "id": version_id},
                    )
                elif snap_changed:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET snapshot = :snap WHERE id = :id"
                        ),
                        {"snap": snap_json, "id": version_id},
                    )
                else:
                    bind.execute(
                        sa.text(
                            "UPDATE deck_versions SET patch = :patch WHERE id = :id"
                        ),
                        {"patch": patch_json, "id": version_id},
                    )
    for group in groups.values():
        if len(group) <= 1:
            continue
        for dup in group[1:]:
            bind.execute(sa.text("DELETE FROM doc_assets WHERE id = :id"), {"id": str(dup[0])})


def upgrade() -> None:
    with op.batch_alter_table("usage_ledger", schema=None) as batch_op:
        batch_op.add_column(sa.Column("upstream_call_id", sa.String(length=160), nullable=True))
        batch_op.create_unique_constraint("uq_usage_ledger_upstream_call", ["upstream_call_id"])
        batch_op.create_index(
            "ix_usage_ledger_purpose_created", ["purpose", "created_at"], unique=False
        )

    with op.batch_alter_table("export_artifacts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("degraded_details", JSONType, nullable=True))

    _dedup_doc_assets()
    with op.batch_alter_table("doc_assets", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_doc_assets_document_sha", ["document_id", "sha256"])

    with op.batch_alter_table("shares", schema=None) as batch_op:
        batch_op.create_index(
            "ix_shares_active",
            ["deck_id", "expires_at"],
            unique=False,
            postgresql_where=sa.text("revoked_at IS NULL"),
            sqlite_where=sa.text("revoked_at IS NULL"),
        )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_deck_versions_snapshot_gin "
            "ON deck_versions USING gin (snapshot jsonb_path_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_deck_versions_snapshot_gin")

    with op.batch_alter_table("shares", schema=None) as batch_op:
        batch_op.drop_index(
            "ix_shares_active",
            postgresql_where=sa.text("revoked_at IS NULL"),
            sqlite_where=sa.text("revoked_at IS NULL"),
        )

    with op.batch_alter_table("doc_assets", schema=None) as batch_op:
        batch_op.drop_constraint("uq_doc_assets_document_sha", type_="unique")

    with op.batch_alter_table("export_artifacts", schema=None) as batch_op:
        batch_op.drop_column("degraded_details")

    with op.batch_alter_table("usage_ledger", schema=None) as batch_op:
        batch_op.drop_index("ix_usage_ledger_purpose_created")
        batch_op.drop_constraint("uq_usage_ledger_upstream_call", type_="unique")
        batch_op.drop_column("upstream_call_id")
