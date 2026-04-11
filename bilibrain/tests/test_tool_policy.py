from bilibrain.tools.policy import ToolPolicy, evaluate_command_request


def test_policy_rejects_disallowed_command_prefix():
    policy = ToolPolicy(
        allowed_command_prefixes=[["python"], ["pytest"]],
        blocked_command_prefixes=[["rm"], ["shutdown"]],
        default_timeout_seconds=30,
    )

    decision = evaluate_command_request(policy, "rm -rf data")

    assert decision.allowed is False
    assert decision.requires_approval is False


def test_policy_allows_command_without_approval_by_default():
    policy = ToolPolicy(
        blocked_command_prefixes=[["rm"], ["shutdown"]],
        default_timeout_seconds=30,
    )

    decision = evaluate_command_request(policy, "python -V")

    assert decision.allowed is True
    assert decision.requires_approval is False
