#!/usr/bin/env python3
"""
Worker process for tmux-based task execution.

Runs inside a tmux window, communicates with the orchestrator
through file-based signals in .signals/<phase>/.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import apply_results


def _read_status(signal_dir: Path) -> dict:
    """Read current status from signal directory."""
    status_file = signal_dir / 'status.json'
    if status_file.exists():
        try:
            return json.loads(status_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {'status': 'waiting'}


def _write_status(signal_dir: Path, status: dict):
    """Write status to signal directory."""
    status_file = signal_dir / 'status.json'
    status_file.write_text(json.dumps(status, indent=2), encoding='utf-8')


def _read_control(signal_dir: Path) -> str | None:
    """Read and consume control command from signal directory."""
    control_file = signal_dir / 'control'
    if control_file.exists():
        try:
            cmd = control_file.read_text(encoding='utf-8').strip().lower()
            if cmd in ('pause', 'resume', 'skip', 'abort'):
                # Don't consume resume — orchestrator may re-send it
                if cmd != 'resume':
                    control_file.unlink()
                return cmd
        except OSError:
            pass
    return None


def _wait_for_prompt(signal_dir: Path) -> str | None:
    """Wait for prompt.txt to appear, return its content."""
    prompt_file = signal_dir / 'prompt.txt'
    if prompt_file.exists():
        try:
            content = prompt_file.read_text(encoding='utf-8')
            prompt_file.unlink()  # consume
            return content
        except OSError:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description='Scheduler Harness Worker')
    parser.add_argument('--signal-dir', required=True,
                        help='Path to signal directory (e.g. .signals/phase-1/)')
    parser.add_argument('--task-source', required=True,
                        help='Path to tasks.md file')
    parser.add_argument('--phase', required=True,
                        help='Phase name this worker handles')
    args = parser.parse_args()

    signal_dir = Path(args.signal_dir)
    task_source = Path(args.task_source)
    results_file = signal_dir / 'results.json'

    print(f"Worker started for phase: {args.phase}")
    print(f"Signal dir: {signal_dir}")
    print(f"Waiting for prompts...")

    round_num = 0

    while True:
        # 1. Check control commands
        control = _read_control(signal_dir)
        if control == 'abort':
            print("Received abort command, shutting down.")
            _write_status(signal_dir, {'status': 'aborted', 'round': round_num})
            break
        if control == 'pause':
            _write_status(signal_dir, {'status': 'paused', 'round': round_num})
            print("Paused. Waiting for resume...")
            while True:
                time.sleep(1)
                cmd = _read_control(signal_dir)
                if cmd == 'resume':
                    print("Resumed.")
                    _write_status(signal_dir, {'status': 'waiting', 'round': round_num})
                    break
                if cmd == 'abort':
                    print("Aborted while paused.")
                    _write_status(signal_dir, {'status': 'aborted', 'round': round_num})
                    sys.exit(0)

        # 2. Wait for prompt
        prompt = _wait_for_prompt(signal_dir)
        if prompt is None:
            time.sleep(1)
            continue

        round_num += 1
        print(f"\n{'─' * 40}")
        print(f"Round {round_num}: executing Claude...")
        print(f"{'─' * 40}")

        # 3. Write status: running
        _write_status(signal_dir, {'status': 'running', 'round': round_num})

        # 4. Execute Claude
        try:
            result = subprocess.run(
                'claude --print --dangerously-skip-permissions',
                input=prompt,
                capture_output=True,
                text=True,
                shell=True,
                encoding='utf-8',
                errors='replace'
            )
            output = result.stdout

            # Strip code fences
            import re
            output = re.sub(r'^```\w*\n?', '', output)
            output = re.sub(r'\n?```\s*$', '', output)
            output = output.strip()

        except FileNotFoundError:
            print("Claude CLI not found!")
            _write_status(signal_dir, {'status': 'error', 'round': round_num,
                                        'error': 'Claude CLI not found'})
            continue
        except Exception as e:
            print(f"Execution error: {e}")
            _write_status(signal_dir, {'status': 'error', 'round': round_num,
                                        'error': str(e)})
            continue

        # 5. Save raw output
        output_file = signal_dir / 'output.json'
        output_file.write_text(output, encoding='utf-8')

        # 6. Parse and apply results
        try:
            parsed = apply_results.parse_output_file(output_file)
            # Save to phase-local results
            apply_results.save_task_results(results_file, parsed)
            # Update task checkboxes in source file
            completed = parsed.get('completed', [])
            if completed:
                apply_results.update_tasks_file(task_source, completed)
            # Update progress files
            apply_results.update_progress_status(signal_dir.parent.parent, parsed)

            has_blocked = bool(parsed.get('blocked', []))
            _write_status(signal_dir, {
                'status': 'blocked' if has_blocked else 'done',
                'round': round_num,
                'completed': completed,
                'blocked': parsed.get('blocked', []),
                'failed': parsed.get('failed', [])
            })

            print(f"Round {round_num} complete: {len(completed)} done, "
                  f"{len(parsed.get('blocked', []))} blocked")

        except Exception as e:
            print(f"Failed to parse output: {e}")
            _write_status(signal_dir, {
                'status': 'error',
                'round': round_num,
                'error': str(e)
            })

        # Back to waiting for next prompt
        _write_status(signal_dir, {
            'status': 'waiting',
            'round': round_num
        })


if __name__ == '__main__':
    main()
