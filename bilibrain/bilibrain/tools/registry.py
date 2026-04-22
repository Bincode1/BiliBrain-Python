from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from bilibrain.tools.browser_read import browser_read_page_tool
from bilibrain.tools.command import run_command_tool
from bilibrain.tools.contracts import ToolApprovalMode, ToolCapability, ToolDefinition
from bilibrain.tools.filesystem import append_file_tool, list_dir_tool, make_dir_tool, read_file_tool, write_file_tool
from bilibrain.tools.obsidian import obsidian_read_note_tool, obsidian_write_note_tool
from bilibrain.tools.web_search import web_search_tool


ToolHandler = Callable[..., Awaitable]


@dataclass(frozen=True)
class ToolRegistryItem:
    definition: ToolDefinition
    handler: ToolHandler
    runtime_required: bool = False


def build_default_tool_registry() -> dict[str, ToolRegistryItem]:
    items = [
        ToolRegistryItem(
            definition=ToolDefinition(
                name="list_dir",
                description="List files and directories inside the current workspace.",
                capabilities=(ToolCapability.FILESYSTEM_READ,),
                approval_mode=ToolApprovalMode.AUTO,
            ),
            handler=list_dir_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="read_file",
                description="Read a text file inside the current workspace.",
                capabilities=(ToolCapability.FILESYSTEM_READ,),
                approval_mode=ToolApprovalMode.AUTO,
            ),
            handler=read_file_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="write_file",
                description="Write a text file inside the current workspace.",
                capabilities=(ToolCapability.FILESYSTEM_WRITE,),
                approval_mode=ToolApprovalMode.REQUIRE_APPROVAL,
            ),
            handler=write_file_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="append_file",
                description="Append text to a file inside the current workspace.",
                capabilities=(ToolCapability.FILESYSTEM_WRITE,),
                approval_mode=ToolApprovalMode.REQUIRE_APPROVAL,
            ),
            handler=append_file_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="make_dir",
                description="Create a directory inside the current workspace.",
                capabilities=(ToolCapability.FILESYSTEM_WRITE,),
                approval_mode=ToolApprovalMode.REQUIRE_APPROVAL,
            ),
            handler=make_dir_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="run_command",
                description="Run a command inside the current workspace through the configured runtime.",
                capabilities=(ToolCapability.COMMAND_EXECUTE,),
                approval_mode=ToolApprovalMode.REQUIRE_APPROVAL,
            ),
            handler=run_command_tool,
            runtime_required=True,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="web_search",
                description="Search the public web and return structured results with titles, links, and snippets.",
                capabilities=(ToolCapability.NETWORK_ACCESS,),
                approval_mode=ToolApprovalMode.AUTO,
            ),
            handler=web_search_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="browser_read_page",
                description="Open a public web page with agent-browser and return the final URL, page title, and extracted text.",
                capabilities=(ToolCapability.NETWORK_ACCESS, ToolCapability.COMMAND_EXECUTE),
                approval_mode=ToolApprovalMode.AUTO,
            ),
            handler=browser_read_page_tool,
            runtime_required=True,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="obsidian_write_note",
                description="Write a Markdown note into the active Obsidian vault using an exact vault-relative path and verify the result.",
                capabilities=(ToolCapability.EXTERNAL_NOTIFY,),
                approval_mode=ToolApprovalMode.REQUIRE_APPROVAL,
            ),
            handler=obsidian_write_note_tool,
        ),
        ToolRegistryItem(
            definition=ToolDefinition(
                name="obsidian_read_note",
                description="Read a Markdown note from the active Obsidian vault using an exact vault-relative path.",
                capabilities=(ToolCapability.EXTERNAL_NOTIFY,),
                approval_mode=ToolApprovalMode.AUTO,
            ),
            handler=obsidian_read_note_tool,
        ),
    ]
    return {item.definition.name: item for item in items}
