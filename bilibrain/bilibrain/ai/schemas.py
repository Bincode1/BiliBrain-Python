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


class ResearchSubtask(BaseModel):
    task_id: str = Field(description="子任务唯一标识")
    title: str = Field(description="子任务标题")
    objective: str = Field(description="该子任务要解决的具体问题")
    search_queries: list[str] = Field(default_factory=list, description="建议的检索查询")
    already_covered: list[str] = Field(default_factory=list, description="知识库中已覆盖、无需重复调研的点")
    do_not_repeat: str = Field(default="", description="提醒检索阶段避免重复的方向")


class ResearchPlan(BaseModel):
    research_goal: str = Field(description="本轮深度研究的目标")
    subtasks: list[ResearchSubtask] = Field(default_factory=list, description="建议拆解出的研究子任务列表")


class ResearchBrief(BaseModel):
    research_goal: str = Field(description="本轮研究要解决的核心问题")
    key_aspects_text: str = Field(default="", description="需要覆盖的关键维度，使用换行分隔")
    primary_query: str = Field(default="", description="第一轮主搜索词")
    secondary_query: str = Field(default="", description="第一轮可选补充搜索词")
    kb_signals_text: str = Field(default="", description="知识库候选线索，使用换行分隔")


class EvidenceJudgement(BaseModel):
    status: Literal["sufficient", "partial", "insufficient"] = Field(description="当前证据是否足以进入最终写作")
    missing_aspects_text: str = Field(default="", description="当前仍明显缺失的方面，使用换行分隔")
    next_query: str = Field(default="", description="下一轮应补充的一条搜索词")
    reason: str = Field(description="一句话说明为什么这么判断")
