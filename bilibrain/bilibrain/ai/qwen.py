from __future__ import annotations

import json
from typing import Any

from langchain_qwq import ChatQwen

from bilibrain.ai.schemas import EvidenceJudgement, QueryPlan, ResearchBrief, ResearchPlan
from bilibrain.core.config import Settings
from bilibrain.services.common import seconds_to_timestamp


class QwenClient:
    SYSTEM_PROMPT = "你是 BiliBrain，只能根据给定资料回答，不要补充资料外的知识。"
    SUMMARY_SYSTEM_PROMPT = "你是 BiliBrain 的摘要助手，只能依据给定文本压缩信息，不要补充外部知识。"
    HISTORY_SYSTEM_PROMPT = "你是 BiliBrain 的会话回顾助手，只能依据给定的会话历史回顾之前聊过的内容，不要补充会话里没有的信息。"
    PLANNER_SYSTEM_PROMPT = "你是 BiliBrain 的问答路由规划器，只负责输出结构化决策，不直接回答用户问题。"
    RESEARCH_SYSTEM_PROMPT = "你是 BiliBrain 的深度研究助手。你要结合知识库已有内容和外部资料，输出高信息密度的研究结论，不要空话。"
    MEMORY_SYSTEM_PROMPT = (
        "你是 BiliBrain 的会话记忆整理助手。"
        "你要维护的是后续对话可复用的会话状态，不是知识内容全文总结。"
        "只能依据已有记忆和新增会话片段更新长期记忆，不要补充对话里没有的信息。"
    )
    MAX_HISTORY_MESSAGES = 10
    MAX_PLANNER_HISTORY_MESSAGES = 6
    MAX_HISTORY_RECALL_MESSAGES = 16

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.MAX_HISTORY_MESSAGES = max(int(settings.chat_recent_turns_to_keep or 5) * 2, 2)
        self.model = ChatQwen(
            model=settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0,
            streaming=True,
            enable_thinking=False,
        )
        self.planner_base_model = ChatQwen(
            model=settings.planner_llm_model or settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0,
            streaming=False,
            enable_thinking=False,
        )
        self.planner_model = self.planner_base_model.with_structured_output(QueryPlan)
        self.research_planner_model = self.planner_base_model.with_structured_output(ResearchPlan)
        self.research_brief_model = self.planner_base_model.with_structured_output(ResearchBrief)
        self.evidence_judge_model = self.planner_base_model.with_structured_output(EvidenceJudgement)

    def ensure_configured(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")

    def _build_messages(
        self,
        query: str,
        context: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
        *,
        citations_required: bool = True,
    ) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = [("system", self.SYSTEM_PROMPT)]
        if str(memory_text or "").strip():
            messages.append(
                (
                    "system",
                    "\n".join(
                        [
                            "以下是更早会话的压缩记忆，可用于理解上下文，但如果与当前资料冲突，仍以当前资料为准：",
                            str(memory_text).strip(),
                        ]
                    ),
                )
            )
        for item in self._normalize_history(history):
            role = "human" if item["role"] == "user" else "ai"
            messages.append((role, item["content"]))
        rules = [
            "1. 只使用资料里的信息，不要补充外部知识。",
            "2. 如果资料不足以回答，就直接说明“你的收藏内容里没有足够信息回答这个问题”。",
            "3. 如果历史对话与当前资料冲突，以当前资料为准。",
            "4. 回答用中文，简洁直接。",
        ]
        if citations_required:
            rules.extend(
                [
                    "5. 关键结论或每个自然段结尾请附上资料编号，格式必须是【1】或【1】【3】。",
                    "6. 不要输出“资料1”“资料[1]”“（资料[1]）”“来源1”等其他引用格式，只能输出【n】样式。",
                    "7. 编号只能使用资料里已有的编号；如果某句无法从资料直接得到，就不要写那句。",
                ]
            )
        messages.append(
            (
                "human",
                "\n".join(
                    [
                        "规则：",
                        *rules,
                        "",
                        f"用户问题：{query}",
                        "",
                        "资料：",
                        context,
                    ]
                ),
            )
        )
        return messages

    def _build_history_recall_messages(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> list[tuple[str, str]]:
        transcript = self._format_history_transcript(
            history,
            limit=self.MAX_HISTORY_RECALL_MESSAGES,
        )
        messages: list[tuple[str, str]] = [("system", self.HISTORY_SYSTEM_PROMPT)]
        if str(memory_text or "").strip():
            messages.append(
                (
                    "system",
                    "\n".join(
                        [
                            "以下是更早会话的压缩记忆，可用于回顾更早讨论过的话题：",
                            str(memory_text).strip(),
                        ]
                    ),
                )
            )
        messages.append(
            (
                "human",
                "\n".join(
                    [
                        "任务：请根据以下会话历史，回顾我们之前聊过的内容。",
                        "要求：",
                        "1. 只能依据会话历史回答，不要补充会话里没有的信息。",
                        "2. 如果会话历史里没有足够信息，就明确说“当前会话历史里没有足够信息回答这个问题”。",
                        "3. 回答用中文，简洁直接。",
                        "4. 如果问题是在追问“前面说了什么”，优先概括当时的结论和关键点。",
                        "",
                        f"用户问题：{query}",
                        "",
                        "会话历史：",
                        transcript or "（暂无可用会话历史）",
                    ]
                ),
            )
        )
        return messages

    def _build_planner_messages(
        self,
        *,
        query: str,
        scope_description: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> list[tuple[str, str]]:
        transcript = self._format_history_transcript(
            history,
            limit=self.MAX_PLANNER_HISTORY_MESSAGES,
        )
        messages: list[tuple[str, str]] = [("system", self.PLANNER_SYSTEM_PROMPT)]
        if str(memory_text or "").strip():
            messages.append(
                (
                    "system",
                    "\n".join(
                        [
                            "以下是更早会话的压缩记忆，可帮助你理解用户是否在追问旧话题：",
                            str(memory_text).strip(),
                        ]
                    ),
                )
            )
        messages.append(
            (
                "human",
                "\n".join(
                    [
                        "你需要判断当前问题应该走哪条问答路由。",
                        "",
                        "可选 route：",
                        "1. history_only：只回顾本次会话历史，不检索当前知识库。",
                        "2. summary_only：在当前知识库范围内，做总结类回答。",
                        "3. chunk_only：在当前知识库范围内，做细节检索问答。",
                        "4. mixed：需要利用会话历史理解问题，但最终回答仍严格受当前知识库范围约束。",
                        "",
                        "硬约束：",
                        "1. 只要不是 history_only，回答都必须严格受当前知识库范围约束。",
                        "2. 如果用户一边引用前文，一边又在问当前知识库有没有相关内容，这通常是 mixed。",
                        "3. 如果问题主要是在回顾“你前面说了什么/刚才总结了什么”，通常是 history_only。",
                        "4. 如果问题主要是在当前范围内做概括、总结、归纳，通常是 summary_only。",
                        "5. 如果问题主要是在当前范围内查一个具体事实、细节、时间点、定义、步骤，通常是 chunk_only。",
                        "",
                        f"当前知识库范围：{scope_description}",
                        "",
                        f"当前用户问题：{query}",
                        "",
                        "最近会话历史：",
                        transcript or "（暂无会话历史）",
                        "",
                        "请严格输出结构化结果，不要输出额外解释。",
                    ]
                ),
            )
        )
        return messages

    async def answer(
        self,
        query: str,
        matches: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> str:
        self.ensure_configured()
        context = self._build_context(matches)
        messages = self._build_messages(query, context, history, memory_text=memory_text)
        return await self._invoke_messages(messages)

    async def stream_answer(
        self,
        query: str,
        matches: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ):
        self.ensure_configured()
        context = self._build_context(matches)
        messages = self._build_messages(query, context, history, memory_text=memory_text)
        async for text in self._stream_messages(messages):
            yield text

    async def answer_from_summary_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> str:
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = self._build_messages(query, context, history, memory_text=memory_text, citations_required=True)
        return await self._invoke_messages(messages)

    async def stream_answer_from_summary_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ):
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = self._build_messages(query, context, history, memory_text=memory_text, citations_required=True)
        async for text in self._stream_messages(messages):
            yield text

    async def answer_from_history(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> str:
        self.ensure_configured()
        messages = self._build_history_recall_messages(query, history, memory_text=memory_text)
        return await self._invoke_messages(messages)

    async def stream_answer_from_history(
        self,
        query: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ):
        self.ensure_configured()
        messages = self._build_history_recall_messages(query, history, memory_text=memory_text)
        async for text in self._stream_messages(messages):
            yield text

    async def plan_query(
        self,
        *,
        query: str,
        scope_description: str,
        history: list[dict[str, Any]] | None = None,
        memory_text: str | None = None,
    ) -> QueryPlan:
        self.ensure_configured()
        messages = self._build_planner_messages(
            query=query,
            scope_description=scope_description,
            history=history,
            memory_text=memory_text,
        )
        result = await self.planner_model.ainvoke(messages)
        if isinstance(result, QueryPlan):
            return result
        if isinstance(result, dict):
            return QueryPlan.model_validate(result)
        return QueryPlan.model_validate(result.model_dump())

    async def plan_research(
        self,
        *,
        query: str,
        scope_description: str,
        kb_snapshot: dict[str, Any],
    ) -> ResearchPlan:
        self.ensure_configured()
        snapshot_json = json.dumps(kb_snapshot, ensure_ascii=False)
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        "你要为一次技术深度研究拆任务。",
                        "要求：",
                        "1. 先判断知识库候选资料里哪些维度已经有线索，避免重复调研。",
                        "2. 输出 2 到 4 个高价值子任务，不要拆得过碎。",
                        "3. 每个子任务必须给出 1 到 3 个适合 web 搜索的查询。",
                        "4. already_covered 只填写知识库候选资料里已经被明确回答的点，不要把模糊相关算进去。",
                        "5. do_not_repeat 要提醒后续检索避免浪费 token 的方向。",
                        "",
                        f"用户问题：{query}",
                        f"当前知识库范围：{scope_description}",
                        "",
                        "知识库快照（注意：这是候选资料，不代表已经完整覆盖问题）：",
                        snapshot_json,
                    ]
                ),
            ),
        ]
        result = await self.research_planner_model.ainvoke(messages)
        if isinstance(result, ResearchPlan):
            return result
        if isinstance(result, dict):
            return ResearchPlan.model_validate(result)
        return ResearchPlan.model_validate(result.model_dump())

    async def understand_research_query(
        self,
        *,
        query: str,
        scope_description: str,
        kb_snapshot: dict[str, Any],
    ) -> ResearchBrief:
        self.ensure_configured()
        snapshot_json = json.dumps(kb_snapshot, ensure_ascii=False)
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        "你要为一次深度研究生成检索简报。",
                        "要求：",
                        "1. 默认不要把问题机械拆成多个章节任务，除非确实存在彼此独立的研究维度。",
                        "2. 如果用户问题本身是宽泛攻略、概览、入门、总结，关键维度应保持高层抽象，不要擅自细拆成具体景点、具体店铺、具体子模块。",
                        "3. key_aspects_text 用换行分隔 1 到 3 个关键维度。",
                        "4. primary_query 和 secondary_query 都必须是短搜索词，不要写成长句，不要写完整任务描述。",
                        "5. secondary_query 必须与 primary_query 形成不同检索角度，不能只是同义改写或词序调整。",
                        "6. 对宽泛问题，优先复用用户原问题作为 primary_query，不要过早缩小到某个具体细节。",
                        "7. 只有用户已经明确要求某个具体点时，才允许把 query 缩到那个具体点。",
                        "8. kb_signals_text 只记录知识库候选资料里看起来可能有价值的线索，不要把它们当成已经充分覆盖。",
                        "",
                        f"用户问题：{query}",
                        f"当前知识库范围：{scope_description}",
                        "",
                        "知识库快照（候选资料）：",
                        snapshot_json,
                    ]
                ),
            ),
        ]
        result = await self.research_brief_model.ainvoke(messages)
        if isinstance(result, ResearchBrief):
            return result
        if isinstance(result, dict):
            return ResearchBrief.model_validate(result)
        return ResearchBrief.model_validate(result.model_dump())

    async def analyze_research_material(
        self,
        *,
        query: str,
        subtask_title: str,
        objective: str,
        kb_snapshot_text: str,
        materials_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"总问题：{query}",
                        f"子任务：{subtask_title}",
                        f"目标：{objective}",
                        "",
                        "知识库已覆盖内容：",
                        kb_snapshot_text,
                        "",
                        "新调研材料：",
                        materials_text,
                        "",
                        "任务：请产出该子任务的分析结论。",
                        "要求：",
                        "1. 先讲最重要的结论，再讲细节。",
                        "2. 去掉重复资料，突出权威来源和明显冲突。",
                        "3. 用中文。",
                        "4. 直接输出高质量分析，不要机械复述原文，不要堆摘要。",
                        "5. 优先说明：核心机制 / 关键事实 / 资料分歧 / 对总问题的价值。",
                        "6. 如果材料里存在明显空白，也要点出来，供后续总报告整合。",
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def analyze_research_evidence(
        self,
        *,
        query: str,
        research_goal: str,
        key_aspects: list[str],
        kb_snapshot_text: str,
        materials_text: str,
    ) -> str:
        self.ensure_configured()
        aspect_lines = "\n".join(f"- {item}" for item in key_aspects if str(item or "").strip()) or "- 无"
        kb_snapshot_text = str(kb_snapshot_text or "").strip()
        evidence_scope_lines: list[str] = []
        if kb_snapshot_text:
            evidence_scope_lines.extend(
                [
                    "知识库候选资料：",
                    kb_snapshot_text,
                    "",
                ]
            )
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"用户问题：{query}",
                        f"研究目标：{research_goal}",
                        "",
                        "需要覆盖的关键维度：",
                        aspect_lines,
                        "",
                        *evidence_scope_lines,
                        "当前证据池：",
                        materials_text,
                        "",
                        "任务：请基于当前证据池，写一份综合分析。",
                        "要求：",
                        "0. 如果知识库候选资料与用户问题直接相关，可以把它作为辅助资料使用；如果不直接相关，就忽略它。",
                        "0.1 如果某条判断既不被当前证据池支持，也不能从相关的知识库候选资料直接得到，就不要把它写成结论。",
                        "1. 直接围绕用户问题分析，不要按子任务逐条汇报。",
                        "2. 优先提炼已经被证据支持的关键结论、机制、差异和实践含义。",
                        "3. 如果某些关键维度证据明显不足，也要明确指出。",
                        "4. 输出中文高密度分析，不要空话。",
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def judge_research_evidence(
        self,
        *,
        query: str,
        research_goal: str,
        key_aspects: list[str],
        kb_snapshot_text: str,
        analysis_text: str,
        sources_text: str,
        round_index: int,
    ) -> EvidenceJudgement:
        self.ensure_configured()
        aspect_lines = "\n".join(f"- {item}" for item in key_aspects if str(item or "").strip()) or "- 无"
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"用户问题：{query}",
                        f"研究目标：{research_goal}",
                        f"当前检索轮次：第 {max(int(round_index), 1)} 轮",
                        "",
                        "需要覆盖的关键维度：",
                        aspect_lines,
                        "",
                        "知识库候选资料：",
                        kb_snapshot_text,
                        "",
                        "当前综合分析：",
                        analysis_text,
                        "",
                        "当前来源清单：",
                        sources_text,
                        "",
                        "任务：判断当前证据是否足以进入最终报告。",
                        "要求：",
                        "1. status 只能是 sufficient / partial / insufficient。",
                        "2. missing_aspects_text 用换行分隔真正缺失的关键维度；如果没有明显缺口就留空字符串。",
                        "3. next_query 只给一条短搜索词；如果不需要继续检索就留空字符串。",
                        "4. 对宽泛问题，next_query 不要过早下钻到很细的子点，除非用户已经明确要求那个子点。",
                        "5. 如果知识库已有候选资料但证据仍不完整，不要误判为 sufficient。",
                    ]
                ),
            ),
        ]
        result = await self.evidence_judge_model.ainvoke(messages)
        if isinstance(result, EvidenceJudgement):
            return result
        if isinstance(result, dict):
            return EvidenceJudgement.model_validate(result)
        return EvidenceJudgement.model_validate(result.model_dump())

    async def identify_research_gaps(
        self,
        *,
        query: str,
        kb_snapshot_text: str,
        analysis_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"总问题：{query}",
                        "",
                        "知识库已有内容：",
                        kb_snapshot_text,
                        "",
                        "外部调研分析：",
                        analysis_text,
                        "",
                        "任务：请找出知识库当前的明显盲区。",
                        "要求：",
                        "1. 只输出真正缺失或覆盖明显不足的点。",
                        "2. 用中文。",
                        "3. 输出 3 到 8 条要点。",
                        "4. 不要把仅仅语义相关但没有真正回答问题的资料算作已覆盖。",
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def write_research_report(
        self,
        *,
        query: str,
        kb_snapshot_text: str,
        analysis_text: str,
        gap_text: str,
        sources_text: str,
    ) -> str:
        self.ensure_configured()
        messages = self._build_research_report_messages(
            query=query,
            kb_snapshot_text=kb_snapshot_text,
            analysis_text=analysis_text,
            gap_text=gap_text,
            sources_text=sources_text,
        )
        return await self._invoke_messages(messages)

    async def stream_research_report(
        self,
        *,
        query: str,
        kb_snapshot_text: str,
        analysis_text: str,
        gap_text: str,
        sources_text: str,
    ):
        self.ensure_configured()
        messages = self._build_research_report_messages(
            query=query,
            kb_snapshot_text=kb_snapshot_text,
            analysis_text=analysis_text,
            gap_text=gap_text,
            sources_text=sources_text,
        )
        async for text in self._stream_messages(messages):
            yield text

    async def compact_conversation_memory(
        self,
        *,
        existing_memory_text: str | None = None,
        history_transcript: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.MEMORY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        "任务：请把已有会话记忆和新增旧消息片段合并，输出一份更新后的长期会话记忆。",
                        "要求：",
                        "1. 只依据给定内容，不要补充会话里没有的信息。",
                        "2. 你的任务是保留会话状态和推进脉络，不要把知识库内容重新展开成详细讲义。",
                        "3. 保留长期有价值的信息，删除寒暄、重复问答和低价值措辞。",
                        "4. 当前仍在推进的话题，放在“当前活跃目标 / 当前活跃知识范围”。已经闭环的话题，降级放到“历史已完成话题”，每个旧话题最多一句。",
                        "5. 不要重复。相同信息只保留在最合适的一个小节里，不要同时出现在“已确认结论”和“最近推进状态”里。",
                        "6. 已确认结论只保留后续还可能被引用的关键结论，不要罗列大量细节事实。",
                        "7. 如果某些结论只是当时基于资料的暂时判断，不要写成绝对事实。",
                        "8. 术语与指代只保留后续可能继续追问的映射，不要做通用概念百科。",
                        "9. 默认尽量控制篇幅，宁可高密度概括，也不要冗长重复。",
                        "10. 输出结构固定为：当前活跃目标、当前活跃知识范围、历史已完成话题、已确认结论、未解决问题、术语与指代、最近推进状态。",
                        "11. 回答用中文，结构清晰，使用精炼要点。",
                        "",
                        "已有会话记忆：",
                        str(existing_memory_text or "").strip() or "（暂无已有记忆）",
                        "",
                        "新增旧消息片段：",
                        history_transcript or "（暂无新增片段）",
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def summarize_video(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：请根据以下视频转写内容输出一份完整摘要。",
                        "要求：",
                        "1. 只依据给定内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出结构固定为：一句话概括、核心要点、详细梳理。",
                        "4. 核心要点控制在 4 到 8 条，覆盖主要主题、方法、结论和步骤。",
                        "5. 避免重复和空话，不要写“视频提到”等低信息密度表述。",
                        "",
                        "转写内容：",
                        transcript_text,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def summarize_video_window(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：请把下面这段视频转写压缩成局部摘要。",
                        "要求：",
                        "1. 只依据给定内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出 3 到 6 条要点。",
                        "4. 保留重要概念、步骤、结论和例子线索。",
                        "5. 不要写标题，不要写额外解释。",
                        "",
                        "转写内容：",
                        transcript_text,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def reduce_video_summaries(
        self,
        *,
        video_title: str,
        window_summaries: list[str],
    ) -> str:
        self.ensure_configured()
        payload = "\n\n".join(
            f"[局部摘要 {index}]\n{summary.strip()}"
            for index, summary in enumerate(window_summaries, start=1)
            if str(summary or "").strip()
        )
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：以下是同一个视频多个片段的局部摘要，请合并成一份最终摘要。",
                        "要求：",
                        "1. 只依据局部摘要内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出结构固定为：一句话概括、核心要点、详细梳理。",
                        "4. 核心要点控制在 4 到 8 条，尽量覆盖整个视频主要主题。",
                        "5. 去掉重复信息，保留关键结论、方法、步骤和注意点。",
                        "",
                        "局部摘要：",
                        payload,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def reduce_summary_documents(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
    ) -> str:
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"用户问题：{query}",
                        "",
                        "任务：以下是同一范围内多个视频的摘要，请先做一轮中间压缩，供后续总汇总使用。",
                        "要求：",
                        "1. 只依据给定摘要，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出 4 到 8 条高信息密度要点。",
                        "4. 优先保留共性主题、代表观点和明显差异。",
                        "5. 不要写空话，不要附加编号解释。",
                        "",
                        "视频摘要：",
                        context,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def _invoke_messages(self, messages: list[tuple[str, str]]) -> str:
        result = await self.model.ainvoke(messages)
        return str(getattr(result, "text", None) or result.content).strip()

    async def _stream_messages(self, messages: list[tuple[str, str]]):
        async for chunk in self.model.astream(messages):
            text = getattr(chunk, "text", None) or getattr(chunk, "content", None) or ""
            if text:
                yield text

    def _build_context(self, matches: list[dict[str, Any]]) -> str:
        lines = []
        for idx, item in enumerate(matches, start=1):
            lines.append(
                f"[{idx}] {item['video_title']} | {item.get('up_name', 'Unknown')} @ {seconds_to_timestamp(item['start_seconds'])}: {item['content']}"
            )
        return "\n".join(lines)

    def _build_summary_context(self, documents: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, item in enumerate(documents, start=1):
            lines.append(
                "\n".join(
                    [
                        f"[{idx}] {item.get('video_title', '未知视频')} | {item.get('up_name', 'Unknown')}",
                        str(item.get("summary_text") or "").strip(),
                    ]
                )
            )
        return "\n\n".join(lines)

    def _build_research_report_messages(
        self,
        *,
        query: str,
        kb_snapshot_text: str,
        analysis_text: str,
        gap_text: str,
        sources_text: str,
    ) -> list[tuple[str, str]]:
        kb_snapshot_text = str(kb_snapshot_text or "").strip()
        prompt_lines: list[str] = [f"用户问题：{query}", ""]
        if kb_snapshot_text:
            prompt_lines.extend(
                [
                    "知识库候选资料（仅供理解上下文和检索线索，不能单独作为事实依据，也不能单独支撑引用）：",
                    kb_snapshot_text,
                    "",
                ]
            )
        prompt_lines.extend(
            [
                "调研分析结论（若其中某条说法得不到统一来源清单支持，必须丢弃）：",
                analysis_text,
                "",
                "当前识别出的知识盲区：",
                gap_text,
                "",
                "统一来源清单：",
                sources_text,
                "",
                "任务：请写一份深度研究报告。",
                "要求：",
                "1. 用中文 Markdown 输出。",
                "2. 先直接回答用户问题，产出一份真实、完整、可读的分析报告，不要写成流程汇报，也不要按“已覆盖/未覆盖”机械分块。",
                "3. 报告结构由问题本身决定；如果问题适合，可以自然包含：总体结论、核心机制拆解、与主流方案对比、实践建议、学习路径。",
                "4. 如果知识库候选资料与用户问题直接相关，可以吸收其中的信息；如果不相关，就忽略，不要硬写进报告。",
                "5. 统一来源清单仍然是优先引用来源。凡是能够由统一来源清单直接支持的句子，尽量附上【n】引用。",
                "6. 不要写“我不知道”“资料不足”这类空泛句子；如果某个维度证据较弱，就基于已有证据谨慎表达，同时把强证据部分写透。",
                "7. 优先输出高信息密度内容，不要空话，不要重复复述搜索过程。",
                "8. 关键结论或每个自然段结尾尽量附上引用，格式必须是【1】或【1】【3】。",
                "9. 只能使用统一来源清单里已有的编号；如果一句话无法从来源清单直接得到，可以不引，但前提是它确实来自与问题直接相关的知识库候选资料，而不是你的常识推断。",
                "10. 不要把不相关的知识库内容、你的常识推断改写成事实句。",
                "11. 不要在正文里重复粘贴完整 URL，也不要额外生成一整节冗长的参考文献列表；引用交给【n】编号即可。",
            ]
        )
        return [
            ("system", self.RESEARCH_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(prompt_lines),
            ),
        ]

    def _normalize_history(
        self,
        history: list[dict[str, Any]] | None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        if not history:
            return []

        normalized: list[dict[str, str]] = []
        for item in history:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized.append({"role": role, "content": content})
        safe_limit = self.MAX_HISTORY_MESSAGES if limit is None else max(int(limit), 1)
        if len(normalized) <= safe_limit:
            return normalized
        return normalized[-safe_limit:]

    def _format_history_transcript(
        self,
        history: list[dict[str, Any]] | None,
        *,
        limit: int,
    ) -> str:
        lines: list[str] = []
        for index, item in enumerate(self._normalize_history(history, limit=limit), start=1):
            speaker = "用户" if item["role"] == "user" else "助手"
            lines.append(f"[{index}] {speaker}: {item['content']}")
        return "\n".join(lines)

    async def close(self) -> None:
        return None
