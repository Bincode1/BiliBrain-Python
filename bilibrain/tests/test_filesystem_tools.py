import asyncio

from bilibrain.tools.errors import WorkspaceError
from bilibrain.tools.filesystem import append_file_tool, read_file_tool, write_file_tool


def test_read_file_tool_reads_text_inside_workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    target = root / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    result = asyncio.run(
        read_file_tool(
            workspace_root=root,
            arguments={"path": "notes.txt"},
        )
    )

    assert result.ok is True
    assert result.payload["content"] == "hello"


def test_write_and_append_file_tools_modify_workspace_file(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()

    write_result = asyncio.run(
        write_file_tool(
            workspace_root=root,
            arguments={"path": "notes.txt", "content": "hello"},
        )
    )
    append_result = asyncio.run(
        append_file_tool(
            workspace_root=root,
            arguments={"path": "notes.txt", "content": "\nworld"},
        )
    )

    assert write_result.ok is True
    assert append_result.ok is True
    assert (root / "notes.txt").read_text(encoding="utf-8") == "hello\nworld"


def test_write_file_tool_rejects_workspace_root_as_file_target(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()

    try:
        asyncio.run(
            write_file_tool(
                workspace_root=root,
                arguments={"path": ".", "content": "hello"},
            )
        )
    except WorkspaceError as exc:
        assert "file path" in str(exc).lower()
    else:
        raise AssertionError("expected WorkspaceError")
