"""服务器工具层纯函数与语音文本清洗的单元测试。"""

from server import describe_weather_code, format_task
from voice import clean_for_tts


class TestWeatherCode:
    def test_common_codes(self):
        assert describe_weather_code(0) == "晴"
        assert describe_weather_code(3) == "阴"
        assert describe_weather_code(61) == "小雨"
        assert describe_weather_code(95) == "雷阵雨"

    def test_unknown_code_falls_back(self):
        assert describe_weather_code(42) == "天气代码 42"
        assert describe_weather_code(-1) == "天气代码 -1"


class TestFormatTask:
    def test_pending_task_fields(self):
        line = format_task({
            "id": 3, "title": "交作业", "status": "pending",
            "deadline": "2026-10-27 23:59", "priority": "高",
            "tags": ["学习"], "completed_at": "",
        })
        assert "#3 交作业" in line
        assert "优先级:高" in line
        assert "截止:2026-10-27 23:59" in line
        assert "标签:学习" in line
        assert "已逾期" not in line

    def test_done_task(self):
        line = format_task({
            "id": 1, "title": "洗衣服", "status": "done",
            "deadline": "", "priority": "", "tags": [],
            "completed_at": "2026-10-25 10:00",
        })
        assert "✅" in line and "完成于 2026-10-25 10:00" in line


class TestCleanForTTS:
    def test_strips_emoji_and_symbols(self):
        raw = "✅ 已添加任务 #3：写作业（截止 2026-10-26）📋"
        out = clean_for_tts(raw)
        assert "✅" not in out and "📋" not in out
        assert "已添加任务" in out and "写作业" in out

    def test_strips_markdown_chars(self):
        out = clean_for_tts("**重要** `代码` [链接]")
        assert "*" not in out and "`" not in out

    def test_plain_text_untouched(self):
        assert clean_for_tts("今天天气不错") == "今天天气不错"
