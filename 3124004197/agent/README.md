# TodoPal · 能说会做的待办清单智能体

> 软件工程课程作业 · 基于 MCP（Model Context Protocol）构建的 AI 智能体
> 既能自然语言对话（能说），又能真正执行操作（会做）

## 项目简介

TodoPal 是一个待办清单智能助理：用户用中文自然语言说话，它理解意图后
通过 MCP 协议调用工具，真正地增删改查任务数据、查询天气，并把结果用
自然语言汇报给用户。

| 能力 | 说明 |
| ---- | ---- |
| 🗣️ 能说 | 中文自然语言多轮对话，自动保存对话记忆，重启程序也不会忘 |
| 🛠️ 会做 | 通过 MCP 调用 8 个工具：增删改查任务、统计、清空、查天气（外部 API） |
| 💬 两种入口 | 终端 CLI（`agent.py`）+ 网页界面（`webapp.py`） |
| 🎤 语音 | 离线语音输入（vosk 识别）+ 语音播报（pyttsx3 合成）+ 网页端朗读 |
| 🌦️ 外部 API | Open-Meteo 天气查询（免费、无需密钥），可结合天气建议任务安排 |

## 架构一览

![架构图](docs/architecture.png)

- `agent.py` / `webapp.py`：智能体客户端（终端 / 网页两种入口），负责对话与工具调度
- `server.py`：MCP 服务器，通过 stdio 与客户端通信，提供 8 个工具
- `storage.py`：TaskStore 存储层，任务数据落在本地 `tasks.json`
- `memory.py`：多轮对话记忆，持久化到 `chat_history.json`
- `voice.py`：可选语音模块，缺依赖时自动降级为纯文字

## 快速开始

环境要求：Python 3.10+，一个 OpenAI 兼容的大模型 API Key
（智谱 GLM / DeepSeek / Kimi / 通义 均可，推荐智谱 `glm-4-flash`，免费）。

```bash
# 1. 进入项目目录，创建虚拟环境
cd agent
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS:
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt
# （可选）启用语音功能：pip install -r requirements-voice.txt

# 3. 配置大模型 API Key
cp .env.example .env     # Windows 用 copy
# 编辑 .env，填入你的 LLM_API_KEY

# 4a. 启动终端版
python agent.py

# 4b. 或启动网页版，浏览器打开 http://127.0.0.1:8000
python webapp.py
```

### 玩法示例

```text
你 > 我明天上午十点要开组会，周五要交软件工程作业，帮我记一下
TodoPal > 好的，已经帮你记下两条任务：
          #1 开组会（明天 2026-10-26 10:00）
          #2 交软件工程作业（2026-10-30）

你 > 看看我还有哪些事没做
你 > 把 1 号任务标记为完成
你 > 明天广州会下雨吗？
你 > 我今天还有多少事？
```

终端可用命令：`/tasks` 直接看清单、`/voice` 语音播报开关、
`/mic` 语音输入开关、`/clear` 清空记忆、`/help`、`/exit`。

### 大模型配置参考（.env）

| 提供商 | LLM_BASE_URL | LLM_MODEL |
| ------ | ------------ | --------- |
| 智谱 GLM（默认） | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

## 目录结构

```text
agent/
├── agent.py               # 智能体客户端：MCP 连接、工具调用循环、CLI、语音集成
├── webapp.py              # Web 后端（FastAPI）：/api/chat、/api/tasks、/api/clear
├── server.py              # MCP 服务器：8 个工具（任务管理 7 个 + 天气查询）
├── storage.py             # 任务存储层 TaskStore（JSON 持久化）
├── memory.py              # 多轮对话记忆（跨会话持久化、合法性校验）
├── voice.py               # 语音输入（vosk）/ 输出（pyttsx3），可选
├── static/                # 网页前端（index.html / style.css / app.js）
├── docs/                  # 架构图与业务流程图（graphviz 源码 + PNG）
├── tests/                 # 单元测试 + MCP 协议集成测试
├── requirements.txt       # 必需依赖
├── requirements-voice.txt # 可选语音依赖
├── .env.example           # 环境变量模板
└── blog.md                # 博客园作业博文
```

## 测试

```bash
python -m pytest -v
```

共 44 个用例：任务存储层单元测试、MCP 服务器真实子进程集成测试
（stdio 握手 + 工具调用）、对话记忆测试、天气 API 集成测试等。

## 常见问题

- **提示未配置 API Key**：复制 `.env.example` 为 `.env` 并填入 `LLM_API_KEY`。
- **语音不可用**：语音是可选功能，`pip install -r requirements-voice.txt` 即可；
  Linux 语音播报需另装 `espeak-ng`（`sudo apt install espeak-ng`）。
- **语音识别首次很慢**：首次使用会自动下载约 40MB 离线中文模型，之后完全离线。
- **网页打不开**：确认 `python webapp.py` 在运行，访问 http://127.0.0.1:8000。
