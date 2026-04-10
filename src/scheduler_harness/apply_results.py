#!/usr/bin/env python3
"""
Parse Claude output and apply results to tasks.md.

Provides functions for parsing LLM output, updating task checkboxes,
and saving accumulated results. Also provides a CLI for standalone usage.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime


def extract_result_json(output_content: str) -> dict | None:
    """
    Extract the result JSON from Claude output.

    Looks for JSON in the format:
    {
      "completed": ["T001"],
      "failed": [],
      "blocked": [],
      "results": {...}
    }
    """
    # Try to find JSON in code block first
    code_block_pattern = re.compile(r'```(?:json)?\s*(\{[\s\S]*?"completed"[\s\S]*?"failed"[\s\S]*?"blocked"[\s\S]*?\})\s*```')
    match = code_block_pattern.search(output_content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find bare JSON object with required keys
    json_pattern = re.compile(r'\{[^{}]*"completed"[^{}]*"failed"[^{}]*"blocked"[^{}]*\}', re.DOTALL)
    match = json_pattern.search(output_content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def parse_output_file(output_file: Path) -> dict:
    """
    Parse Claude output file and extract results.

    Returns dict with completed, failed, blocked lists.
    """
    if not output_file.exists():
        raise FileNotFoundError(f"Output file not found: {output_file}")

    content = output_file.read_text(encoding='utf-8')

    # Try to parse as JSON first (Claude --output-format json)
    try:
        data = json.loads(content)
        # Claude JSON output has 'result' field with the text
        if 'result' in data:
            result = extract_result_json(data['result'])
            if result:
                return result
    except json.JSONDecodeError:
        pass

    # Try to extract from raw text
    result = extract_result_json(content)
    if result:
        return result

    raise ValueError("Could not extract result JSON from output file")


def update_tasks_file(task_source: Path, completed_ids: list[str], dry_run: bool = False) -> bool:
    """
    Update tasks.md by checking off completed tasks.

    Changes:
        - [ ] T001 ...  ->  - [x] T001 ...

    Returns True if any changes were made.
    """
    if not task_source.exists():
        raise FileNotFoundError(f"Task source not found: {task_source}")

    content = task_source.read_text(encoding='utf-8')
    lines = content.split('\n')
    changed = False

    for i, line in enumerate(lines):
        for task_id in completed_ids:
            # Match: - [ ] T001 ... (with any content after T001)
            pattern = re.compile(rf'^(-\s+)\[\s+\](\s+{re.escape(task_id)}\s+.*)$')
            match = pattern.match(line)
            if match:
                new_line = f"{match.group(1)}[x]{match.group(2)}"
                lines[i] = new_line
                print(f"Marking complete: {task_id}")
                changed = True
                break

    if changed and not dry_run:
        task_source.write_text('\n'.join(lines), encoding='utf-8')
        print(f"Updated {task_source}")

    return changed


def update_progress_status(base_dir: Path, results: dict) -> None:
    """
    Update status in progress/{TaskID}.txt files based on task results.

    completed → Status: resolved
    failed/blocked → Status: blocked
    """
    progress_dir = base_dir / 'progress'
    if not progress_dir.exists():
        return

    task_results = results.get('results', {})

    for task_id in results.get('completed', []):
        f = progress_dir / f"{task_id}.txt"
        if f.exists():
            content = f.read_text(encoding='utf-8')
            updated = re.sub(r'Status:\s*active', 'Status: resolved', content)
            if updated != content:
                f.write_text(updated, encoding='utf-8')
                print(f"Progress updated: {task_id} → resolved")

    for task_id in results.get('failed', []) + results.get('blocked', []):
        f = progress_dir / f"{task_id}.txt"
        if f.exists():
            content = f.read_text(encoding='utf-8')
            updated = re.sub(r'Status:\s*active', 'Status: blocked', content)
            if updated != content:
                f.write_text(updated, encoding='utf-8')
                print(f"Progress updated: {task_id} → blocked")


def save_task_results(results_file: Path, results: dict, dry_run: bool = False) -> bool:
    """
    Save/append task execution results to results.json.

    Structure:
    {
        "T001": {
            "status": "completed",
            "output": "Created file hello.txt",
            "files": ["hello.txt"],
            "data": {},
            "timestamp": "2024-01-01T12:00:00"
        },
        ...
    }
    """
    existing = {}

    # Load existing results
    if results_file.exists():
        try:
            existing = json.loads(results_file.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            existing = {}

    timestamp = datetime.now().isoformat()

    # Update with new results
    completed = results.get('completed', [])
    failed = results.get('failed', [])
    blocked = results.get('blocked', [])
    task_results = results.get('results', {})

    for task_id in completed:
        task_data = task_results.get(task_id, {})
        existing[task_id] = {
            "status": "completed",
            "output": task_data.get("output", ""),
            "files": task_data.get("files", []),
            "data": task_data.get("data", {}),
            "timestamp": timestamp
        }
        print(f"Saved result for {task_id}: {task_data.get('output', 'no output')}")

    for task_id in failed:
        task_data = task_results.get(task_id, {})
        existing[task_id] = {
            "status": "failed",
            "output": task_data.get("output", ""),
            "files": task_data.get("files", []),
            "data": task_data.get("data", {}),
            "timestamp": timestamp
        }

    for task_id in blocked:
        task_data = task_results.get(task_id, {})
        existing[task_id] = {
            "status": "blocked",
            "output": task_data.get("output", ""),
            "files": task_data.get("files", []),
            "data": task_data.get("data", {}),
            "timestamp": timestamp
        }

    if not dry_run:
        results_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"Results saved to {results_file}")

    return True


def main():
    parser = argparse.ArgumentParser(description='Parse Claude output and update tasks.md')
    parser.add_argument('--output-file', required=True, help='Path to Claude output JSON file')
    parser.add_argument('--task-source', required=True, help='Path to tasks.md')
    parser.add_argument('--results-file', help='Path to results.json for saving task outputs')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without modifying')

    args = parser.parse_args()

    output_file = Path(args.output_file)
    task_source = Path(args.task_source)
    results_file = Path(args.results_file) if args.results_file else None

    try:
        # Parse output file
        results = parse_output_file(output_file)
        print(f"Results: completed={results['completed']}, failed={results.get('failed', [])}, blocked={results.get('blocked', [])}")

        # Update tasks file
        completed = results.get('completed', [])
        if completed:
            update_tasks_file(task_source, completed, dry_run=args.dry_run)
        else:
            print("No completed tasks to update")

        # Save task results to results.json
        if results_file:
            save_task_results(results_file, results, dry_run=args.dry_run)

        # Report failed/blocked
        failed = results.get('failed', [])
        blocked = results.get('blocked', [])
        if failed:
            print(f"Failed tasks: {failed}")
        if blocked:
            print(f"Blocked tasks: {blocked}")

        sys.exit(0)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error parsing output: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
