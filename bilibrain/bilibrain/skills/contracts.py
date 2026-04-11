from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillDescriptor(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1)
    skill_path: str = Field(..., min_length=1)
    directory_path: str = Field(..., min_length=1)
    allow_model_invocation: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: list[str] = Field(default_factory=list)
    active: bool = False


class SkillManifest(SkillDescriptor):
    body: str = Field(..., min_length=1)


class SkillActivation(BaseModel):
    session_id: str | None = Field(default=None, max_length=128)
    skill: SkillManifest
    actor: str = Field(default="system", min_length=1, max_length=64)


class SkillActivateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    actor: str = Field(default="system", min_length=1, max_length=64)


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class ParsedSkillManifest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    allow_model_invocation: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
