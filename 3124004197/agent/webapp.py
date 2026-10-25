"""TodoPal Web 界面（加分项）：FastAPI 后端 + 单页聊天前端。

复用 agent.TodoAgent 的全部能力（MCP 工具循环、多轮对话记忆），
并把 uvicorn 和 MCP 客户端放在同一个 asyncio 事件循环里驱动，
处理请求时直接 await，无需跨线程桥接。

启动：python webapp.py，然后浏览器访问 http://127.0.0.1:8000
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import API_KEY, BASE_DIR, TodoAgent

STATIC_DIR = os.path.join(BASE_DIR, "static")

agent: TodoAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = TodoAgent()
    async with AsyncExitStack() as stack:
        await agent.connect(stack)
        app.state.chat_lock = asyncio.Lock()
        yield


app = FastAPI(title="TodoPal 待办小助手", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    async with app.state.chat_lock:  # 单用户演示：同一时刻只处理一条消息
        try:
            reply = await agent.chat(message)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"调用大模型失败：{exc}。请检查 .env 中的 "
                       "LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 以及网络连接。") from exc
    return {"reply": reply}


@app.get("/api/tasks")
async def tasks():
    result = await agent.session.call_tool("list_tasks", {"status": "all"})
    text = "\n".join(c.text for c in result.content
                     if getattr(c, "type", "") == "text")
    return {"text": text}


@app.post("/api/clear")
async def clear():
    agent.messages.clear()
    agent.memory.clear()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    if not API_KEY:
        print("⚠️ 尚未配置大模型 API Key：请复制 .env.example 为 .env 并填写 LLM_API_KEY。")
        sys.exit(1)
    print("TodoPal Web 启动中… 请用浏览器打开 http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
