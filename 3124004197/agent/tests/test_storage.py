"""TaskStore 存储层单元测试（不依赖网络与大模型）。"""

import os
from datetime import datetime, timedelta

import pytest

from storage import TaskStore, is_overdue, normalize_priority, parse_tags


@pytest.fixture()
def store(tmp_path):
    return TaskStore(str(tmp_path / "tasks.json"))


def tomorrow(hours=None):
    d = datetime.now() + timedelta(days=1)
    if hours is None:
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d") + f" {hours:02d}:00"


class TestAddAndList:
    def test_add_minimal(self, store):
        t = store.add_task("写作业")
        assert t["id"] == 1
        assert t["status"] == "pending"
        assert t["deadline"] == "" and t["priority"] == "" and t["tags"] == []

    def test_add_full_fields(self, store):
        t = store.add_task("开组会", deadline=tomorrow(10), priority="高", tags="学习, 会议")
        assert t["deadline"] == tomorrow(10)
        assert t["priority"] == "高"
        assert t["tags"] == ["学习", "会议"]

    def test_add_empty_title_rejected(self, store):
        with pytest.raises(ValueError):
            store.add_task("   ")

    def test_add_invalid_deadline_rejected(self, store):
        with pytest.raises(ValueError):
            store.add_task("写作业", deadline="下周三")

    def test_priority_alias_normalized(self, store):
        assert normalize_priority("high") == "高"
        assert normalize_priority("Medium") == "中"
        t = store.add_task("a", priority="LOW")
        assert t["priority"] == "低"

    def test_invalid_priority_rejected(self, store):
        with pytest.raises(ValueError):
            store.add_task("a", priority="紧急")

    def test_tags_dedup_and_split(self, store):
        assert parse_tags("学习，生活、 生活 ,工作") == ["学习", "生活", "工作"]
        assert parse_tags("") == []


class TestListAndSort:
    def test_status_filter(self, store):
        a = store.add_task("未完成")
        store.add_task("已完成")
        store.complete_task(2)
        pending = store.list_tasks("pending")
        done = store.list_tasks("done")
        assert [t["id"] for t in pending] == [a["id"]]
        assert [t["id"] for t in done] == [2]

    def test_invalid_status_rejected(self, store):
        with pytest.raises(ValueError):
            store.list_tasks("finished")

    def test_overdue_first_then_deadline_then_undated(self, store):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        store.add_task("普通无日期")            # id 1，无日期
        store.add_task("明天到期", deadline=tomorrow())   # id 2
        store.add_task("昨天到期", deadline=yesterday)    # id 3，已逾期
        ids = [t["id"] for t in store.list_tasks()]
        assert ids == [3, 2, 1]  # 逾期 → 有日期 → 无日期


class TestCompleteUpdateDelete:
    def test_complete_sets_timestamp(self, store):
        store.add_task("洗衣服")
        t = store.complete_task("1")  # 字符串编号也能识别
        assert t["status"] == "done" and t["completed_at"]

    def test_complete_twice_rejected(self, store):
        store.add_task("洗衣服")
        store.complete_task(1)
        with pytest.raises(ValueError):
            store.complete_task(1)

    def test_update_partial_fields(self, store):
        store.add_task("买牛奶", priority="低")
        t = store.update_task(1, title="买两箱牛奶", deadline=tomorrow(20))
        assert t["title"] == "买两箱牛奶"
        assert t["deadline"] == tomorrow(20)
        assert t["priority"] == "低"  # 未传的字段不受影响

    def test_update_clear_with_dash(self, store):
        store.add_task("买牛奶", deadline=tomorrow(), priority="高")
        t = store.update_task(1, deadline="-", priority="-")
        assert t["deadline"] == "" and t["priority"] == ""

    def test_update_status_roundtrip(self, store):
        store.add_task("买牛奶")
        t = store.update_task(1, status="done")
        assert t["status"] == "done" and t["completed_at"]
        t = store.update_task(1, status="pending")
        assert t["status"] == "pending" and t["completed_at"] == ""

    def test_update_invalid_deadline_rejected(self, store):
        store.add_task("买牛奶")
        with pytest.raises(ValueError):
            store.update_task(1, deadline="三天后")

    def test_delete_missing_rejected(self, store):
        with pytest.raises(ValueError):
            store.delete_task(99)

    def test_delete_and_id_no_reuse(self, store):
        store.add_task("一")
        store.add_task("二")
        store.delete_task(1)
        t = store.add_task("三")
        assert t["id"] == 3                      # 新编号继续递增
        assert [x["id"] for x in store.list_tasks()] == [2, 3]


class TestClearAndStats:
    def test_clear_completed(self, store):
        store.add_task("一")
        store.add_task("二")
        store.complete_task(2)
        assert store.clear_completed() == 1
        assert store.clear_completed() == 0
        assert [t["id"] for t in store.list_tasks()] == [1]

    def test_stats_counts_overdue(self, store):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        store.add_task("逾期", deadline=yesterday)
        store.add_task("正常")
        store.add_task("完成", deadline=yesterday)
        store.complete_task(3)
        s = store.stats()
        assert s == {"total": 3, "pending": 2, "done": 1, "overdue": 1}


class TestPersistence:
    def test_data_survives_restart(self, tmp_path):
        path = str(tmp_path / "tasks.json")
        s1 = TaskStore(path)
        s1.add_task("跨进程存活", deadline=tomorrow(9), priority="中", tags="测试")
        s1.complete_task(1)
        s2 = TaskStore(path)  # 模拟重新启动
        tasks = s2.list_tasks("done")
        assert len(tasks) == 1
        assert tasks[0]["title"] == "跨进程存活"
        assert tasks[0]["priority"] == "中"

    def test_corrupted_file_backed_up_not_crash(self, tmp_path):
        path = tmp_path / "tasks.json"
        path.write_text("{不是合法的JSON", encoding="utf-8")
        store = TaskStore(str(path))
        assert store.list_tasks() == []
        assert (tmp_path / "tasks.json.bak").exists()  # 原文件被备份


class TestIsOverdue:
    def test_overdue_rules(self, store):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        store.add_task("a", deadline=yesterday)
        store.add_task("b", deadline=tomorrow())
        store.add_task("c", deadline=yesterday)
        store.complete_task(3)
        store.add_task("d")
        tasks = {t["title"]: t for t in store.list_tasks()}  # 取最新状态
        assert is_overdue(tasks["a"]) is True
        assert is_overdue(tasks["b"]) is False
        assert is_overdue(tasks["c"]) is False  # 已完成不算逾期
        assert is_overdue(tasks["d"]) is False
