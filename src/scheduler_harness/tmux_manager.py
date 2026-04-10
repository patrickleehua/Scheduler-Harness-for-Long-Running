#!/usr/bin/env python3
"""
tmux session manager for Scheduler Harness.

Manages tmux sessions, windows, and panes for distributed task execution.
Falls back gracefully when tmux is not available.
"""

import shutil
import subprocess
from pathlib import Path


class TmuxManager:
    """Manages a tmux session with multiple worker windows."""

    def __init__(self, session_name: str, work_dir: Path):
        self.session_name = session_name
        self.work_dir = work_dir
        self._windows: list[str] = []

    @staticmethod
    def is_available() -> bool:
        """Check if tmux is available on the system."""
        return shutil.which('tmux') is not None

    def _run_tmux(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """Execute a tmux command."""
        cmd = ['tmux'] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def create_session(self):
        """Create a new detached tmux session."""
        self._run_tmux([
            'new-session', '-d', '-s', self.session_name,
            '-c', str(self.work_dir)
        ])
        # Rename the default window to 'dashboard'
        self._run_tmux([
            'rename-window', '-t', f'{self.session_name}:0', 'dashboard'
        ])
        self._windows.append('dashboard')
        print(f"  tmux session '{self.session_name}' created")
        print(f"  Attach with: tmux attach -t {self.session_name}")

    def create_window(self, name: str):
        """Create a new window in the session."""
        self._run_tmux([
            'new-window', '-t', self.session_name,
            '-n', name, '-c', str(self.work_dir)
        ])
        self._windows.append(name)

    def send_keys(self, window: str, cmd: str):
        """Send keys to a specific window."""
        target = f'{self.session_name}:{window}'
        self._run_tmux(['send-keys', '-t', target, cmd, 'Enter'])

    def send_lines(self, window: str, lines: list[str]):
        """Send multiple lines to a specific window."""
        target = f'{self.session_name}:{window}'
        for line in lines:
            self._run_tmux(['send-keys', '-t', target, line, 'Enter'])

    def capture_pane(self, window: str) -> str:
        """Capture the current content of a pane."""
        target = f'{self.session_name}:{window}'
        result = self._run_tmux(['capture-pane', '-t', target, '-p'], check=False)
        return result.stdout

    def clear_pane(self, window: str):
        """Clear the pane content."""
        self.send_keys(window, 'clear')

    def kill_window(self, window: str):
        """Kill a specific window."""
        target = f'{self.session_name}:{window}'
        self._run_tmux(['kill-window', '-t', target], check=False)
        if window in self._windows:
            self._windows.remove(window)

    def kill_session(self):
        """Kill the entire session."""
        self._run_tmux(['kill-session', '-t', self.session_name], check=False)
        self._windows.clear()

    def select_window(self, window: str):
        """Switch to a specific window (makes it active)."""
        target = f'{self.session_name}:{window}'
        self._run_tmux(['select-window', '-t', target])

    @property
    def is_alive(self) -> bool:
        """Check if the session is still running."""
        result = self._run_tmux(['has-session', '-t', self.session_name], check=False)
        return result.returncode == 0

    def list_windows(self) -> list[str]:
        """List all window names in the session."""
        result = self._run_tmux([
            'list-windows', '-t', self.session_name, '-F', '#{window_name}'
        ], check=False)
        if result.returncode == 0:
            return result.stdout.strip().split('\n')
        return []
