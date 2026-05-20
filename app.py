import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request


HOST = "127.0.0.1"
PORT = int(os.getenv("APP_PORT", "8000"))
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. Answer clearly and practically."
)


def load_env_file() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file()


def provider_name() -> str:
    return os.getenv("AI_PROVIDER", "openai").strip().lower()


def active_model() -> str:
    if provider_name() == "ollama":
        return os.getenv("OLLAMA_MODEL", "llama3.2")
    return os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def build_messages(payload: dict) -> list[dict]:
    history = payload.get("messages", [])
    messages: list[dict] = []
    system_prompt = payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    messages.append({"role": "system", "content": system_prompt})

    for item in history:
        role = item.get("role", "").strip()
        content = item.get("content", "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    user_message = payload.get("message", "").strip()
    if user_message:
        messages.append({"role": "user", "content": user_message})

    return messages


def call_openai(messages: list[dict]) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    body = {
        "model": active_model(),
        "input": [
            {
                "role": message["role"],
                "content": [{"type": "input_text", "text": message["content"]}],
            }
            for message in messages
        ],
    }

    req = request.Request(
        url="https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI connection failed: {exc.reason}") from exc

    parts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text:
                parts.append(text)

    if not parts:
        raise RuntimeError("OpenAI response did not include text output.")

    return "\n".join(parts).strip()


def call_ollama(messages: list[dict]) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    body = {
        "model": active_model(),
        "messages": messages,
        "stream": False,
    }

    req = request.Request(
        url=f"{base_url}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama request failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Ollama connection failed: {exc.reason}") from exc

    message = data.get("message", {})
    content = message.get("content", "").strip()
    if not content:
        raise RuntimeError("Ollama response did not include message content.")

    return content


def ask_model(payload: dict) -> str:
    messages = build_messages(payload)
    if len(messages) < 2:
        raise RuntimeError("Please enter a message first.")

    if provider_name() == "ollama":
        return call_ollama(messages)
    return call_openai(messages)


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Local AI Assistant</title>
  <style>
    :root {
      --bg: #f4efe7;
      --panel: rgba(255, 252, 247, 0.88);
      --line: rgba(61, 48, 33, 0.14);
      --text: #2d241a;
      --muted: #6d5c49;
      --accent: #0f766e;
      --accent-2: #b45309;
      --user: #fff5d9;
      --assistant: #f6fbf8;
      --error: #fff1f2;
      --shadow: 0 20px 60px rgba(58, 42, 23, 0.12);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.14), transparent 32%),
        radial-gradient(circle at top right, rgba(180, 83, 9, 0.16), transparent 28%),
        linear-gradient(160deg, #f8f4ee 0%, #efe7da 100%);
      padding: 24px;
    }

    .shell {
      max-width: 980px;
      margin: 0 auto;
      background: var(--panel);
      backdrop-filter: blur(18px);
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .topbar {
      padding: 24px 28px 12px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.65), rgba(255,255,255,0.28));
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 40px);
      letter-spacing: -0.03em;
    }

    .subtitle {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
    }

    .status {
      margin-top: 14px;
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line);
      font-size: 14px;
      color: var(--muted);
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(15, 118, 110, 0.12);
    }

    .content {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 0;
    }

    .chat-area {
      min-height: 68vh;
      border-right: 1px solid var(--line);
      display: flex;
      flex-direction: column;
    }

    .messages {
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      overflow-y: auto;
      height: 100%;
    }

    .message {
      padding: 16px 18px;
      border-radius: 20px;
      border: 1px solid var(--line);
      line-height: 1.6;
      white-space: pre-wrap;
    }

    .message.user { background: var(--user); align-self: flex-end; max-width: 84%; }
    .message.assistant { background: var(--assistant); max-width: 90%; }
    .message.error { background: var(--error); border-color: rgba(190, 24, 93, 0.2); }

    .sidebar {
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .card {
      padding: 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line);
    }

    .card h2 {
      margin: 0 0 10px;
      font-size: 16px;
    }

    .card p, .card li {
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }

    .card ul {
      margin: 0;
      padding-left: 18px;
    }

    .composer {
      padding: 18px 24px 24px;
      border-top: 1px solid var(--line);
      background: rgba(255,255,255,0.44);
    }

    textarea, input, button {
      font: inherit;
    }

    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 16px;
      background: rgba(255,255,255,0.92);
      color: var(--text);
    }

    textarea {
      resize: vertical;
      min-height: 130px;
    }

    .field {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 14px;
    }

    label {
      font-size: 13px;
      color: var(--muted);
      font-weight: 600;
    }

    .actions {
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      margin-top: 4px;
    }

    button {
      border: none;
      border-radius: 999px;
      padding: 14px 20px;
      cursor: pointer;
      color: white;
      background: linear-gradient(135deg, var(--accent), #115e59);
      box-shadow: 0 10px 24px rgba(15, 118, 110, 0.22);
    }

    button.secondary {
      background: linear-gradient(135deg, var(--accent-2), #92400e);
      box-shadow: 0 10px 24px rgba(180, 83, 9, 0.18);
    }

    button:disabled {
      opacity: 0.6;
      cursor: wait;
    }

    .hint {
      color: var(--muted);
      font-size: 13px;
    }

    @media (max-width: 860px) {
      body { padding: 14px; }
      .content { grid-template-columns: 1fr; }
      .chat-area { border-right: none; border-bottom: 1px solid var(--line); min-height: 50vh; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <h1>Local AI Assistant</h1>
      <p class="subtitle">브라우저에서 대화하고, 백엔드는 내 PC에서 실행됩니다.</p>
      <div class="status">
        <span class="dot"></span>
        <span id="providerStatus">연결 준비 중...</span>
      </div>
    </div>

    <div class="content">
      <section class="chat-area">
        <div class="messages" id="messages"></div>
        <div class="composer">
          <div class="field">
            <label for="systemPrompt">시스템 프롬프트</label>
            <input id="systemPrompt" value="You are a helpful AI assistant. Answer clearly and practically." />
          </div>
          <div class="field">
            <label for="userMessage">메시지</label>
            <textarea id="userMessage" placeholder="예: 오늘 할 일을 정리해줘"></textarea>
          </div>
          <div class="actions">
            <div class="hint">Shift+Enter 줄바꿈, Enter 전송</div>
            <div>
              <button class="secondary" id="resetButton" type="button">대화 초기화</button>
              <button id="sendButton" type="button">보내기</button>
            </div>
          </div>
        </div>
      </section>

      <aside class="sidebar">
        <div class="card">
          <h2>현재 설정</h2>
          <p id="configText">불러오는 중...</p>
        </div>
        <div class="card">
          <h2>시작 방법</h2>
          <ul>
            <li>OpenAI 사용: <code>OPENAI_API_KEY</code> 설정</li>
            <li>Ollama 사용: <code>AI_PROVIDER=ollama</code> 설정</li>
            <li>브라우저에서 대화하며 로컬에서 앱 실행</li>
          </ul>
        </div>
        <div class="card">
          <h2>팁</h2>
          <p>Ollama를 쓰면 모델 실행도 내 PC에서 할 수 있습니다. OpenAI를 쓰면 앱만 로컬에서 실행되고 추론은 API로 처리됩니다.</p>
        </div>
      </aside>
    </div>
  </div>

  <script>
    const messagesEl = document.getElementById("messages");
    const userMessageEl = document.getElementById("userMessage");
    const systemPromptEl = document.getElementById("systemPrompt");
    const sendButtonEl = document.getElementById("sendButton");
    const resetButtonEl = document.getElementById("resetButton");
    const providerStatusEl = document.getElementById("providerStatus");
    const configTextEl = document.getElementById("configText");
    let history = [];

    function escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function renderMessages() {
      messagesEl.innerHTML = "";
      if (history.length === 0) {
        addMessage("assistant", "안녕하세요. 로컬 AI Assistant 준비가 끝났습니다. 첫 메시지를 보내보세요.");
        return;
      }
      for (const item of history) {
        addMessage(item.role, item.content);
      }
    }

    function addMessage(role, content) {
      const div = document.createElement("div");
      div.className = `message ${role}`;
      div.innerHTML = escapeHtml(content);
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    async function loadConfig() {
      const response = await fetch("/api/config");
      const data = await response.json();
      providerStatusEl.textContent = `${data.provider} / ${data.model}`;
      configTextEl.textContent = `provider=${data.provider}, model=${data.model}, port=${data.port}`;
    }

    async function sendMessage() {
      const message = userMessageEl.value.trim();
      if (!message) return;

      history.push({ role: "user", content: message });
      renderMessages();
      userMessageEl.value = "";
      sendButtonEl.disabled = true;

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message,
            messages: history.filter((item) => item.role !== "error"),
            system_prompt: systemPromptEl.value.trim()
          })
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "Unknown error");
        }

        history.push({ role: "assistant", content: data.reply });
        renderMessages();
      } catch (err) {
        history.push({ role: "error", content: `오류: ${err.message}` });
        renderMessages();
      } finally {
        sendButtonEl.disabled = false;
        userMessageEl.focus();
      }
    }

    sendButtonEl.addEventListener("click", sendMessage);
    resetButtonEl.addEventListener("click", () => {
      history = [];
      renderMessages();
      userMessageEl.focus();
    });
    userMessageEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    renderMessages();
    loadConfig().catch((err) => {
      providerStatusEl.textContent = "설정 확인 필요";
      configTextEl.textContent = err.message;
    });
  </script>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send_html(INDEX_HTML)
            return
        if self.path == "/api/config":
            self._send_json(
                {
                    "provider": provider_name(),
                    "model": active_model(),
                    "port": PORT,
                }
            )
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            payload = json.loads(raw_body.decode("utf-8"))
            reply = ask_model(payload)
            self._send_json({"reply": reply})
        except json.JSONDecodeError:
            self._send_json(
                {"error": "Invalid JSON payload."},
                status=HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                {"error": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Local AI Assistant running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
