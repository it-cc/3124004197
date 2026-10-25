"""多轮对话记忆模块：把对话历史持久化到 JSON 文件。

让智能体在程序重启后仍记得之前聊过什么（加分项：多轮对话记忆）。
只保存 user / assistant / tool 三类消息；加载时做合法性校验，
损坏或不合法的历史直接丢弃，绝不让智能体带着坏上下文启动。
"""

import json
import os
import threading

VALID_ROLES = ("user", "assistant", "tool")


class ChatMemory:
    """线程安全的对话记忆仓（进程内加锁，进程间各自持有文件副本）。"""

    def __init__(self, path: str, max_messages: int = 40):
        self.path = str(path)
        self.max_messages = max_messages
        self._lock = threading.Lock()

    # ---------- 加载 / 校验 ----------

    def load(self) -> list[dict]:
        """启动时恢复历史；文件不存在或内容非法时返回空列表。"""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, list):
                return []
            cleaned = [m for m in raw if self._valid(m)]
            # 必须以 user 开头，且不能出现没有配对 assistant 的 tool 消息
            return self._drop_orphans(cleaned)
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _valid(msg) -> bool:
        if not isinstance(msg, dict) or msg.get("role") not in VALID_ROLES:
            return False
        if msg["role"] == "tool":
            return bool(msg.get("tool_call_id"))
        if msg["role"] == "assistant":
            has_calls = bool(msg.get("tool_calls"))
            return bool(msg.get("content")) or has_calls
        return isinstance(msg.get("content"), str)

    @staticmethod
    def _drop_orphans(messages: list[dict]) -> list[dict]:
        """去掉开头非 user 的消息，以及未完成配对的 assistant 工具调用链。"""
        start = 0
        while start < len(messages) and messages[start]["role"] != "user":
            start += 1
        messages = messages[start:]
        cleaned: list[dict] = []
        expecting_tool_ids: set[str] = set()

        def drop_incomplete_chain():
            """上一轮工具调用没等到结果（对话被中断）：移除未完成的 assistant 调用。"""
            for i in range(len(cleaned) - 1, -1, -1):
                if cleaned[i]["role"] == "assistant" and cleaned[i].get("tool_calls"):
                    del cleaned[i]
                    break
            expecting_tool_ids.clear()

        for msg in messages:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                cleaned.append(msg)
                expecting_tool_ids |= {tc.get("id") for tc in msg["tool_calls"]
                                       if tc.get("id")}
                continue
            if msg["role"] == "tool":
                if msg.get("tool_call_id") in expecting_tool_ids:
                    expecting_tool_ids.discard(msg["tool_call_id"])
                    cleaned.append(msg)
                continue  # 孤儿 tool 消息直接丢弃
            if expecting_tool_ids:  # 还没等到工具结果又来了新消息：链条不完整
                drop_incomplete_chain()
            cleaned.append(msg)
        return cleaned

    # ---------- 保存 / 清空 ----------

    def save(self, messages: list[dict]) -> None:
        with self._lock:
            keep = [m for m in messages if self._valid(m)][-self.max_messages:]
            keep = self._drop_orphans(keep)
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(keep, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)  # 原子替换，避免写一半被截断

    def clear(self) -> None:
        with self._lock:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
