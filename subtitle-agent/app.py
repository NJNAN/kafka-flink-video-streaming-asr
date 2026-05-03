from __future__ import annotations

import threading
from pathlib import Path

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static
except ModuleNotFoundError as exc:
    raise SystemExit("缺少 Textual，请先执行：pip install -r requirements.txt") from exc

from agent.executor import run_agent
from config import load_config


class InputScreen(ModalScreen[str]):
    CSS = """
    InputScreen {
        align: center middle;
        background: #030712 60%;
    }
    #dialog {
        width: 86;
        height: 11;
        border: round #38bdf8;
        background: #0f172a;
        padding: 1 2;
    }
    #dialog-title {
        color: #f8fafc;
        text-style: bold;
        margin-bottom: 1;
    }
    #dialog-actions {
        height: 3;
        align-horizontal: right;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, value: str = "") -> None:
        super().__init__()
        self.title = title
        self.value = value

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(self.title, id="dialog-title")
            yield Input(value=self.value, id="dialog-input")
            with Horizontal(id="dialog-actions"):
                yield Button("Confirm", variant="primary", id="ok")
                yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#dialog-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss("")
            return
        self.dismiss(self.query_one("#dialog-input", Input).value.strip())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())


class SubtitleAgentApp(App):
    TITLE = "Subtitle Agent"
    SUB_TITLE = "AI subtitle studio"
    BINDINGS = [
        ("g", "go", "run"),
        ("v", "set_video", "video"),
        ("p", "set_profile", "profile"),
        ("l", "clear_log", "clear"),
        ("q", "quit", "quit"),
    ]

    CSS = """
    Screen {
        background: #070b12;
        color: #dbeafe;
    }
    Header {
        height: 1;
        background: #070b12;
        color: #dbeafe;
    }
    Footer {
        height: 1;
        background: #070b12;
        color: #93c5fd;
    }
    #shell {
        height: 1fr;
        padding: 1 2 0 2;
    }
    #hero {
        height: 5;
        border: round #1e293b;
        background: #0f172a;
        padding: 1 2;
    }
    #title {
        height: 1;
        color: #f8fafc;
        text-style: bold;
    }
    #subtitle {
        height: 1;
        color: #93c5fd;
    }
    #statusline {
        height: 1;
        color: #a7f3d0;
    }
    #body {
        height: 1fr;
        margin-top: 1;
    }
    #sidebar {
        width: 34;
        border: round #1e293b;
        background: #0b1220;
        padding: 1;
        margin-right: 1;
    }
    #main {
        width: 1fr;
    }
    #logbox {
        height: 1fr;
        border: round #1e293b;
        background: #090e18;
        padding: 1;
    }
    #log {
        height: 1fr;
        border: none;
        background: #090e18;
    }
    #command-panel {
        height: 5;
        border: round #1e293b;
        background: #0f172a;
        padding: 1;
        margin-top: 1;
    }
    #command {
        height: 1;
        background: #020617;
        color: #f8fafc;
        border: none;
        padding: 0 1;
    }
    #hint {
        height: 1;
        color: #64748b;
        margin-top: 1;
    }
    .side-title {
        color: #f8fafc;
        text-style: bold;
        margin-bottom: 1;
    }
    .side-muted {
        color: #64748b;
    }
    .side-ok {
        color: #34d399;
    }
    .side-warn {
        color: #fbbf24;
    }
    .step-active {
        color: #facc15;
        text-style: bold;
    }
    .step-idle {
        color: #475569;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.video_path = ""
        self.profile = self.config.default_profile
        self.goal = "生成高质量字幕，检查专业词、漏字幕、错词和时间轴问题。"
        self.running = False
        self.latest_result: dict | None = None
        self.motion_index = 0
        self.current_step = "idle"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="shell"):
            with Vertical(id="hero"):
                yield Static("", id="title")
                yield Static("Context aware AI editing / RAG / rhythm tuning / styled ASS variants", id="subtitle")
                yield Static("", id="statusline")
            with Horizontal(id="body"):
                with Vertical(id="sidebar"):
                    yield Static("SESSION", classes="side-title")
                    yield Static("", id="session")
                    yield Static("PIPELINE", classes="side-title")
                    yield Static("", id="steps")
                    yield Static("OUTPUT", classes="side-title")
                    yield Static("", id="output")
                with Vertical(id="main"):
                    with Container(id="logbox"):
                        yield RichLog(id="log", wrap=True, highlight=True, markup=True)
                    with Vertical(id="command-panel"):
                        yield Input(placeholder="Paste video path or type :run / :profile bigdata / :goal ...", id="command")
                        yield Static("g run   v video   p profile   l clear   q quit", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.28, self.animate)
        self.refresh_side()
        self.write_intro()
        self.query_one("#command", Input).focus()

    def write_intro(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[bold #f8fafc]StreamSense Subtitle Agent[/bold #f8fafc]")
        log.write("[#94a3b8]This run uses DeepSeek for context brief, dynamic revision, consistency and semantic polish.[/#94a3b8]")
        log.write("[#94a3b8]Paste a video path, then type :run. Outputs include revised.ass and revised.creator.ass.[/#94a3b8]")

    def animate(self) -> None:
        frames = ["●", "●", "●", "◆", "◆", "◆"]
        frame = frames[self.motion_index % len(frames)] if self.running else "●"
        self.motion_index += 1
        state = "running" if self.running else "ready"
        color = "#22c55e" if not self.running else "#38bdf8"
        self.query_one("#title", Static).update(
            f"[{color}]{frame}[/] [bold #f8fafc]Subtitle Agent[/bold #f8fafc]  "
            f"[#64748b]{state}[/#64748b]"
        )
        self.query_one("#statusline", Static).update(
            f"model={self.config.llm_model}  profile={self.profile}  "
            f"batch={self.config.ai_batch_size}  key={'ok' if self.config.llm_api_key else 'missing'}"
        )

    @staticmethod
    def short(value: str, limit: int = 38) -> str:
        if not value:
            return "none"
        if len(value) <= limit:
            return value
        return value[:16] + "..." + value[-18:]

    def refresh_side(self) -> None:
        self.query_one("#session", Static).update(
            f"[#64748b]video[/#64748b]\n{self.short(self.video_path)}\n\n"
            f"[#64748b]goal[/#64748b]\n{self.short(self.goal, 48)}\n"
        )
        step_names = [
            ("plan", "Plan"),
            ("subtitle", "Subtitle"),
            ("rag", "RAG"),
            ("context", "Context"),
            ("glossary", "Glossary"),
            ("review", "AI revise"),
            ("consistency", "Consistency"),
            ("semantic", "Semantic"),
            ("rhythm", "Rhythm"),
            ("report", "Export"),
        ]
        lines = []
        for key, label in step_names:
            if key == self.current_step:
                lines.append(f"[#facc15]● {label}[/#facc15]")
            else:
                lines.append(f"[#475569]○ {label}[/#475569]")
        self.query_one("#steps", Static).update("\n".join(lines))
        if self.latest_result:
            self.query_one("#output", Static).update(
                f"[#34d399]done[/#34d399]\n{self.latest_result['task_id']}\n\n"
                f"[#64748b]ASS[/#64748b]\n{self.short(self.latest_result.get('revised_ass', ''))}"
            )
        else:
            self.query_one("#output", Static).update("[#64748b]No run yet[/#64748b]")

    def write_log(self, message: str, style: str = "#dbeafe") -> None:
        self.query_one("#log", RichLog).write(f"[{style}]{message}[/]")

    def action_set_video(self) -> None:
        self.push_screen(InputScreen("Video path", self.video_path), self._set_video_done)

    def _set_video_done(self, value: str) -> None:
        if value:
            self.video_path = value
            self.write_log(f"video = {value}", "#93c5fd")
            self.refresh_side()

    def action_set_profile(self) -> None:
        self.push_screen(InputScreen("Profile: bigdata / course / meeting / dino", self.profile), self._set_profile_done)

    def _set_profile_done(self, value: str) -> None:
        if value:
            self.profile = value
            self.write_log(f"profile = {value}", "#93c5fd")
            self.refresh_side()

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
        self.write_intro()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if value.startswith(":"):
            self.handle_command(value)
            return
        self.video_path = value
        self.write_log(f"video = {value}", "#93c5fd")
        self.refresh_side()

    def handle_command(self, value: str) -> None:
        command, _, rest = value[1:].partition(" ")
        command = command.strip().lower()
        rest = rest.strip()
        if command in {"run", "go", "g"}:
            self.action_go()
        elif command in {"profile", "p"}:
            if rest:
                self.profile = rest
                self.write_log(f"profile = {rest}", "#93c5fd")
                self.refresh_side()
            else:
                self.action_set_profile()
        elif command == "goal":
            if rest:
                self.goal = rest
                self.write_log(f"goal = {rest}", "#93c5fd")
                self.refresh_side()
        elif command in {"video", "v"}:
            if rest:
                self.video_path = rest
                self.write_log(f"video = {rest}", "#93c5fd")
                self.refresh_side()
            else:
                self.action_set_video()
        elif command in {"clear", "l"}:
            self.action_clear_log()
        else:
            self.write_log(f"unknown command: {value}", "#f59e0b")

    def action_go(self) -> None:
        if self.running:
            self.write_log("Agent is already running.", "#f59e0b")
            return
        if not self.video_path:
            self.write_log("Set a video path first.", "#f43f5e")
            return
        self.running = True
        self.current_step = "plan"
        self.refresh_side()
        self.write_log("Starting AI subtitle pipeline...", "#22c55e")
        thread = threading.Thread(target=self._run_agent_thread, daemon=True)
        thread.start()

    def _run_agent_thread(self) -> None:
        def receive(message: str) -> None:
            lower = message.lower()
            if "step 2" in lower:
                self.current_step = "subtitle"
            elif "step 4" in lower or "rag" in lower:
                self.current_step = "rag"
            elif "step 5" in lower or "上下文" in message:
                self.current_step = "context"
            elif "step 6" in lower or "术语" in message:
                self.current_step = "glossary"
            elif "step 7" in lower or "审校批次" in message or "修正" in message:
                self.current_step = "review"
            elif "step 8" in lower or "一致性" in message:
                self.current_step = "consistency"
            elif "step 9" in lower or "语义" in message:
                self.current_step = "semantic"
            elif "step 10" in lower or "节奏" in message:
                self.current_step = "rhythm"
            elif "step 11" in lower or "step 12" in lower or "报告" in message or "完成" in message:
                self.current_step = "report"
            self.call_from_thread(self.refresh_side)
            self.call_from_thread(self.write_log, message, "#dbeafe")

        try:
            result = run_agent(
                config=self.config,
                video_path=Path(self.video_path),
                profile=self.profile,
                goal=self.goal,
                log=receive,
            )
            self.latest_result = result
            self.call_from_thread(self.write_log, "Done.", "#22c55e")
            self.call_from_thread(self.write_log, f"report: {result['report']}", "#93c5fd")
            self.call_from_thread(self.write_log, f"ass: {result.get('revised_ass', '')}", "#93c5fd")
            self.call_from_thread(self.write_log, f"creator: {result.get('creator_ass', '')}", "#93c5fd")
        except Exception as exc:
            self.call_from_thread(self.write_log, f"Agent failed: {exc}", "#f43f5e")
        finally:
            self.running = False
            self.current_step = "idle"
            self.call_from_thread(self.refresh_side)


if __name__ == "__main__":
    SubtitleAgentApp().run()
