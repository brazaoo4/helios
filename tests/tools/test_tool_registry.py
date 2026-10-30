"""Tests for FastMCP tool registry, schema definitions, annotations, and async offloading."""

import asyncio

import pytest

from src.server import mcp, save_memory


def test_fastmcp_tool_schema_descriptions():
    tools = asyncio.run(mcp.list_tools())
    tool_map = {t.name: t for t in tools}

    # Verify all expected tools are registered
    expected_tools = {
        "recall_memories",
        "save_memory",
        "deprecate_memory",
        "recall_history",
        "revalidate_memories",
        "manage_scope_alias",
        "export_bundle",
        "manage_git_webhooks",
        "get_client_setup_bundle",
        "manage_server_config",
    }
    assert expected_tools.issubset(set(tool_map.keys()))

    # Inspect manage_server_config schema
    cfg_tool = tool_map["manage_server_config"]
    cfg_props = cfg_tool.inputSchema.get("properties", {})
    assert "action" in cfg_props
    assert "key" in cfg_props
    assert "value" in cfg_props

    # Inspect manage_git_webhooks schema
    gw_tool = tool_map["manage_git_webhooks"]
    gw_props = gw_tool.inputSchema.get("properties", {})
    assert "action" in gw_props
    assert "repos" in gw_props
    assert "include_forks" in gw_props

    # Inspect get_client_setup_bundle schema
    setup_tool = tool_map["get_client_setup_bundle"]
    setup_props = setup_tool.inputSchema.get("properties", {})
    assert "client" in setup_props
    assert "os_platform" in setup_props
    assert "instance_role" in setup_props
    assert "action" in setup_props

    # Inspect save_memory's schema
    save_tool = tool_map["save_memory"]
    schema = save_tool.inputSchema
    properties = schema.get("properties", {})

    # content description MUST contain 25-word limit notice
    content_prop = properties.get("content", {})
    assert "STRICT LIMIT: MUST be <= 25 words" in content_prop.get("description", "")

    # category description and enum
    cat_prop = properties.get("category", {})
    assert set(cat_prop.get("enum", [])) == {"rule", "fact", "preference", "episodic"}
    assert "guardrails" in cat_prop.get("description", "")

    # scope description
    scope_prop = properties.get("scope", {})
    assert "homelab" in scope_prop.get("description", "")

    # anchor_files description
    anchors_prop = properties.get("anchor_files", {})
    assert "docker-compose.yml" in anchors_prop.get("description", "")

    # replaces_id description
    replaces_prop = properties.get("replaces_id", {})
    assert "supersede" in replaces_prop.get("description", "")

    # Inspect recall_memories schema
    recall_tool = tool_map["recall_memories"]
    recall_props = recall_tool.inputSchema.get("properties", {})
    assert "category" in recall_props
    assert "status_filter" in recall_props
    assert "drift status" in recall_props["status_filter"].get("description", "")

    # Inspect revalidate_memories schema
    reval_tool = tool_map["revalidate_memories"]
    reval_props = reval_tool.inputSchema.get("properties", {})
    assert "memory_ids" in reval_props
    assert "stale memory IDs" in reval_props["memory_ids"].get("description", "")


@pytest.mark.anyio
async def test_fastmcp_async_call_thread_offloading():
    save_memory(scope="global", category="rule", content="Always offload sync tools to worker thread")
    res = await mcp.call_tool("recall_memories", {"scope": "global", "query": "offload"})
    assert res is not None
    # Output contains the rule
    content_text = res[0][0].text
    assert "Always offload sync tools" in content_text


def test_all_mcp_tools_declare_four_boolean_annotations():
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 10

    expected_annotations = {
        "recall_memories": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "recall_history": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "get_client_setup_bundle": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "export_bundle": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "save_memory": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "revalidate_memories": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "manage_server_config": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "deprecate_memory": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "manage_scope_alias": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        "manage_git_webhooks": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }

    assert {t.name for t in tools} == set(expected_annotations.keys())

    for tool in tools:
        assert tool.annotations is not None, f"Tool {tool.name} missing annotations"
        assert isinstance(tool.annotations.readOnlyHint, bool), f"{tool.name}.readOnlyHint is not bool"
        assert isinstance(tool.annotations.destructiveHint, bool), f"{tool.name}.destructiveHint is not bool"
        assert isinstance(tool.annotations.idempotentHint, bool), f"{tool.name}.idempotentHint is not bool"
        assert isinstance(tool.annotations.openWorldHint, bool), f"{tool.name}.openWorldHint is not bool"

        expected = expected_annotations[tool.name]
        assert tool.annotations.readOnlyHint is expected["readOnlyHint"]
        assert tool.annotations.destructiveHint is expected["destructiveHint"]
        assert tool.annotations.idempotentHint is expected["idempotentHint"]
        assert tool.annotations.openWorldHint is expected["openWorldHint"]
