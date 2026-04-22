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
    approval_mode: ToolApprovalMode = Field(default=ToolApprovalMode.AUTO)
    actor: str = Field(default="agent", min_length=1, max_length=64)


class AgentResumeRequest(BaseModel):
    conversation_id: int | None = Field(default=None, gt=0)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    decision: dict = Field(default_factory=dict)
    actor: str = Field(default="agent", min_length=1, max_length=64)
    folder_id: int | None = Field(default=None, gt=0)
    bvid: str | None = Field(default=None, max_length=32)
    scope_mode: Literal["video", "folder", "global"] | None = Field(default=None)


class ChatConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ChatConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class SettingsRequest(BaseModel):
    max_video_minutes: int = Field(..., ge=1, le=300)


class TagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class ModelSettingsRequest(BaseModel):
    llm_model: str = Field(..., min_length=1)
    dashscope_api_key: str = Field(..., min_length=1)
    dashscope_base_url: str = Field(default="")
    embedding_model: str = Field(default="")
    ollama_base_url: str = Field(default="")
    asr_api_model: str = Field(default="")
    asr_api_base_url: str = Field(default="")


class ModelSettingsResponse(BaseModel):
    llm_model: str
    dashscope_api_key: str
    dashscope_base_url: str
    embedding_model: str
    ollama_base_url: str
    asr_api_model: str
    asr_api_base_url: str
