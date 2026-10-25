"""TodoPal MCP 服务器：把待办管理能力封装成 MCP 工具，供智能体调用。

基于官方 MCP Python SDK 的 FastMCP 实现，通过 stdio 传输与客户端通信。
每个工具的 docstring 会成为大模型看到的工具说明，务必写得清楚。
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

from storage import TaskStore, is_overdue, today_info

# 数据文件默认与代码同目录，可用环境变量 TODO_FILE 覆盖（测试时用到）
DATA_FILE = os.environ.get(
    "TODO_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json"),
)

mcp = FastMCP("todo-pal")
store = TaskStore(DATA_FILE)


def format_task(t: dict) -> str:
    """把一条任务渲染成一行可读文本，直接展示给大模型和用户。"""
    mark = "✅" if t["status"] == "done" else "⬜"
    line = f"{mark} #{t['id']} {t['title']}"
    if t["priority"]:
        line += f"[优先级:{t['priority']}]"
    if t["deadline"]:
        line += f" ｜ 截止:{t['deadline']}"
        if is_overdue(t):
            line += " ⚠️已逾期"
    if t["tags"]:
        line += f" ｜ 标签:{','.join(t['tags'])}"
    if t["status"] == "done" and t["completed_at"]:
        line += f" ｜ 完成于 {t['completed_at']}"
    return line


@mcp.tool()
def add_task(title: str, deadline: str = "", priority: str = "", tags: str = "") -> str:
    """添加一条待办任务并返回任务编号。

    title：任务内容（必填），如“完成软件工程作业”。
    deadline：截止时间（可选），格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM。
      用户说“明天下午三点”“周五”等相对时间时，必须结合今天的日期换算成上述格式；
      用户没有提到截止时间时留空，不要编造。
    priority：优先级（可选），只能是 高/中/低，用户没说就留空。
    tags：标签（可选），多个用逗号分隔，如“学习,软件工程”。
    """
    task = store.add_task(title, deadline=deadline, priority=priority, tags=tags)
    extra = f"，截止 {task['deadline']}" if task["deadline"] else ""
    prio = f"，优先级 {task['priority']}" if task["priority"] else ""
    tags_str = f"，标签 {','.join(task['tags'])}" if task["tags"] else ""
    return f"✅ 已添加任务 #{task['id']}：{task['title']}{extra}{prio}{tags_str}"


@mcp.tool()
def list_tasks(status: str = "all") -> str:
    """查看任务清单，返回格式化的任务列表。

    status 可选值：all（全部，默认）、pending（未完成）、done（已完成）。
    返回文本中“⚠️已逾期”表示任务已超过截止时间仍未完成。
    """
    tasks = store.list_tasks(status)
    stats = store.stats()
    if not tasks:
        scope = {"all": "目前没有任何任务", "pending": "当前没有未完成的任务",
                 "done": "还没有已完成的任务"}[status]
        return f"📋 {scope}。"
    lines = [format_task(t) for t in tasks]
    header = (f"📋 共 {stats['total']} 条任务："
              f"未完成 {stats['pending']}，已完成 {stats['done']}")
    if stats["overdue"]:
        header += f"，其中 {stats['overdue']} 条已逾期"
    return header + "\n" + "\n".join(lines)


@mcp.tool()
def complete_task(task_id: str) -> str:
    """把指定编号的任务标记为已完成。

    task_id：任务的数字编号，如 "3"。如果用户只说了任务名称而没说编号，
    先调用 list_tasks 找到对应编号。
    """
    task = store.complete_task(task_id)
    return f"✅ 任务 #{task['id']}「{task['title']}」已完成！"


@mcp.tool()
def delete_task(task_id: str) -> str:
    """删除指定编号的任务（不可恢复）。

    task_id：任务的数字编号，如 "3"。如果用户只说了任务名称而没说编号，
    先调用 list_tasks 找到对应编号；删除前建议与用户确认。
    """
    task = store.delete_task(task_id)
    return f"🗑️ 已删除任务 #{task['id']}「{task['title']}」。"


@mcp.tool()
def update_task(task_id: str, title: str = "", deadline: str = "",
                priority: str = "", tags: str = "", status: str = "") -> str:
    """修改指定编号的任务信息，只传需要修改的字段，不改的留空。

    task_id：任务的数字编号，如 "3"。
    title：新的任务内容。
    deadline：新的截止时间（YYYY-MM-DD 或 YYYY-MM-DD HH:MM）；传 "-" 表示清除截止时间。
    priority：新的优先级（高/中/低）；传 "-" 表示清除优先级。
    tags：新的标签（逗号分隔）；传 "-" 表示清除标签。
    status：传 "done" 表示标记完成，传 "pending" 表示改回未完成。
    """
    kwargs = {}
    if title:
        kwargs["title"] = title
    if deadline:
        kwargs["deadline"] = deadline
    if priority:
        kwargs["priority"] = priority
    if tags:
        kwargs["tags"] = tags
    if status:
        kwargs["status"] = status
    task = store.update_task(task_id, **kwargs)
    return f"✏️ 任务 #{task['id']} 已更新：\n{format_task(task)}"


@mcp.tool()
def clear_completed() -> str:
    """清空所有已完成的任务，返回删除的数量。"""
    removed = store.clear_completed()
    if removed == 0:
        return "📋 没有已完成的任务需要清理。"
    return f"🧹 已清理 {removed} 条已完成任务。"


@mcp.tool()
def task_stats() -> str:
    """统计任务数量：总数、未完成、已完成、已逾期。用户问“我今天还有多少事”时可用。"""
    s = store.stats()
    return (f"📊 任务统计：共 {s['total']} 条，未完成 {s['pending']}，"
            f"已完成 {s['done']}" + (f"，已逾期 {s['overdue']}" if s["overdue"] else ""))


# ---------------- 外部 API：Open-Meteo 天气查询（免费、无需密钥） ----------------

# WMO 天气现象代码 → 中文描述
WEATHER_CODES = {
    0: "晴", 1: "基本晴", 2: "局部多云", 3: "阴",
    45: "有雾", 48: "雾凇",
    51: "轻毛毛雨", 53: "毛毛雨", 55: "浓毛毛雨",
    56: "轻冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "轻冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴小冰雹", 99: "雷阵雨伴大冰雹",
}


def describe_weather_code(code) -> str:
    return WEATHER_CODES.get(int(code), f"天气代码 {code}")


def _geocode(city: str) -> dict:
    """调用 Open-Meteo 地理编码接口，把城市名换成经纬度。"""
    resp = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "zh", "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        raise ValueError(f"没有找到叫「{city}」的城市，请确认名称（也可尝试用拼音，如 Beijing）。")
    return results[0]


@mcp.tool()
def query_weather(city: str, days: str = "1") -> str:
    """查询指定城市未来几天的天气预报（外部天气 API）。

    city：城市中文名或拼音，如 “广州” / “Beijing”。
    days：预报天数（1~7 的数字），默认 1 表示今天。
    适合回答“明天会下雨吗”“周末适合出门吗”这类问题，
    也可以结合天气情况帮用户安排或调整任务。
    """
    try:
        n_days = max(1, min(7, int(str(days))))
    except ValueError:
        n_days = 1
    try:
        place = _geocode(city)
        where = "、".join(x for x in (place.get("admin1"), place.get("name")) if x)
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_probability_max",
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
                "forecast_days": n_days,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except ValueError:
        raise
    except Exception as exc:
        return (f"[错误] 天气服务暂时不可用（{type(exc).__name__}），"
                "请稍后再试或检查网络连接。")

    cur = data.get("current", {})
    lines = [f"🌤️ {where}（{place.get('country', '')}）当前天气："
             f"{describe_weather_code(cur.get('weather_code', -1))}，"
             f"{cur.get('temperature_2m', '?')}℃，"
             f"风速 {cur.get('wind_speed_10m', '?')} km/h"]

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    for i, date in enumerate(dates):
        rain = daily["precipitation_probability_max"][i]
        rain_tip = f"，降水概率 {rain}%" if rain is not None else ""
        lines.append(f"  {date}：{describe_weather_code(daily['weather_code'][i])}，"
                     f"{daily['temperature_2m_min'][i]}~{daily['temperature_2m_max'][i]}℃{rain_tip}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 每次启动时在 stderr 打印数据文件位置，便于排查（不污染 stdio 协议通道）
    print(f"[todo-pal] 数据文件：{DATA_FILE}", file=__import__('sys').stderr)
    mcp.run(transport="stdio")
