from bilibrain.tools.contracts import ToolCallRequest


def test_tool_call_request_requires_workspace_and_tool_name():
    payload = ToolCallRequest.model_validate(
        {
            "workspace_id": "ws-1",
            "tool_name": "read_file",
            "arguments": {"path": "notes.txt"},
        }
    )

    assert payload.workspace_id == "ws-1"
    assert payload.tool_name == "read_file"
    assert payload.arguments["path"] == "notes.txt"
