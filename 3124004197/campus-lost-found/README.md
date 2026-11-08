# 寻回 · 校园失物找回助手

一个可运行的校园失物／拾物公告板：发布信息，AI 找候选，提交认领说明，由发布者核验并记录归还。支持 DeepSeek 匹配和按物品持续咨询。

## 一键运行

```bash
"/home/cc/workspace/homework/software engineering/3124004197/campus-lost-found/start.sh" --demo
```

默认使用 8080～8090 中可用端口并打开浏览器。终端会输出真实地址；不要用 `0.0.0.0` 作为浏览器访问地址。保持启动终端运行，Ctrl+C 停止服务。可以添加 `--no-browser` 只输出地址。

`--demo` 会首次加入 8 条明确标记为“演示数据”的记录，演示记录也持久保存。演示账号：

| 账号 | 密码 | 用途 |
|---|---|---|
| demo_lost | demo123456 | 演示丢失者发布、匹配和认领 |
| demo_found | demo123456 | 演示拾物者核验与归还 |

这些账号和记录不代表真实用户或物品。演示账号新发布的信息也自动标记为演示。正式上线使用新的 `DATA_DIR`，不启用演示数据，并注册自己的账号。

正常启动（不新增演示数据）：

```bash
./start.sh
```

如果虚拟环境不存在，脚本会创建 `.venv` 并安装基础依赖。手动启动：

```bash
cd "/home/cc/workspace/homework/software engineering/3124004197/campus-lost-found"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn campus_app.main:app --app-dir "$PWD" --host 0.0.0.0 --port 8080
```

## 功能

- 注册、登录、退出；密码通过 PBKDF2 加盐散列，登录会话使用 HttpOnly Cookie。
- 发布寻物／拾物：类别、描述、地点、日期、照片及仅发布者可查看的私密核验特征。
- 公开搜索、分类、状态筛选、分页；管理本人记录、编辑、关闭与删除。
- DeepSeek 线索匹配：按类别、描述、地点和日期初筛，AI 比较候选并给出理由与核对问题。
- 未配置或 API 失败时明确回退为关键词匹配，不假称 AI 成功。
- 认领／提供线索：请求说明仅发布者及提交者可见；只有发布者可以核验。
- 核验通过后记录归还，并允许双方查看对方联系方式；未通过不共享联系方式。
- 按用户＋物品保存持续咨询，最近 20 轮作为模型上下文，刷新页面可恢复近期对话。
- 照片限制 5 MiB，支持 JPEG／PNG／WebP；校验图片并重编码，移除原始 EXIF 元信息。

## DeepSeek 配置

密钥只放在项目根目录 `.env`，不要写入 `.env.example`、前端或提交到 Git。

```dotenv
DEEPSEEK_API_KEY=填写你的DeepSeek密钥
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
AI_TIMEOUT=60
COOKIE_SECURE=0
ENABLE_DEMO=0
```

已有开发环境的 DeepSeek 私有配置已迁移到本项目的 `.env`，不会在页面显示。修改配置后停止旧服务并重新运行。

真实线索与演示线索分开匹配。AI 只接收公开文字信息，以及当前用户的咨询内容和近期问答，不接收账号联系方式或私密核验特征。首版不使用照片识别，照片用于人工比对。

相关度得分不是“物主概率”。AI 不能自动认领、共享联系方式或确认归属。发布者应核对未公开特征后确认。首版使用普通账号，没有学校 SSO 或官方身份认证。

## 存储与部署

SQLite、重编码后的图片存储在 `data/`。会话和对话持久保存。不要将 `.env` 或 `data/` 打包进公共仓库。建议单个 Uvicorn worker，保持同一会话请求顺序及 AI 并发限制。

正式部署可使用 Docker：

```bash
docker build -t campus-lost-found .
docker run --env-file .env -e DATA_DIR=/app/data -p 8080:8080 \
  -v campus-lost-found-data:/app/data campus-lost-found
```

使用 HTTPS 反向代理，并设置 `COOKIE_SECURE=1`；代理应保留浏览器 Host。老师可访问的公网域名仍需由团队部署并提供，本地服务不等同于已上线。

## 验证

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
env -u PYTHONPATH PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

测试覆盖授权与私密字段、核验与联系方式共享、重复请求、图片校验、AI 降级及候选白名单、对话隔离、跨站请求和演示数据持久化。浏览器验证结果见 [验收记录](docs/验收记录.md)。

## 文档

- [作业博客与需求分析（合并版）](docs/作业博客.md)
- [设计方案](docs/设计方案.md)
- [演示与答辩流程](docs/演示与答辩流程.md)

官方 API 文档：https://api-docs.deepseek.com/api/create-chat-completion
