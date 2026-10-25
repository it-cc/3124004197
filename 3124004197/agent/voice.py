"""语音输入 / 输出模块（加分项，可选功能）。

- 语音输出：pyttsx3 调用操作系统本地 TTS 引擎离线合成（Windows 用 SAPI5，
  Linux 用 espeak-ng），不联网、不需要 API Key。
- 语音输入：vosk 离线中文识别（首次使用自动下载约 40MB 小模型）+
  sounddevice 采集麦克风。

所有依赖都是懒加载：没装依赖时相关功能自动禁用并给出安装提示，
纯文字交互完全不受影响。
"""

import json
import os
import queue
import re
import threading
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# vosk 中文小模型（约 40MB，识别快、离线可用）
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
VOSK_MODEL_DIR = os.environ.get(
    "VOSK_MODEL",
    os.path.join(BASE_DIR, "models", "vosk-model-small-cn-0.22"),
)

# 依赖探测：缺什么不影响其他功能
try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import sounddevice as _sd
    import vosk as _vosk
except ImportError:
    _sd = None
    _vosk = None


def clean_for_tts(text: str) -> str:
    """把界面文本清洗成适合朗读的内容：去掉 emoji、Markdown 符号等。"""
    text = re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\u2B00-\u2BFF\uFE0F]",
        "", text)
    text = re.sub(r"[#*`>_~|\[\]()（）：:；;]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class Speaker:
    """语音播报器：后台线程朗读，不阻塞对话。"""

    def __init__(self):
        self.enabled = False
        self.reason = ""
        self._engine = None
        self._lock = threading.Lock()

    def _ensure_engine(self) -> bool:
        if self._engine is not None:
            return True
        if pyttsx3 is None:
            self.reason = "未安装 pyttsx3，请执行：pip install pyttsx3（Linux 还需安装 espeak-ng）"
            return False
        try:
            engine = pyttsx3.init()
            # 优先选中文语音
            for voice in engine.getProperty("voices"):
                if any(k in getattr(voice, "name", "") for k in ("Huihui", "Yaoyao", "Ting", "Chinese", "中文")):
                    engine.setProperty("voice", voice.id)
                    break
            engine.setProperty("rate", 180)
            self._engine = engine
            return True
        except Exception as exc:
            self.reason = f"语音引擎初始化失败：{exc}"
            return False

    def toggle(self) -> str:
        """切换开关，返回状态说明文本。"""
        if self.enabled:
            self.enabled = False
            return "🔇 语音播报已关闭。"
        if not self._ensure_engine():
            return f"⚠️ 无法开启语音播报：{self.reason}"
        self.enabled = True
        return "🔊 语音播报已开启，之后每条回复我都会念出来。"

    def say(self, text: str) -> None:
        """在后台线程朗读；正在朗读时跳过新请求，避免叠音。"""
        if not self.enabled or not self._lock.acquire(blocking=False):
            return
        def _run():
            try:
                self._engine.say(clean_for_tts(text))
                self._engine.runAndWait()
            except Exception:
                pass  # 播报失败不影响文字交互
            finally:
                self._lock.release()
        threading.Thread(target=_run, daemon=True).start()


class Listener:
    """语音输入：麦克风录音 → vosk 离线识别成文字。"""

    def __init__(self):
        self._model = None
        self._tried = False

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        if _sd is None or _vosk is None:
            print("⚠️ 未安装语音识别依赖，请执行：pip install vosk sounddevice")
            return False
        if not os.path.isdir(VOSK_MODEL_DIR):
            ok = self._download_model()
            if not ok:
                return False
        _vosk.SetLogLevel(-1)
        self._model = _vosk.Model(VOSK_MODEL_DIR)
        return True

    def _download_model(self) -> bool:
        """首次使用时自动下载并解压中文小模型。"""
        os.makedirs(os.path.dirname(VOSK_MODEL_DIR), exist_ok=True)
        zip_path = VOSK_MODEL_DIR + ".zip"
        print(f"⬇️ 首次使用语音输入，正在下载离线识别模型（约 40MB）…")
        try:
            def _progress(blocks, block_size, total):
                done = min(blocks * block_size, total)
                if total > 0:
                    print(f"\r   下载进度 {done / total * 100:.0f}%", end="")
            urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path, _progress)
            print("\n📦 解压中…")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(os.path.dirname(VOSK_MODEL_DIR))
            os.remove(zip_path)
            return True
        except Exception as exc:
            print(f"\n⚠️ 模型下载失败：{exc}\n"
                  f"   可手动下载 {VOSK_MODEL_URL}\n"
                  f"   解压到 {VOSK_MODEL_DIR} 后重试。")
            return False

    def record_until_enter(self) -> str | None:
        """开始录音，直到用户按回车；返回识别出的文字（失败返回 None）。"""
        if not self._ensure_model():
            return None
        audio_q: queue.Queue = queue.Queue()
        stop = threading.Event()

        def callback(indata, frames, time_info, status):
            if not stop.is_set():
                audio_q.put(bytes(indata))

        import sounddevice as sd
        import vosk

        recognizer = vosk.KaldiRecognizer(self._model, 16000)
        print("🔴 录音中… 说完按回车结束")
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=4000, callback=callback):
            input()  # 用户说完按回车
            stop.set()
            while not audio_q.empty():          # 吃掉已缓冲音频
                recognizer.AcceptWaveform(audio_q.get())
            result = json.loads(recognizer.FinalResult())
        text = (result.get("text") or "").strip()
        if not text:
            print("🤔 没听清，请靠近麦克风再试一次，或改用键盘输入。")
            return None
        return text
