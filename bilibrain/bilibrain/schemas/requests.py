from typing import Literal

from pydantic import BaseModel, Field
from bilibrain.tools.contracts import ToolApprovalMode


class SyncRequest(BaseModel):
    folder_id: int = Field(..., gt=0)


class AskRequest(BaseModel):
    query: str = Field(..., min_length=2)
    folder_id: int | None = Field(default=None, gt=0)
    bvid: str | None = Field(default=None, max_length=32)
    scope_mode: Literal["video", "folder", "global"] | None = Field(default=None)
    conversation_id: int | None = Field(default=None, gt=0)
    deep_research: bool = Field(default=False)


class ChatConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ChatConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class SkillAgentAskRequest(BaseModel):
    query: str = Field(..., min_length=2)
    conversation_id: int | None = Field(default=None, gt=0)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    approval_mode: ToolApprovalMode = Field(default=ToolApprovalMode.AUTO)
    actor: str = Field(default="skill-agent", min_length=1, max_length=64)


class SkillAgentResumeRequest(BaseModel):
    conversation_id: int | None = Field(default=None, gt=0)
    session_id: str = Field(..., min_length=1, max_length=128)
    decision: dict = Field(default_factory=dict)
    actor: str = Field(default="skill-agent", min_length=1, max_length=64)


class SettingsRequest(BaseModel):
    max_video_minutes: int = Field(..., ge=1, le=300)


class TagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)
