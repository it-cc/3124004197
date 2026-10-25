"""任务存储层：负责待办任务的持久化与增删改查。

TaskStore 把所有任务保存在一个 JSON 文件里（无需数据库），
对内提供 Python 方法，对外由 server.py 的 MCP 工具调用。
所有校验失败均抛出 ValueError，由 server.py 捕获后转成
对大模型友好的中文提示。
"""

import json
import os
import re
import threading
from datetime import datetime

# 合法截止时间：2026-10-26 或 2026-10-26 18:00
DEADLINE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")

# 优先级别名归一化（允许模型/用户输入 high、低 等写法）
PRIORITY_ALIASES = {
    "高": "高", "中": "中", "低": "低",
    "high": "高", "h": "高",
    "medium": "中", "mid": "中", "m": "中",
    "low": "低", "l": "低",
}

STATUS_FILTERS = ("all", "pending", "done")

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_info() -> str:
    d = datetime.now()
    return f"{d.strftime('%Y-%m-%d')} 星期{WEEKDAY_CN[d.weekday()]}"


def parse_deadline(text: str) -> datetime:
    """把任务里存的截止时间解析成 datetime；date-only 视为当天 23:59。"""
    text = text.strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(hour=23, minute=59)
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(f"无法解析截止时间：{text}") from exc


def is_overdue(task: dict, now: datetime | None = None) -> bool:
    """未完成且已过截止时间的任务视为逾期。"""
    if task.get("status") != "pending" or not task.get("deadline"):
        return False
    now = now or datetime.now()
    return parse_deadline(task["deadline"]) < now


def normalize_priority(text: str) -> str:
    key = (text or "").strip().lower()
    if key in ("", "-", "无"):
        return ""
    if key not in PRIORITY_ALIASES:
        raise ValueError(f"优先级只支持 高/中/低，收到：{text}")
    return PRIORITY_ALIASES[key]


def parse_tags(text) -> list[str]:
    """把 '学习,生活' 这类逗号/顿号分隔的字符串拆成标签列表。"""
    if not text:
        return []
    if isinstance(text, list):
        parts = text
    else:
        parts = re.split(r"[,，、;；\s]+", str(text))
    seen: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return seen


