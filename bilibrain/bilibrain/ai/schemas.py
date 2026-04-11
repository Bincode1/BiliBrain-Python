from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    route: Literal["direct", "kb_qa"] = Field(
        description="本轮问题是否需要检索知识库"
    )
    retrieval_strategy: Literal["chunk", "summary"] = Field(
        description="检索策略：chunk 查具体细节，summary 查宏观概括。仅 route=kb_qa 时有效"
    )
    use_history: bool = Field(description="是否需要利用会话历史帮助理解当前问题")
    reason: str = Field(description="一句话解释为什么这么判断")
