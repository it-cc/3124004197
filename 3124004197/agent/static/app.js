/* TodoPal 前端交互逻辑：发消息、刷新任务、浏览器语音播报（Web Speech API） */

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const typingEl = document.getElementById("typing");
const taskListEl = document.getElementById("taskList");
const refreshBtn = document.getElementById("refreshBtn");
const clearBtn = document.getElementById("clearBtn");
const speakToggleBtn = document.getElementById("speakToggle");

let speakOn = false;

function addBubble(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.textContent = text;            // textContent 防止注入
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

function setBusy(busy) {
  sendBtn.disabled = busy;
  inputEl.disabled = busy;
  typingEl.classList.toggle("hidden", !busy);
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || sendBtn.disabled) return;
  addBubble("user", text);
  inputEl.value = "";
  setBusy(true);
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "请求失败");
    addBubble("bot", data.reply);
    if (speakOn) speak(data.reply);
  } catch (err) {
    addBubble("err", "⚠️ " + err.message + "（请确认 webapp.py 正在运行且已配置 API Key）");
  } finally {
    setBusy(false);
    inputEl.focus();
    refreshTasks();
  }
}

async function refreshTasks() {
  try {
    const resp = await fetch("/api/tasks");
    const data = await resp.json();
    taskListEl.textContent = data.text || "（暂无任务）";
  } catch (err) {
    taskListEl.textContent = "任务清单加载失败，请确认服务已启动。";
  }
}

/* ---------- 浏览器语音播报（Web Speech API，使用系统内置中文语音） ---------- */
function speak(text) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "zh-CN";
  utter.rate = 1.05;
  speechSynthesis.speak(utter);
}

speakToggleBtn.addEventListener("click", () => {
  speakOn = !speakOn;
  speakToggleBtn.textContent = speakOn ? "🔊 播报开" : "🔇 播报关";
  if (!speakOn && "speechSynthesis" in window) speechSynthesis.cancel();
});

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
refreshBtn.addEventListener("click", refreshTasks);
clearBtn.addEventListener("click", async () => {
  if (!confirm("确定清空对话记忆吗？任务数据不受影响。")) return;
  await fetch("/api/clear", { method: "POST" });
  messagesEl.innerHTML = "";
  addBubble("bot", "对话记忆已清空，我们重新开始吧 🙌");
  refreshTasks();
});

refreshTasks();
inputEl.focus();
