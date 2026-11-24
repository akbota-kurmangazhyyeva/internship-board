"""The contract between source adapters (Part B) and the processing pipeline (Part A).

An adapter's only job is to turn whatever its source returns into `RawPostingIn` objects and hand them to
`app.pipeline.ingest_posting(session, source_key, posting)`. Everything after that (snapshot + hash,
change detection, normalisation, extraction, duplicate grouping, canonical record, review queue) is done
by the pipeline.

`source_fields` is optional structured data the source already provides. Supported keys (all optional):

    city          "Алматы" or ["Алматы", "Астана"]          (hh.kz: area.name)
    work_format   "remote" | "hybrid" | "onsite"            (hh.kz: work_format / schedule=remote)
    experience    "noExperience" | "between1And3" | "between3And6" | "moreThan6"   (hh.kz ids accepted)
    employment    "internship" | "probation" | "full" | "part" | "project"        (hh.kz: employment.id)
    salary        {"from": 150000, "to": 250000, "currency": "KZT", "gross": false}  (hh.kz: salary)
    skills        ["Python", "SQL"]                          (hh.kz: key_skills[].name)
    deadline      "2026-12-15"                               (only if the source has an explicit field)

Structured values outrank free-text rules. Anything else the source returns goes in `payload` untouched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RawPostingIn(BaseModel):
    external_id: str = Field(
        min_length=1, max_length=255, description="Stable id at the source (hh vacancy id, TG message id, ...)"
    )
    url: str = Field(min_length=1, description="Public link to the posting at the source")
    title: str = Field(min_length=1)
    description: str = Field(default="", description="Full text or HTML as collected")
    employer: str | None = None
    published_at: datetime | None = None
    apply_url: str | None = None
    source_fields: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] | None = Field(default=None, description="Original response, kept for audit")

    def content_hash(self) -> str:
        """SHA-256 over the fields that matter. Unchanged hash => nothing to reprocess (FR-03)."""
        material = {
            "title": self.title,
            "description": self.description,
            "employer": self.employer,
            "apply_url": self.apply_url,
            "source_fields": self.source_fields,
        }
        blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
