"""PostgreSQL schema.

Mapping to the entities in the requirements document (section 3.4):

    Source               -> sources (+ source_runs for health/retry history)
    RawPosting           -> raw_snapshots       (one row per distinct content hash, FR-03)
    VacancySourceLink    -> source_postings      (one row per (source, external id); links to a canonical vacancy)
    ExtractedField       -> extracted_fields     (value, confidence, provenance per snapshot, FR-07)
    CanonicalVacancy     -> canonical_vacancies  (merged, de-duplicated, searchable, FR-09/11/16)
    User, StudentProfile -> users, student_profiles
    SavedVacancy         -> saved_vacancies
    Interaction          -> interactions
    ReviewItem           -> review_items
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _str_array() -> Mapped[list[str]]:
    return mapped_column(ARRAY(String), nullable=False, default=list, server_default=text("'{}'"))


# --------------------------------------------------------------------------- ingestion


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # api | feed | page | telegram | file | manual
    base_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=360, server_default=text("360"))
    policy_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | failed
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    changed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class SourcePosting(Base):
    """One posting at one source. Links to the canonical vacancy it was grouped into."""

    __tablename__ = "source_postings"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))  # hash of the latest snapshot
    employer_key: Mapped[str | None] = mapped_column(String(255), index=True)  # dedup blocking
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = _created_at()
    last_checked_at: Mapped[datetime] = _created_at()
    gone_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_vacancy_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_vacancies.id", ondelete="SET NULL"), index=True
    )
    match_score: Mapped[float | None] = mapped_column(Float)
    match_method: Mapped[str | None] = mapped_column(String(20))  # new | auto | admin

    source: Mapped[Source] = relationship()
    snapshots: Mapped[list[RawSnapshot]] = relationship(
        back_populates="source_posting", cascade="all, delete-orphan", order_by="RawSnapshot.collected_at"
    )


class RawSnapshot(Base):
    """Raw text exactly as collected. Never modified after insert (FR-03, FR-05)."""

    __tablename__ = "raw_snapshots"
    __table_args__ = (UniqueConstraint("source_posting_id", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_postings.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    collected_at: Mapped[datetime] = _created_at()
    title: Mapped[str] = mapped_column(Text)
    employer: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    apply_url: Mapped[str | None] = mapped_column(Text)
    source_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    source_posting: Mapped[SourcePosting] = relationship(back_populates="snapshots")
    fields: Mapped[list[ExtractedField]] = relationship(cascade="all, delete-orphan")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("snapshot_id", "field"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("raw_snapshots.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # ok | low_confidence | conflict | missing
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String(80))
    evidence: Mapped[str | None] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    extractor_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- canonical vacancies

# Multilingual full-text search (FR-16): Russian and English stemming plus a 'simple' (unstemmed) copy that
# also covers Kazakh, for which PostgreSQL ships no stemmer. Prefix queries on 'simple' handle Kazakh suffixes.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('russian'::regconfig, coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, coalesce(search_document, '')), 'B') || "
    "setweight(to_tsvector('russian'::regconfig, coalesce(search_document, '')), 'B') || "
    "setweight(to_tsvector('english'::regconfig, coalesce(search_document, '')), 'B')"
)


class CanonicalVacancy(Base):
    __tablename__ = "canonical_vacancies"
    __table_args__ = (
        Index("ix_canonical_vacancies_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_canonical_vacancies_cities", "cities", postgresql_using="gin"),
        Index("ix_canonical_vacancies_skills", "skills", postgresql_using="gin"),
        Index("ix_canonical_vacancies_languages", "languages", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | expired | hidden
    title: Mapped[str] = mapped_column(Text)
    employer_name: Mapped[str | None] = mapped_column(Text)
    employer_key: Mapped[str | None] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    posting_language: Mapped[str | None] = mapped_column(String(10))

    # Denormalised "known" values (confidence >= threshold) used for filters and ranking.
    # Full provenance lives in field_meta and extracted_fields.
    is_internship: Mapped[bool | None] = mapped_column(Boolean)
    level: Mapped[str | None] = mapped_column(String(10), index=True)
    work_format: Mapped[str | None] = mapped_column(String(10), index=True)
    cities: Mapped[list[str]] = _str_array()
    skills: Mapped[list[str]] = _str_array()
    languages: Mapped[list[str]] = _str_array()
    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    salary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    eligibility: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    apply_url: Mapped[str | None] = mapped_column(Text)
    field_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = _created_at()
    last_checked_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_reason: Mapped[str | None] = mapped_column(String(40))

    search_document: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    search_vector: Mapped[Any] = mapped_column(TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True))

    source_postings: Mapped[list[SourcePosting]] = relationship(
        primaryjoin="CanonicalVacancy.id == SourcePosting.canonical_vacancy_id", viewonly=True
    )


# --------------------------------------------------------------------------- users


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="student", server_default="student")
    tracking_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    consent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    education_level: Mapped[str | None] = mapped_column(String(20))  # college | bachelor | master | phd
    year_of_study: Mapped[int | None] = mapped_column(SmallInteger)
    expected_graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    field_of_study: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[str]] = _str_array()
    preferred_cities: Mapped[list[str]] = _str_array()
    work_formats: Mapped[list[str]] = _str_array()  # acceptable formats; empty = any
    target_levels: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=lambda: ["intern", "junior"], server_default=text("'{intern,junior}'")
    )
    languages: Mapped[list[str]] = _str_array()
    interests: Mapped[list[str]] = _str_array()
    open_to_relocation: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="profile")


class SavedVacancy(Base):
    __tablename__ = "saved_vacancies"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("canonical_vacancies.id", ondelete="CASCADE"), primary_key=True)
    remind: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()

    vacancy: Mapped[CanonicalVacancy] = relationship()


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("canonical_vacancies.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # view | click_apply | dismiss | not_relevant
    created_at: Mapped[datetime] = _created_at()


# --------------------------------------------------------------------------- administration


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    # low_confidence_field | field_conflict | suspected_duplicate | stale_vacancy
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)
    vacancy_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_vacancies.id", ondelete="SET NULL"))
    source_posting_id: Mapped[int | None] = mapped_column(ForeignKey("source_postings.id", ondelete="CASCADE"))
    other_vacancy_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_vacancies.id", ondelete="SET NULL"))
    field: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
