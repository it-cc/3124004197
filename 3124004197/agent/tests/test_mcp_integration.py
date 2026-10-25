"""MCP 集成测试：以真实 stdio 子进程方式启动 server.py，
走完整的 MCP 协议握手与工具调用，验证“会做”这一半的能力。
不需要网络与大模型 API。
"""

import asyncio
import os
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")

EXPECTED_TOOLS = {"add_task", "list_tasks", "complete_task", "delete_task",
                  "update_task", "clear_completed", "task_stats", "query_weather"}


def run_with_server(tmp_path, coro_fn):
    """在独立的 MCP 会话里执行 coro_fn(session)，数据文件隔离到 tmp_path。"""
    async def runner():
        params = StdioServerParameters(
            command=sys.executable,
            args=[SERVER_PATH],
            env={**os.environ, "TODO_FILE": str(tmp_path / "tasks.json")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await coro_fn(session)
    return asyncio.run(runner())


def test_initialize_and_list_tools(tmp_path):
    async def step(session):
        result = await session.list_tools()
        return {t.name for t in result.tools}

    tools = run_with_server(tmp_path, step)
    assert tools == EXPECTED_TOOLS

    # 每个工具都应带有非空描述（这是大模型选择工具的依据）
    async def check_desc(session):
        result = await session.list_tools()
        return all(t.description for t in result.tools)

    assert run_with_server(tmp_path, check_desc) is True


def test_add_then_list_via_mcp(tmp_path):
    async def step(session):
        added = await session.call_tool(
            "add_task",
            {"title": "完成软件工程作业", "deadline": "2026-10-27 23:59",
             "priority": "高", "tags": "学习,软件工程"})
        listed = await session.call_tool("list_tasks", {"status": "pending"})
        return added, listed

    added, listed = run_with_server(tmp_path, step)
    assert added.isError is False
    assert "#1" in added.content[0].text
    text = listed.content[0].text
    assert "完成软件工程作业" in text
    assert "2026-10-27 23:59" in text
    assert "⚠️" not in text  # 未逾期


def test_complete_update_delete_workflow(tmp_path):
    async def step(session):
        await session.call_tool("add_task", {"title": "买牛奶"})
        done = await session.call_tool("complete_task", {"task_id": "1"})
        updated = await session.call_tool(
            "update_task", {"task_id": "1", "title": "买两箱牛奶",
                            "priority": "高"})
        stats = await session.call_tool("task_stats", {})
        cleared = await session.call_tool("clear_completed", {})
        return done, updated, stats, cleared

    done, updated, stats, cleared = run_with_server(tmp_path, step)
    assert "已完成" in done.content[0].text
    assert "买两箱牛奶" in updated.content[0].text
    assert "已完成 1" in stats.content[0].text
    assert "1 条" in cleared.content[0].text


def test_invalid_input_returns_tool_error_not_crash(tmp_path):
    async def step(session):
        bad_deadline = await session.call_tool(
            "add_task", {"title": "x", "deadline": "后天"})
        bad_id = await session.call_tool("complete_task", {"task_id": "999"})
        return bad_deadline, bad_id

    bad_deadline, bad_id = run_with_server(tmp_path, step)
    # MCP 约定：工具内业务错误用 isError=True 返回文本，而不是让服务器崩溃
    assert bad_deadline.isError is True
    assert "格式" in bad_deadline.content[0].text
    assert bad_id.isError is True
    assert "找不到" in bad_id.content[0].text


def test_weather_external_api_via_mcp(tmp_path):
    """外部 API 交互（加分项）：通过 MCP 调用 Open-Meteo 天气查询。"""
    async def step(session):
        return await session.call_tool(
            "query_weather", {"city": "Beijing", "days": "1"})

    result = run_with_server(tmp_path, step)
    text = result.content[0].text
    if result.isError and "不可用" in text:
        pytest.skip("当前环境无法访问 Open-Meteo 天气服务")
    assert result.isError is False
    assert "北京" in text
    assert "℃" in text
