#!/usr/bin/env python3
"""
Parse tasks.md and return uncompleted tasks.

Usage:
    python3 scripts/parse_tasks.py --task-source ./tasks.md
    python3 scripts/parse_tasks.py --task-source ./tasks.md --limit 2
    python3 scripts/parse_tasks.py --task-source ./tasks.md --phase "Phase 1: File Operations"
    python3 scripts/parse_tasks.py --task-source ./tasks.md --list-phases
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_tasks(content: str) -> list[dict]:
    """
    Parse markdown content and extract tasks with their phase info.

    Supports format:
        ## Phase 1: File Operations
        - [ ] T001 Task description
        - [x] T002 Completed task

    Returns list of dicts with keys: id, description, completed, raw_line, phase
    """
    tasks = []
    current_phase = None
    # Supports formats like 'T001', '1.1', 'B-12', etc.
    task_pattern = re.compile(r'^-\s+\[([ xX])\]\s+([A-Za-z0-9_.-]+)\s+(.+)$')
    phase_pattern = re.compile(r'^##\s+(.+)$')

    for line in content.split('\n'):
        stripped = line.strip()

        # Check for phase header (## Phase ...)
        phase_match = phase_pattern.match(stripped)
        if phase_match:
            current_phase = phase_match.group(1).strip()
            continue

        # Check for task line
        task_match = task_pattern.match(stripped)
        if task_match:
            checkbox = task_match.group(1).lower()
            task_id = task_match.group(2)
            description = task_match.group(3).strip()
            tasks.append({
                'id': task_id,
                'description': description,
                'completed': checkbox == 'x',
                'raw_line': line,
                'phase': current_phase
            })

    return tasks


def get_uncompleted_tasks(tasks: list[dict]) -> list[dict]:
    """Filter to return only uncompleted tasks."""
    return [t for t in tasks if not t['completed']]


def get_phases(tasks: list[dict]) -> list[str]:
    """Extract unique phases in order of appearance."""
    seen = set()
    phases = []
    for t in tasks:
        phase = t.get('phase')
        if phase and phase not in seen:
            seen.add(phase)
            phases.append(phase)
    return phases


def get_phase_summary(tasks: list[dict]) -> list[dict]:
    """Get summary of each phase: total tasks, completed, remaining."""
    phases = get_phases(tasks)
    summary = []
    for phase in phases:
        phase_tasks = [t for t in tasks if t.get('phase') == phase]
        completed = [t for t in phase_tasks if t['completed']]
        remaining = [t for t in phase_tasks if not t['completed']]
        summary.append({
            'phase': phase,
            'total': len(phase_tasks),
            'completed': len(completed),
            'remaining': len(remaining),
            'all_done': len(remaining) == 0,
            'task_ids': [t['id'] for t in phase_tasks]
        })
    return summary


def main():
    parser = argparse.ArgumentParser(description='Parse tasks.md and return uncompleted tasks')
    parser.add_argument('--task-source', required=True, help='Path to the tasks markdown file')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of tasks to return')
    parser.add_argument('--phase', type=str, default=None, help='Filter tasks by phase name')
    parser.add_argument('--list-phases', action='store_true', help='List all phases with summary')
    parser.add_argument('--current-phase', action='store_true', help='Show the first phase with remaining tasks')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    task_file = Path(args.task_source)
    if not task_file.exists():
        print(f"Error: Task file not found: {args.task_source}", file=sys.stderr)
        sys.exit(1)

    content = task_file.read_text(encoding='utf-8')
    all_tasks = parse_tasks(content)

    # List phases mode
    if args.list_phases:
        summary = get_phase_summary(all_tasks)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            for s in summary:
                status = "✓ DONE" if s['all_done'] else f"  {s['remaining']} remaining"
                print(f"[{status}] {s['phase']} ({s['completed']}/{s['total']})")
        return

    # Current phase mode - find first phase with remaining tasks
    if args.current_phase:
        summary = get_phase_summary(all_tasks)
        for s in summary:
            if not s['all_done']:
                if args.json:
                    print(json.dumps(s, ensure_ascii=False, indent=2))
                else:
                    print(s['phase'])
                return
        # All phases done
        if args.json:
            print(json.dumps(None))
        else:
            print("All phases completed")
        return

    # Normal mode - get uncompleted tasks
    uncompleted = get_uncompleted_tasks(all_tasks)

    # Filter by phase if specified
    if args.phase:
        uncompleted = [t for t in uncompleted if t.get('phase') == args.phase]

    if args.limit is not None and args.limit > 0:
        uncompleted = uncompleted[:args.limit]

    if args.json:
        output = [{'id': t['id'], 'description': t['description'], 'phase': t.get('phase')} for t in uncompleted]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for task in uncompleted:
            phase_prefix = f"[{task.get('phase', 'No Phase')}] " if task.get('phase') else ""
            print(f"{phase_prefix}{task['id']}: {task['description']}")


if __name__ == '__main__':
    main()
