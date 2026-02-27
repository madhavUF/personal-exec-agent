"""
macOS Menubar App for the Personal AI Agent.

Manages the FastAPI web server and Telegram bot as child processes.
Shows live status in the menubar and lets you open the dashboard,
restart services, or quit — all from the menu bar icon.

Launched by launchd at login; do not run alongside start.sh.
"""

import os
import sys
import subprocess
import webbrowser

import rumps

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class AIAgentApp(rumps.App):

    def __init__(self):
        super().__init__("🤖", quit_button=None)

        self._server_proc = None
        self._bot_proc = None

        # Menu layout
        self.open_item    = rumps.MenuItem("Open Dashboard",    callback=self.open_dashboard)
        self.server_item  = rumps.MenuItem("Web Server: …")
        self.bot_item     = rumps.MenuItem("Telegram Bot: …")
        self.restart_item = rumps.MenuItem("Restart Services",  callback=self.restart_services)
        self.quit_item    = rumps.MenuItem("Quit",              callback=self.quit_app)

        self.menu = [
            self.open_item,
            None,
            self.server_item,
            self.bot_item,
            None,
            self.restart_item,
            None,
            self.quit_item,
        ]

        self._start_services()

        # Poll process health every 5 seconds
        self._timer = rumps.Timer(self._check_status, 5)
        self._timer.start()

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def _start_services(self):
        server_log = open(os.path.join(LOG_DIR, "server.log"), "a")
        bot_log    = open(os.path.join(LOG_DIR, "telegram.log"), "a")

        self._server_proc = subprocess.Popen(
            [PYTHON, "app.py"],
            cwd=PROJECT_DIR,
            stdout=server_log,
            stderr=server_log,
        )
        self._bot_proc = subprocess.Popen(
            [PYTHON, "-m", "src.telegram_bot"],
            cwd=PROJECT_DIR,
            stdout=bot_log,
            stderr=bot_log,
        )
        self._update_menu()

    def _stop_services(self):
        for proc in (self._server_proc, self._bot_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._server_proc = None
        self._bot_proc = None

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------

    def open_dashboard(self, _):
        webbrowser.open("http://localhost:8000")

    def restart_services(self, _):
        self.title = "🔄"
        self._stop_services()
        self._start_services()

    def quit_app(self, _):
        self._stop_services()
        rumps.quit_application()

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    def _proc_status(self, proc) -> tuple[str, bool]:
        """Return (label, is_running) for a process."""
        if proc is None:
            return "⛔ Stopped", False
        if proc.poll() is None:
            return "✅ Running", True
        return "❌ Crashed", False

    def _update_menu(self):
        server_label, server_ok = self._proc_status(self._server_proc)
        bot_label,    bot_ok    = self._proc_status(self._bot_proc)

        self.server_item.title = f"Web Server: {server_label}"
        self.bot_item.title    = f"Telegram Bot: {bot_label}"

        if server_ok and bot_ok:
            self.title = "🤖"
        elif server_ok or bot_ok:
            self.title = "🤖⚠️"
        else:
            self.title = "🤖❌"

    def _check_status(self, _):
        # Auto-restart crashed processes
        if self._server_proc and self._server_proc.poll() is not None:
            log = open(os.path.join(LOG_DIR, "server.log"), "a")
            self._server_proc = subprocess.Popen(
                [PYTHON, "app.py"],
                cwd=PROJECT_DIR, stdout=log, stderr=log,
            )

        if self._bot_proc and self._bot_proc.poll() is not None:
            log = open(os.path.join(LOG_DIR, "telegram.log"), "a")
            self._bot_proc = subprocess.Popen(
                [PYTHON, "-m", "src.telegram_bot"],
                cwd=PROJECT_DIR, stdout=log, stderr=log,
            )

        self._update_menu()


if __name__ == "__main__":
    AIAgentApp().run()
