"""多轮对话记忆 ChatMemory 的单元测试（加分项验证）。"""

from memory import ChatMemory


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "h.json")
    msgs = [
        {"role": "user", "content": "明天提醒我开会"},
        {"role": "assistant", "content": "好的，已记录。"},
    ]
    ChatMemory(path).save(msgs)
    # 新实例模拟程序重启后恢复
    assert ChatMemory(path).load() == msgs


def test_save_is_atomic_no_tmp_leftover(tmp_path):
    path = str(tmp_path / "h.json")
    ChatMemory(path).save([{"role": "user", "content": "hi"}])
    assert not (tmp_path / "h.json.tmp").exists()


def test_invalid_roles_dropped(tmp_path):
    path = str(tmp_path / "h.json")
    msgs = [
        {"role": "system", "content": "注入内容"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "你好呀"},
        {"nonsense": True},
    ]
    ChatMemory(path).save(msgs)
    loaded = ChatMemory(path).load()
    assert [m["content"] for m in loaded if "content" in m] == ["你好", "你好呀"]
    assert loaded[0]["role"] == "user"


def test_orphan_tool_message_dropped(tmp_path):
    path = str(tmp_path / "h.json")
    msgs = [
        {"role": "tool", "tool_call_id": "x", "content": "孤儿结果"},
        {"role": "user", "content": "看看任务"},
        {"role": "assistant", "content": "没有任务"},
    ]
    ChatMemory(path).save(msgs)
    loaded = ChatMemory(path).load()
    assert all(m["role"] != "tool" for m in loaded)
    assert loaded[0]["role"] == "user"


def test_complete_tool_chain_kept(tmp_path):
    path = str(tmp_path / "h.json")
    msgs = [
        {"role": "user", "content": "加个任务"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "add_task", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "已添加 #1"},
        {"role": "assistant", "content": "已经加好啦"},
    ]
    ChatMemory(path).save(msgs)
    assert ChatMemory(path).load() == msgs


def test_interrupted_tool_chain_removed(tmp_path):
    """对话在工具调用中途被打断：恢复时必须移除残缺的调用链。"""
    path = str(tmp_path / "h.json")
    msgs = [
        {"role": "user", "content": "加个任务"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "add_task", "arguments": "{}"}}]},
        # 工具结果丢了，用户又发来一条
        {"role": "user", "content": "算了不用了"},
    ]
    ChatMemory(path).save(msgs)
    loaded = ChatMemory(path).load()
    # 残缺的 assistant tool_calls 被移除，两条 user 保留，序列合法
    assert [m["role"] for m in loaded] == ["user", "user"]
    assert loaded[1]["content"] == "算了不用了"


def test_truncated_history_starts_with_user(tmp_path):
    path = str(tmp_path / "h.json")
    msgs = [{"role": "user", "content": f"消息{i}"} for i in range(6)]
    memory = ChatMemory(path, max_messages=4)
    memory.save(msgs)
    loaded = memory.load()
    assert len(loaded) == 4
    assert loaded[0]["content"] == "消息2"


def test_corrupted_file_returns_empty(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{{{不是JSON", encoding="utf-8")
    assert ChatMemory(str(path)).load() == []


def test_clear_removes_file(tmp_path):
    path = str(tmp_path / "h.json")
    memory = ChatMemory(path)
    memory.save([{"role": "user", "content": "hi"}])
    memory.clear()
    assert memory.load() == []
    memory.clear()  # 重复清空不报错
