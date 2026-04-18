from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase


class SkillPolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class SkillPolicyRule:
    action: SkillPolicyAction
    patterns: tuple[str, ...] = field(default_factory=tuple)
    actors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillPolicy:
    default_action: SkillPolicyAction = SkillPolicyAction.ALLOW
    rules: tuple[SkillPolicyRule, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillPolicyDecision:
    action: SkillPolicyAction
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == SkillPolicyAction.ALLOW

    @property
    def requires_approval(self) -> bool:
        return self.action == SkillPolicyAction.ASK


def _normalize_patterns(patterns: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(str(item or "").strip() for item in patterns if str(item or "").strip())


def _match_rule(rule: SkillPolicyRule, *, skill_name: str, actor: str) -> bool:
    normalized_actor = str(actor or "").strip()
    if rule.actors and normalized_actor not in rule.actors:
        return False
    return any(fnmatchcase(skill_name, pattern) for pattern in rule.patterns)


def evaluate_skill_request(
    policy: SkillPolicy,
    *,
    skill_name: str,
    actor: str = "agent",
) -> SkillPolicyDecision:
    normalized_name = str(skill_name or "").strip()
    normalized_actor = str(actor or "").strip() or "agent"
    if not normalized_name:
        return SkillPolicyDecision(
            action=SkillPolicyAction.DENY,
            reason="Empty skill name is not allowed.",
        )

    for rule in policy.rules:
        if _match_rule(rule, skill_name=normalized_name, actor=normalized_actor):
            actor_scope = f" for actor '{normalized_actor}'" if rule.actors else ""
            return SkillPolicyDecision(
                action=rule.action,
                reason=f"Skill '{normalized_name}' matched {rule.action.value} policy{actor_scope}.",
            )

    return SkillPolicyDecision(
        action=policy.default_action,
        reason=f"Skill '{normalized_name}' follows default {policy.default_action.value} policy.",
    )


def _parse_action(value: str, *, default: SkillPolicyAction = SkillPolicyAction.ALLOW) -> SkillPolicyAction:
    normalized = str(value or "").strip().lower()
    if normalized == SkillPolicyAction.DENY.value:
        return SkillPolicyAction.DENY
    if normalized == SkillPolicyAction.ASK.value:
        return SkillPolicyAction.ASK
    if normalized == SkillPolicyAction.ALLOW.value:
        return SkillPolicyAction.ALLOW
    return default


def _build_rules(action: SkillPolicyAction, patterns: tuple[str, ...], *, actors: tuple[str, ...] = ()) -> list[SkillPolicyRule]:
    normalized_patterns = _normalize_patterns(patterns)
    if not normalized_patterns:
        return []
    normalized_actors = tuple(str(actor or "").strip() for actor in actors if str(actor or "").strip())
    return [SkillPolicyRule(action=action, patterns=normalized_patterns, actors=normalized_actors)]


def _parse_actor_overrides(raw: str) -> list[SkillPolicyRule]:
    rules: list[SkillPolicyRule] = []
    payload = str(raw or "").strip()
    if not payload:
        return rules

    for actor_block in payload.split(";"):
        block = str(actor_block or "").strip()
        if not block or "=" not in block:
            continue
        actor_name, rule_block = block.split("=", 1)
        normalized_actor = str(actor_name or "").strip()
        if not normalized_actor:
            continue
        for raw_rule in rule_block.split("|"):
            segment = str(raw_rule or "").strip()
            if not segment or ":" not in segment:
                continue
            action_name, raw_patterns = segment.split(":", 1)
            action = _parse_action(action_name, default=SkillPolicyAction.ALLOW)
            patterns = tuple(
                str(item or "").strip()
                for item in raw_patterns.split(",")
                if str(item or "").strip()
            )
            rules.extend(_build_rules(action, patterns, actors=(normalized_actor,)))
    return rules


def build_skill_policy(settings) -> SkillPolicy:
    rules: list[SkillPolicyRule] = []
    rules.extend(_parse_actor_overrides(getattr(settings, "skills_policy_overrides", "")))
    rules.extend(_build_rules(SkillPolicyAction.DENY, getattr(settings, "skills_policy_deny_patterns", ())))
    rules.extend(_build_rules(SkillPolicyAction.ASK, getattr(settings, "skills_policy_ask_patterns", ())))
    rules.extend(_build_rules(SkillPolicyAction.ALLOW, getattr(settings, "skills_policy_allow_patterns", ())))
    return SkillPolicy(
        default_action=_parse_action(
            getattr(settings, "skills_policy_default_action", SkillPolicyAction.ALLOW.value),
            default=SkillPolicyAction.ALLOW,
        ),
        rules=tuple(rules),
    )
