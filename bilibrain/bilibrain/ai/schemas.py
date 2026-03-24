from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    route: Literal["history_only", "summary_only", "chunk_only", "mixed"] = Field(
        description="本轮问题应走的主路由"
    )
    use_history: bool = Field(description="是否需要利用会话历史帮助理解当前问题")
    use_current_scope: bool = Field(description="是否需要严格使用当前选中的知识库范围")
    retrieval_mode: Literal["none", "summary", "chunk"] = Field(
        description="当前知识库应使用的资料模式"
    )
    reason: str = Field(description="一句话解释为什么这么判断")
