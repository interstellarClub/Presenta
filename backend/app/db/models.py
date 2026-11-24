import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSONType = JSON(none_as_null=True).with_variant(JSONB, "postgresql")
BigIntType = BigInteger().with_variant(Integer, "sqlite")


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('pending','active','suspended')", name="status_allowed"),
    )

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Session(Base, CreatedAtMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index(
            "ix_sessions_active_user",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )


class InviteCode(Base, CreatedAtMixin):
    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(120))
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("used_count >= 0", name="used_count_non_negative"),)


class InviteRedemption(Base, CreatedAtMixin):
    __tablename__ = "invite_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("invite_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (UniqueConstraint("code_id", "user_id", name="uq_invite_redemption"),)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    original_key: Mapped[str | None] = mapped_column(Text)
    normalized_md: Mapped[str | None] = mapped_column(Text)
    ast: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(24), default="parsing", nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('upload_docx','editor_md')", name="source_type_allowed"
        ),
        CheckConstraint(
            "status IN ('parsing','normalizing','extracting_assets','indexing','ready','failed')",
            name="status_allowed",
        ),
        Index("ix_documents_user_created", "user_id", "created_at"),
    )

    assets: Mapped[list["DocAsset"]] = relationship(back_populates="document")


class DocAsset(Base, CreatedAtMixin):
    __tablename__ = "doc_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigIntType)
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    ref_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('image','table','formula')", name="kind_allowed"),
        UniqueConstraint("document_id", "sha256", name="uq_doc_assets_document_sha"),
    )

    document: Mapped[Document] = relationship(back_populates="assets")


class Theme(Base, CreatedAtMixin):
    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    package_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="builtin", nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('builtin','pending','approved','rejected')", name="status_allowed"
        ),
    )


class Deck(Base, TimestampMixin):
    __tablename__ = "decks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    theme_id: Mapped[str] = mapped_column(String(64), default="academic", nullable=False)
    motion_level: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_version_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("motion_level >= 0.0 AND motion_level <= 1.0", name="motion_range"),
        Index("ix_decks_user_created", "user_id", "created_at"),
    )

    versions: Mapped[list["DeckVersion"]] = relationship(
        back_populates="deck", order_by="DeckVersion.seq"
    )
    document: Mapped[Document | None] = relationship()


class DeckVersion(Base, CreatedAtMixin):
    __tablename__ = "deck_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deck_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    patch: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("deck_id", "seq", name="uq_deck_version_seq"),
        CheckConstraint("kind IN ('autosave','milestone','anchor')", name="kind_allowed"),
        CheckConstraint(
            "kind = 'autosave' OR snapshot IS NOT NULL", name="snapshot_required"
        ),
        Index("ix_deck_versions_deck_seq", "deck_id", "seq"),
    )

    deck: Mapped[Deck] = relationship(back_populates="versions")


class Share(Base, CreatedAtMixin):
    __tablename__ = "shares"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deck_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    download_formats: Mapped[list[str]] = mapped_column(
        JSONType, default=lambda: ["pdf", "pptx", "html", "mp4", "gif"], nullable=False
    )
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_shares_expires", "expires_at"),
        Index(
            "ix_shares_active",
            "deck_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )


class ShareToken(Base, CreatedAtMixin):
    __tablename__ = "share_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    share_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shares.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_share_tokens_share_expiry", "share_id", "expires_at"),
    )


class ShareAccessLog(Base, CreatedAtMixin):
    __tablename__ = "share_access_logs"

    id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    share_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shares.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('auth_fail','view','download_pdf','download_pptx','download_html',"
            "'download_mp4','download_gif')",
            name="kind_allowed",
        ),
    )


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('ingest','batch_generate','pdf_export','ppt_export','gif_export',"
            "'cleanup')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled','partial')",
            name="status_allowed",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        Index(
            "ix_jobs_active",
            "status",
            "created_at",
            postgresql_where=text("status IN ('queued','running')"),
            sqlite_where=text("status IN ('queued','running')"),
        ),
    )


class ExportArtifact(Base, CreatedAtMixin):
    __tablename__ = "export_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deck_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigIntType, nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    degraded_notes: Mapped[list[str] | None] = mapped_column(JSONType)
    degraded_details: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "format IN ('pdf','pptx','html','mp4','gif')", name="format_allowed"
        ),
        Index("ix_export_cache", "deck_id", "format", "schema_hash"),
        Index("ix_export_expires", "expires_at"),
    )


class UsageLedger(Base, CreatedAtMixin):
    __tablename__ = "usage_ledger"

    id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    deck_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(48), nullable=False)
    thinking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    upstream_call_id: Mapped[str | None] = mapped_column(String(160), unique=True)

    __table_args__ = (
        Index("ix_usage_ledger_purpose_created", "purpose", "created_at"),
    )


class AuditLog(Base, CreatedAtMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigIntType, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType)