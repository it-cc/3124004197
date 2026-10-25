"""TodoPal 智能体客户端：终端对话入口。

职责：
1. 以 stdio 方式启动并连接 MCP 服务器（server.py），获取工具列表；
2. 把 MCP 工具转换成 OpenAI function-calling 格式交给大模型；
3. 运行“模型决策 → MCP 执行工具 → 结果回喂模型”的循环；
4. 提供终端 REPL，让用户用自然语言管理待办。

模型侧使用 OpenAI 兼容接口（智谱 GLM / DeepSeek / Kimi / 通义 等均可），
通过 .env 文件配置。
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

from memory import ChatMemory
from storage import today_info
from voice import Listener, Speaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

API_KEY = os.environ.get("LLM_API_KEY", "").strip()
BASE_URL = os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip()
MODEL = os.environ.get("LLM_MODEL", "glm-4-flash").strip()

# 单次提问最多允许的工具调用轮数 / 保留的最大对话条数（超出裁剪旧历史）
MAX_TOOL_ROUNDS = 6
MAX_HISTORY = 40
MAX_TOOL_TEXT = 3000  # 工具返回文本过长时截断，防止撑爆上下文

SYSTEM_PROMPT = f"""你是「TodoPal 待办小助手」，一个帮用户管理待办任务的智能助理。今天是 {today_info()}。

你通过工具来操作用户的待办清单，工具有：add_task（添加）、list_tasks（查看）、
complete_task（完成）、delete_task（删除）、update_task（修改）、clear_completed（清理已完成）、
task_stats（统计）、query_weather（查天气，外部 API）。请遵守：

1. 用户想新增任务时调用 add_task。“明天/后天/周五/下周三”等相对时间必须按今天的日期
   换算成 YYYY-MM-DD 或 YYYY-MM-DD HH:MM；用户没提截止时间、优先级时留空，不要编造。
2. 用户想查看任务时调用 list_tasks；想知道数量概览时调用 task_stats。
3. 用户想完成/删除/修改任务时，若不知道编号，先 list_tasks 再操作；删除前先向用户确认。
4. 用户询问天气、出门要不要带伞、周末适不适合安排活动时，调用 query_weather；
   可以结合天气情况建议用户如何安排待办（比如下雨天把户外任务改期）。
5. 用户一条话里包含多件事时，可以依次调用多个工具完成。
6. 工具执行完后，用简洁自然的中文向用户汇报，不要原样复读工具输出，不要输出 Markdown 表格。
7. 与待办无关的闲聊或提问直接回答，不要调用工具。
8. 一次对话里提到的所有任务都要处理完再收尾，不要遗漏。"""

BANNER = r"""
 ______                _  _____  _
|__  / |__ _ _  _ __ _| |/ _ \ || |
  / /| '_ \ '_|| / _` | | (_) __ |
 /___|_.__/_|   \__,_|_|\___/ |_||_|
        TodoPal · 能说会做的待办清单智能体
"""

HELP_TEXT = """你可以直接用自然语言跟我对话，比如：
  · 我明天上午十点要开组会，周五要交软件工程作业，帮我记一下
  · 看看我还有哪些事没做
  · 把 2 号任务标记为完成
  · 帮我把“买牛奶”的截止时间改到后天晚上八点
  · 我今天还有多少事？
可用命令：
  /tasks  直接查看任务清单（不经过大模型，速度更快）
  /voice  开/关语音播报（朗读我的回复，离线合成）
  /mic    开/关语音输入（按回车说话，说完再按回车，离线识别）
  /clear  清空当前对话记忆
  /help   显示本帮助
  /exit   退出（或 Ctrl+C / Ctrl+D）

对话记忆会自动保存，重启程序后我仍然记得之前聊过什么。"""


class TodoAgent:
    """封装 MCP 连接、对话记忆、语音交互与大模型工具调用循环。"""

    def __init__(self, memory_file: str | None = None):
        if not API_KEY:
            raise RuntimeError(
                "尚未配置大模型 API Key：请复制 .env.example 为 .env，"
                "并填入 LLM_API_KEY（智谱/DeepSeek 等 OpenAI 兼容接口均可）。")
        self.client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)
        server_path = os.path.join(BASE_DIR, "server.py")
        self.server_params = StdioServerParameters(
            command=sys.executable,  # 用当前解释器启动，保证 MCP SDK 可用
            args=[server_path],
        )
        self.session: ClientSession | None = None
        self.tools_schema: list[dict] = []
        # 多轮对话记忆：跨会话持久化
        self.memory = ChatMemory(memory_file
                                 or os.path.join(BASE_DIR, "chat_history.json"),
                                 max_messages=MAX_HISTORY)
        self.messages: list[dict] = self.memory.load()
        if self.messages:
            print(f"🧠 已恢复 {len(self.messages)} 条历史对话记忆。")
        # 语音输入 / 输出（可选，缺依赖时自动降级）
        self.speaker = Speaker()
        self.listener = Listener()

    # ---------- MCP 连接 ----------

    async def connect(self, stack: AsyncExitStack) -> None:
        """启动 MCP 服务器子进程并完成握手。

        stdio 连接和会话都登记到调用方提供的 AsyncExitStack 里，
        由 with 语句统一负责在退出时关闭子进程。
        """
        read, write = await stack.enter_async_context(
            stdio_client(self.server_params))
        self.session = await stack.enter_async_context(
            ClientSession(read, write))
        await self.session.initialize()
        result = await self.session.list_tools()
        # MCP 工具描述 → OpenAI function-calling 的 tools 参数
        self.tools_schema = [
            {"type": "function",
             "function": {"name": t.name,
                          "description": t.description or "",
                          "parameters": t.inputSchema}}
            for t in result.tools
        ]

    # ---------- 大模型工具调用循环 ----------

    async def chat(self, user_input: str) -> str:
        """处理一条用户输入，返回助手的最终回复（成功后持久化对话记忆）。"""
        snapshot = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        try:
            answer = await self._loop()
            self.memory.save(self.messages)
            return answer
        except BaseException:
            # 出错或被中断时回滚本轮消息，避免留下“孤儿 tool_calls”破坏历史
            del self.messages[snapshot:]
            raise

    async def _loop(self) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                + self.messages,
                tools=self.tools_schema or None,
                temperature=0.5,
            )
            msg = response.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:  # 模型认为可以直接回答
                answer = (msg.content or "").strip() or "（我好像走神了，请再说一次～）"
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                result_text = await self._execute_tool(tc)
                self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                      "content": result_text})
            self._trim_history()
        answer = ("这件事需要调用的工具次数有点多，我先停在这里。"
                  "你可以把需求拆成几步，一步一步告诉我～")
        self.messages.append({"role": "assistant", "content": answer})
        return answer

    async def _execute_tool(self, tc) -> str:
        """通过 MCP 协议真正执行一次工具调用，把结果转成文本。"""
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            return f"[错误] 工具参数不是合法 JSON：{tc.function.arguments!r}，请重新调用。"
        try:
            result = await self.session.call_tool(name, args)
        except Exception as exc:  # MCP 层报错也要回喂给模型，让它自行纠正
            return f"[错误] 调用工具 {name} 失败：{exc}"
        parts = [c.text for c in result.content
                 if getattr(c, "type", "") == "text"]
        text = "\n".join(parts) or "（工具执行完毕，无返回内容）"
        if len(text) > MAX_TOOL_TEXT:
            text = text[:MAX_TOOL_TEXT] + "…（内容过长已截断）"
        return f"[错误] {text}" if result.isError else text

    def _trim_history(self) -> None:
        """历史过长时裁掉最早的若干条，保证裁剪后仍以 user 消息开头
        （避免出现没有配对 assistant 的 tool 消息）。"""
        if len(self.messages) <= MAX_HISTORY:
            return
        trimmed = self.messages[-MAX_HISTORY:]
        skip = 0
        while skip < len(trimmed) and trimmed[skip]["role"] != "user":
            skip += 1
        self.messages = trimmed[skip:]

    # ---------- 终端 REPL ----------

    async def run_repl(self) -> None:
        assert self.session is not None
        print(BANNER)
        print(f"已连接 MCP 服务器，注册工具：{', '.join(t['function']['name'] for t in self.tools_schema)}")
        print(f"对话模型：{MODEL}（{BASE_URL}）")
        print(HELP_TEXT)
        mic_enabled = False
        while True:
            try:
                prompt = "\n你 > " + ("（按回车说话，或直接打字）" if mic_enabled else "")
                user_input = await asyncio.to_thread(input, prompt)
            except (EOFError, KeyboardInterrupt):
                print("\n👋 再见！")
                return
            cmd = user_input.strip()
            if not cmd:
                if mic_enabled:  # 空回车 = 进入语音录音
                    try:
                        spoken = await asyncio.to_thread(
                            self.listener.record_until_enter)
                    except Exception as exc:
                        print(f"⚠️ 录音失败：{exc}")
                        continue
                    if not spoken:
                        continue
                    print(f"🎤 识别到：{spoken}")
                    cmd = spoken
                else:
                    continue
            if cmd.lower() in ("/exit", "/quit", "exit", "quit", "退出"):
                print("👋 再见！")
                return
            if cmd in ("/help", "帮助"):
                print(HELP_TEXT)
                continue
            if cmd == "/voice":
                print(self.speaker.toggle())
                continue
            if cmd == "/mic":
                if mic_enabled:
                    mic_enabled = False
                    print("🎤 语音输入已关闭，改回键盘输入。")
                else:
                    mic_enabled = True
                    print("🎤 语音输入已开启：按回车开始说话，说完再按回车。"
                          "（首次使用会自动下载约 40MB 离线识别模型）")
                continue
            if cmd == "/clear":
                self.messages.clear()
                self.memory.clear()
                print("🧽 已清空对话记忆。")
                continue
            if cmd == "/tasks":  # 绕过大模型直接读 MCP 工具，展示“会做”的一面
                result = await self.session.call_tool("list_tasks", {"status": "all"})
                print("\n".join(c.text for c in result.content))
                continue
            try:
                answer = await self.chat(cmd)
                print(f"\nTodoPal > {answer}")
                if self.speaker.enabled:
                    self.speaker.say(answer)
            except KeyboardInterrupt:
                print("\n（已取消本轮回复）")
            except Exception as exc:
                print(f"\n⚠️ 调用大模型失败：{exc}\n"
                      "请检查 .env 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 以及网络连接。")


async def main() -> None:
    try:
        agent = TodoAgent()
        async with AsyncExitStack() as stack:
            await agent.connect(stack)
            await agent.run_repl()
    except RuntimeError as exc:  # 配置缺失等可预期的错误，给出友好提示
        print(f"⚠️ {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"⚠️ 无法启动 MCP 服务器：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 再见！")