class TaskStore:
    """线程安全的 JSON 任务仓库。"""

    def __init__(self, path: str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._data: dict = {"next_id": 1, "tasks": []}
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("tasks"), list):
                self._data = {
                    "next_id": int(raw.get("next_id", 1)),
                    "tasks": raw["tasks"],
                }
        except (json.JSONDecodeError, OSError, ValueError):
            # 文件损坏时改名备份，避免下次保存覆盖掉原数据
            try:
                os.replace(self.path, self.path + ".bak")
            except OSError:
                pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ---------- 内部工具 ----------

    @staticmethod
    def _norm_id(task_id) -> int:
        try:
            return int(str(task_id).strip().lstrip("#"))
        except (TypeError, ValueError):
            raise ValueError(f"任务编号必须是数字，收到：{task_id!r}") from None

    def _find(self, task_id: int) -> dict:
        for t in self._data["tasks"]:
            if t["id"] == task_id:
                return t
        raise ValueError(f"找不到编号为 #{task_id} 的任务，可先用 list_tasks 查看现有任务。")

    @staticmethod
    def _new_task(task_id: int, title: str, deadline: str,
                  priority: str, tags: list[str]) -> dict:
        return {
            "id": task_id,
            "title": title,
            "deadline": deadline,        # 空字符串表示没有截止时间
            "priority": priority,        # 空 = 未设置；高/中/低
            "tags": tags,
            "status": "pending",
            "created_at": now_str(),
            "completed_at": "",
        }

    # ---------- 对外 CRUD ----------

    def add_task(self, title: str, deadline: str = "",
                 priority: str = "", tags=None) -> dict:
        title = (title or "").strip()
        if not title:
            raise ValueError("任务内容（title）不能为空。")
        if len(title) > 100:
            title = title[:100]
        deadline = (deadline or "").strip()
        if deadline and not DEADLINE_PATTERN.match(deadline):
            raise ValueError(
                f"截止时间格式不正确：{deadline}，"
                "应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM，例如 2026-10-26 18:00。")
        prio = normalize_priority(priority)
        with self._lock:
            task = self._new_task(self._data["next_id"], title,
                                  deadline, prio, parse_tags(tags))
            self._data["next_id"] += 1
            self._data["tasks"].append(task)
            self._save()
            return dict(task)

    def list_tasks(self, status: str = "all") -> list[dict]:
        status = (status or "all").strip().lower()
        if status not in STATUS_FILTERS:
            raise ValueError(f"status 只支持 all/pending/done，收到：{status}")
        with self._lock:
            tasks = [t for t in self._data["tasks"]
                     if status == "all" or t["status"] == status]
            return [dict(t) for t in self._sorted(tasks)]

    @staticmethod
    def _sorted(tasks: list[dict]) -> list[dict]:
        """待办在前（逾期最靠前 → 有截止时间按时间升序 → 无截止时间），
        已完成的排在最后。"""
        now = datetime.now()

        def sort_key(t: dict):
            done = t["status"] == "done"
            if done:
                return (1, t.get("completed_at") or "", t["id"])
            if t.get("deadline"):
                dl = parse_deadline(t["deadline"])
                return (0, dl.strftime("%Y-%m-%d %H:%M"), t["id"])
            # 无截止时间的待办：排在所有有截止时间的后面、已完成的前面
            return (0, "9999-12-31 23:59", t["id"])

        def overdue_first(t: dict):
            return 0 if is_overdue(t, now) else 1

        return sorted(tasks, key=lambda t: (overdue_first(t), sort_key(t)))

    def complete_task(self, task_id) -> dict:
        with self._lock:
            task = self._find(self._norm_id(task_id))
            if task["status"] == "done":
                raise ValueError(f"任务 #{task['id']} 已经是完成状态，无需重复标记。")
            task["status"] = "done"
            task["completed_at"] = now_str()
            self._save()
            return dict(task)

    def delete_task(self, task_id) -> dict:
        with self._lock:
            tid = self._norm_id(task_id)
            task = self._find(tid)
            self._data["tasks"].remove(task)
            self._save()
            return dict(task)

    def update_task(self, task_id, title: str | None = None,
                    deadline: str | None = None,
                    priority: str | None = None,
                    tags=None, status: str | None = None) -> dict:
        """局部更新：传 None 表示不修改该字段。

        deadline 传 "-" 表示清除截止时间；
        status 只接受 pending / done；
        tags 传空字符串表示清除所有标签。
        """
        with self._lock:
            task = self._find(self._norm_id(task_id))
            if title is not None:
                title = title.strip()
                if not title:
                    raise ValueError("任务内容不能被改成空。")
                task["title"] = title[:100]
            if deadline is not None:
                deadline = deadline.strip()
                if deadline in ("", "-"):
                    task["deadline"] = ""
                else:
                    if not DEADLINE_PATTERN.match(deadline):
                        raise ValueError(
                            f"截止时间格式不正确：{deadline}，"
                            "应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM。")
                    task["deadline"] = deadline
            if priority is not None:
                if priority.strip() in ("", "-"):
                    task["priority"] = ""
                else:
                    task["priority"] = normalize_priority(priority)
            if tags is not None:
                task["tags"] = parse_tags(tags) if str(tags).strip() else []
            if status is not None:
                status = status.strip().lower()
                if status not in ("pending", "done"):
                    raise ValueError("status 只能是 pending 或 done。")
                if status == "done" and task["status"] != "done":
                    task["status"] = "done"
                    task["completed_at"] = now_str()
                elif status == "pending" and task["status"] != "pending":
                    task["status"] = "pending"
                    task["completed_at"] = ""
            self._save()
            return dict(task)

    def clear_completed(self) -> int:
        with self._lock:
            before = len(self._data["tasks"])
            self._data["tasks"] = [t for t in self._data["tasks"]
                                   if t["status"] != "done"]
            removed = before - len(self._data["tasks"])
            if removed:
                self._save()
            return removed

    def stats(self) -> dict:
        with self._lock:
            tasks = self._data["tasks"]
            pending = sum(1 for t in tasks if t["status"] == "pending")
            overdue = sum(1 for t in tasks if is_overdue(t))
            return {
                "total": len(tasks),
                "pending": pending,
                "done": len(tasks) - pending,
                "overdue": overdue,
            }
