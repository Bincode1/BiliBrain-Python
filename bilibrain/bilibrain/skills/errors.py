class SkillError(RuntimeError):
    """Base error for skill operations."""


class SkillNotFoundError(SkillError):
    """Requested skill does not exist."""


class SkillPolicyError(SkillError):
    """Skill is blocked by current policy."""


class SkillApprovalRequiredError(SkillPolicyError):
    """Skill access requires explicit approval."""


class SkillParseError(SkillError):
    """Skill manifest is malformed."""
