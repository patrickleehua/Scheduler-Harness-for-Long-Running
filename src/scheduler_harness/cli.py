#!/usr/bin/env python3
"""
Scheduler Harness - Main Runner

Executes tasks phase by phase. Each phase completes fully before moving to the next.
Previous phase results are passed as context to subsequent phases.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import parse_tasks
from . import build_prompt
from . import apply_results


def do_reset(base_dir: Path, task_source: Path = None):
    """
    Clean up all runtime-generated files, restoring the project to a fresh state.
    """
    print("=" * 60)
    print("  [RESET] Cleaning generated files...")
    print("=" * 60)

    removed = []
    skipped = []

    files_to_remove = [
        base_dir / 'state.json',
        base_dir / 'results.json',
        base_dir / '.tasks_cache.json',
        base_dir / '.results_context.json',
    ]

    for f in files_to_remove:
        if f.exists():
            f.unlink()
            removed.append(str(f.relative_to(base_dir)))
        else:
            skipped.append(str(f.relative_to(base_dir)))

    runs_dir = base_dir / 'runs'
    if runs_dir.exists():
        file_count = sum(1 for _ in runs_dir.iterdir())
        shutil.rmtree(runs_dir)
        removed.append(f"runs/  ({file_count} file(s))")
    else:
        skipped.append("runs/")

    if task_source and task_source.exists():
        content = task_source.read_text(encoding='utf-8')
        updated = re.sub(r'^(\s*- )\[x\]', r'\1[ ]', content, flags=re.MULTILINE | re.IGNORECASE)
        if updated != content:
            task_source.write_text(updated, encoding='utf-8')
            removed.append(f"Reset checkboxes in {task_source.name}")
        else:
            skipped.append(f"No checked boxes in {task_source.name}")

    print()
    if removed:
        print("  [v] Removed / reset:")
        for item in removed:
            print(f"    - {item}")
    if skipped:
        print("  [>] Already clean (skipped):")
        for item in skipped:
            print(f"    - {item}")

    print()
    print("  [OK] Reset complete. Project is ready for a fresh run.")
    print("=" * 60)


def do_archive(base_dir: Path, task_source: Path = None):
    """
    Archive all runtime-generated files into a timestamped directory.

    The archive includes:
      - state.json
      - results.json
      - runs/  (all round-*.json files)
      - .tasks_cache.json
      - .results_context.json
      - The task source file (if provided)

    Archive naming: <task_filename>_<yyyy-mm-dd_HH-MM-SS>/
    Archives are stored in an 'archives/' directory under base_dir.
    """
    print("=" * 60)
    print("  [ARCHIVE] Creating archive...")
    print("=" * 60)

    archives_dir = base_dir / 'archives'
    archives_dir.mkdir(parents=True, exist_ok=True)

    # Build archive name
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if task_source and task_source.exists():
        task_name = task_source.stem  # filename without extension
    else:
        task_name = "scheduler"
    archive_name = f"{task_name}_{timestamp}"
    archive_path = archives_dir / archive_name
    archive_path.mkdir(parents=True, exist_ok=True)

    # Collect files to archive
    files_to_archive = [
        base_dir / 'state.json',
        base_dir / 'results.json',
        base_dir / '.tasks_cache.json',
        base_dir / '.results_context.json',
    ]

    archived_items = []
    skipped_items = []

    # Copy individual files
    for f in files_to_archive:
        if f.exists():
            dest = archive_path / f.name
            shutil.copy2(f, dest)
            archived_items.append(f.name)
        else:
            skipped_items.append(f.name)

    # Copy runs/ directory
    runs_dir = base_dir / 'runs'
    if runs_dir.exists():
        run_files = [rf for rf in runs_dir.iterdir() if rf.is_file()]
        if run_files:
            dest_runs = archive_path / 'runs'
            dest_runs.mkdir(exist_ok=True)
            for rf in run_files:
                shutil.copy2(rf, dest_runs / rf.name)
                archived_items.append(f"runs/{rf.name}")
        else:
            skipped_items.append("runs/ (empty)")
    else:
        skipped_items.append("runs/")

    # Copy task source file
    if task_source and task_source.exists():
        shutil.copy2(task_source, archive_path / task_source.name)
        archived_items.append(task_source.name)

    # Save metadata
    meta = {
        'task_source_original_path': str(task_source) if task_source else None,
        'task_source_name': task_source.name if task_source else None,
        'archived_at': timestamp,
        'base_dir': str(base_dir),
    }
    meta_file = archive_path / '_archive_meta.json'
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')

    # Calculate total size
    total_size = sum(f.stat().st_size for f in archive_path.rglob('*') if f.is_file())

    print()
    if archived_items:
        print("  [v] Archived files:")
        for item in archived_items:
            print(f"    - {item}")
    if skipped_items:
        print("  [>] Not found (skipped):")
        for item in skipped_items:
            print(f"    - {item}")

    print()
    print(f"  [OK] Archive created: {archive_path}")
    print(f"       Total size: {total_size / 1024:.1f} KB")

    # Clean up original runtime files after successful archive
    cleaned = []
    for f in files_to_archive:
        if f.exists():
            f.unlink()
            cleaned.append(f.name)
    runs_dir = base_dir / 'runs'
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
        cleaned.append("runs/")
    if cleaned:
        print()
        print("  [v] Cleaned up original files:")
        for item in cleaned:
            print(f"    - {item}")

    print("=" * 60)
    return archive_path


def do_restore(base_dir: Path, archive_path: Path):
    """
    Restore runtime files from a previously created archive directory.

    This will:
      - Copy state.json, results.json, runs/, etc. back to base_dir
      - Restore the task source file to its original location
      - Overwrite any existing files
    """
    if not archive_path.exists():
        # Try looking in archives/ directory
        candidate = base_dir / 'archives' / archive_path.name
        if candidate.exists():
            archive_path = candidate
        else:
            print(f"Error: Archive not found: {archive_path}")
            sys.exit(1)

    if not archive_path.is_dir():
        print(f"Error: Archive is not a directory: {archive_path}")
        sys.exit(1)

    print("=" * 60)
    print(f"  [RESTORE] Restoring from archive...")
    print(f"  Archive: {archive_path.name}")
    print("=" * 60)

    # Read metadata
    meta = {}
    meta_file = archive_path / '_archive_meta.json'
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding='utf-8'))

    restored_items = []
    task_source_name = meta.get('task_source_name')

    # Files that go directly to base_dir
    runtime_files = ['state.json', 'results.json', '.tasks_cache.json', '.results_context.json']

    for fname in runtime_files:
        src = archive_path / fname
        if src.exists():
            shutil.copy2(src, base_dir / fname)
            restored_items.append(fname)

    # Restore runs/ directory
    src_runs = archive_path / 'runs'
    if src_runs.exists() and src_runs.is_dir():
        dest_runs = base_dir / 'runs'
        dest_runs.mkdir(exist_ok=True)
        for rf in src_runs.iterdir():
            if rf.is_file():
                shutil.copy2(rf, dest_runs / rf.name)
                restored_items.append(f"runs/{rf.name}")

    # Restore task source file
    if task_source_name:
        src_task = archive_path / task_source_name
        if src_task.exists():
            original_path = meta.get('task_source_original_path')
            if original_path:
                target = Path(original_path)
            else:
                target = base_dir / task_source_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_task, target)
            restored_items.append(f"{task_source_name} → {target}")

    print()
    if restored_items:
        print("  [v] Restored files:")
        for item in restored_items:
            print(f"    - {item}")

    print()
    print(f"  [OK] Restore complete. State recovered from: {archive_path.name}")
    if meta.get('archived_at'):
        print(f"       Archive timestamp: {meta['archived_at']}")
    print("=" * 60)


def do_list_archives(base_dir: Path):
    """
    List all available archive directories in the archives/ directory.
    """
    archives_dir = base_dir / 'archives'

    print("=" * 60)
    print("  [ARCHIVES] Available archives")
    print("=" * 60)

    if not archives_dir.exists():
        print("\n  No archives found.")
        print(f"  (Archives directory: {archives_dir})")
        print("\n  Create one with: scheduler-harness --archive --task-source tasks.md")
        print("=" * 60)
        return

    # Find archive directories (those containing _archive_meta.json)
    archives = []
    for d in sorted(archives_dir.iterdir(), reverse=True):
        if d.is_dir() and (d / '_archive_meta.json').exists():
            archives.append(d)

    if not archives:
        print("\n  No archives found.")
        print(f"  (Archives directory: {archives_dir})")
        print("\n  Create one with: scheduler-harness --archive --task-source tasks.md")
        print("=" * 60)
        return

    print()
    for i, arc in enumerate(archives, 1):
        # Read metadata
        try:
            meta = json.loads((arc / '_archive_meta.json').read_text(encoding='utf-8'))
            task_name = meta.get('task_source_name', '?')
            archived_at = meta.get('archived_at', '?')
        except Exception:
            task_name = '?'
            archived_at = '?'

        # Count files (exclude metadata)
        file_count = sum(1 for f in arc.rglob('*') if f.is_file() and f.name != '_archive_meta.json')
        total_size = sum(f.stat().st_size for f in arc.rglob('*') if f.is_file())

        print(f"  {i}. {arc.name}")
        print(f"     Task source: {task_name}  |  Files: {file_count}  |  Size: {total_size / 1024:.1f} KB")
        print(f"     Created: {archived_at.replace('_', ' ').replace('-', '-', 2).replace('-', ':', 2)}")
        print()

    print(f"  Total: {len(archives)} archive(s)")
    print(f"  Restore with: scheduler-harness --restore <archive_folder_name>")
    print("=" * 60)


def strip_code_fences(text: str) -> str:
    """
    Strip markdown code fences from text.
    Handles: ```json ... ``` or ``` ... ```
    Returns the inner content if fences are found, otherwise returns original text.
    """
    if not text:
        return ""
    stripped = text.strip()
    pattern = re.compile(r'^```(?:json)?\s*\n(.*?)\n\s*```\s*$', re.DOTALL)
    match = pattern.match(stripped)
    if match:
        return match.group(1).strip()
    return text


def load_accumulated_results(results_file: Path) -> dict:
    """Load accumulated task results from results.json."""
    if results_file.exists():
        try:
            return json.loads(results_file.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            pass
    return {}


def get_phases(task_source: Path) -> list[dict]:
    """Get all phases from the task source file."""
    content = task_source.read_text(encoding='utf-8')
    all_tasks = parse_tasks.parse_tasks(content)
    return parse_tasks.get_phase_summary(all_tasks)


def get_uncompleted_tasks_for_phase(task_source: Path, phase: str, limit: int = None) -> list[dict]:
    """Get uncompleted tasks for a specific phase."""
    content = task_source.read_text(encoding='utf-8')
    all_tasks = parse_tasks.parse_tasks(content)
    uncompleted = parse_tasks.get_uncompleted_tasks(all_tasks)
    uncompleted = [t for t in uncompleted if t.get('phase') == phase]
    if limit is not None and limit > 0:
        uncompleted = uncompleted[:limit]
    
    # Return limited fields to match original subprocess behavior
    return [{'id': t['id'], 'description': t['description'], 'phase': t.get('phase')} for t in uncompleted]


def get_selected_tasks(task_source: Path, selection: str) -> list[dict]:
    """Get tasks filtered by selection string (range or cherry-pick)."""
    content = task_source.read_text(encoding='utf-8')
    all_tasks = parse_tasks.parse_tasks(content)
    selected = parse_tasks.filter_tasks_by_selection(all_tasks, selection)
    return [{'id': t['id'], 'description': t['description'], 'phase': t.get('phase'), 'completed': t['completed']} for t in selected]


def _execute_round(tasks: list[dict], args, base_dir: Path, runs_dir: Path, state: dict, results_file: Path, label: str = "") -> bool:
    """
    Execute a single round of tasks: build prompt, call Claude, apply results.
    Returns True on success, False on failure.
    """
    task_source = args.task_source

    accumulated_results = load_accumulated_results(results_file)

    # Build prompt (use template if specified)
    template_path = getattr(args, 'template', None)
    prompt = build_prompt.build_prompt(tasks, accumulated_results, template_path=template_path)
    if accumulated_results:
        print(f"    Passing {len(accumulated_results)} previous result(s) as context")

    output_file = runs_dir / f"round-{state['round']}.json"

    # Run Claude
    print("    Running Claude...")
    try:
        claude_result = subprocess.run(
            'claude --print --dangerously-skip-permissions',
            input=prompt,
            capture_output=True,
            text=True,
            shell=True,
            encoding='utf-8',
            errors='replace'
        )
        cleaned_output = strip_code_fences(claude_result.stdout)
        output_file.write_text(cleaned_output, encoding='utf-8')
        print(f"    Output saved to: {output_file}")
    except FileNotFoundError:
        print("    ⚠ Claude CLI not found, creating mock output...")
        task_ids = [t['id'] for t in tasks]
        mock_output = {
            "completed": task_ids,
            "failed": [],
            "blocked": []
        }
        output_file.write_text(json.dumps(mock_output, indent=2), encoding='utf-8')
        print(f"    Mock output saved to: {output_file}")

    # Apply results
    print("    Applying results...")
    try:
        results = apply_results.parse_output_file(output_file)
        completed = results.get('completed', [])
        if completed:
            apply_results.update_tasks_file(task_source, completed)
        apply_results.save_task_results(results_file, results)
    except Exception as e:
        print(f"    Apply failed: {e}")

    # Update state
    state_file = base_dir / 'state.json'
    state['task_source'] = str(task_source)
    state['last_run_file'] = output_file.name
    if label:
        state['current_phase'] = label
    state_file.write_text(json.dumps(state, indent=2))

    print(f"    ✓ Round {state['round']} done.")
    time.sleep(1)
    return True


def run_phase(phase_name: str, args, base_dir: Path, runs_dir: Path, state: dict, results_file: Path) -> bool:
    """
    Run all tasks in a single phase until complete.
    Returns True if all tasks in the phase completed, False if stopped early.
    """
    task_source = args.task_source

    print(f"\n{'━' * 60}")
    print(f"  ▶ Phase: {phase_name}")
    print(f"{'━' * 60}")

    while True:
        if state['rounds_this_run'] >= args.max_rounds:
            print(f"\n⚠ Reached max rounds ({args.max_rounds}). Pausing.")
            return False

        limit = None if args.mode == 'phase' else args.batch_size
        tasks = get_uncompleted_tasks_for_phase(task_source, phase_name, limit)

        if not tasks:
            print(f"\n  ✓ Phase '{phase_name}' complete!")
            return True

        state['round'] += 1
        state['rounds_this_run'] += 1

        current_batch_ids = [t['id'] for t in tasks]

        if current_batch_ids == state.get('last_batch'):
            state['retry_count'] = state.get('retry_count', 0) + 1
            if state['retry_count'] > state.get('max_retries', 3):
                print(f"    Reached max retries ({state.get('max_retries', 3)}). Aborting phase.")
                return False
            print(f"\n  [Round {state['round']}] 🔁 Retry {state['retry_count']}/{state.get('max_retries', 3)} for batch: {current_batch_ids}")
        else:
            state['retry_count'] = 0
            state['last_batch'] = current_batch_ids
            print(f"\n  [Round {state['round']}] ▶ Processing {len(tasks)} task(s) from '{phase_name}'...")
            for t in tasks:
                print(f"    - {t['id']}: {t['description'][:60]}")

        _execute_round(tasks, args, base_dir, runs_dir, state, results_file, label=phase_name)

    return True


def run_selected_tasks(args, base_dir: Path, runs_dir: Path, state: dict, results_file: Path) -> bool:
    """
    Run only the selected tasks (from --tasks argument).
    Supports range (T001:T005) and cherry-pick (T001,T003,T007) syntax.
    Returns True if all selected tasks completed, False otherwise.
    """
    task_source = args.task_source
    selection = args.tasks

    all_selected = get_selected_tasks(task_source, selection)

    if not all_selected:
        print(f"\n⚠ No tasks matched the selection: '{selection}'")
        return False

    # Separate completed vs uncompleted
    already_done = [t for t in all_selected if t.get('completed')]
    pending = [t for t in all_selected if not t.get('completed')]

    # Display selection summary
    print(f"\n{'━' * 60}")
    print(f"  ▶ Task Selection: {selection}")
    print(f"{'━' * 60}")
    print(f"  Selected {len(all_selected)} task(s): {[t['id'] for t in all_selected]}")
    if already_done:
        print(f"  ⏭ Already completed ({len(already_done)}): {[t['id'] for t in already_done]}")
    if pending:
        print(f"  ▶ To execute ({len(pending)}):")
        for t in pending:
            print(f"    - {t['id']}: {t['description'][:60]}")
    else:
        print(f"\n  ✓ All selected tasks are already complete!")
        return True

    # Execute in batches
    batch_size = args.batch_size
    i = 0
    while i < len(pending):
        if state['rounds_this_run'] >= args.max_rounds:
            print(f"\n⚠ Reached max rounds ({args.max_rounds}). Pausing.")
            return False

        # Re-read task source to check if tasks are now completed
        fresh_selected = get_selected_tasks(task_source, selection)
        fresh_pending = [t for t in fresh_selected if not t.get('completed')]

        if not fresh_pending:
            print(f"\n  ✓ All selected tasks completed!")
            return True

        batch = fresh_pending[:batch_size]
        state['round'] += 1
        state['rounds_this_run'] += 1

        current_batch_ids = [t['id'] for t in batch]

        if current_batch_ids == state.get('last_batch'):
            state['retry_count'] = state.get('retry_count', 0) + 1
            if state['retry_count'] > state.get('max_retries', 3):
                print(f"    Reached max retries ({state.get('max_retries', 3)}). Aborting.")
                return False
            print(f"\n  [Round {state['round']}] 🔁 Retry {state['retry_count']}/{state.get('max_retries', 3)} for: {current_batch_ids}")
        else:
            state['retry_count'] = 0
            state['last_batch'] = current_batch_ids
            remaining = len(fresh_pending)
            print(f"\n  [Round {state['round']}] ▶ Processing {len(batch)}/{remaining} selected task(s)...")
            for t in batch:
                print(f"    - {t['id']}: {t['description'][:60]}")

        _execute_round(batch, args, base_dir, runs_dir, state, results_file, label=f"selected({selection})")
        i += batch_size

    return True


def main():
    parser = argparse.ArgumentParser(description='Scheduler Harness for Long-Running')
    parser.add_argument('--task-source', required=False, default=None, help='Path to tasks.md')
    parser.add_argument('--batch-size', type=int, default=1, help='Tasks per round')
    parser.add_argument('--max-rounds', type=int, default=20, help='Maximum rounds')
    parser.add_argument('--mode', choices=['phase', 'task'], default='phase',
                        help='Execution mode: "phase" runs all tasks in a phase together, "task" runs them one by one')
    parser.add_argument('--max-retries', type=int, default=3, help='Maximum retries per batch')
    parser.add_argument('--phase', type=str, default=None,
                        help='Run only a specific phase (e.g. "Phase 1: File Operations")')
    parser.add_argument('--tasks', type=str, default=None,
                        help='Select specific tasks to execute. '
                             'Range: "T001:T005" (from T001 to T005). '
                             'Cherry-pick: "T001,T003,T007" (only these). '
                             'Single: "T003" (just one task). '
                             'Implies --mode task.')
    parser.add_argument('--reset', action='store_true',
                        help='Clean up all generated files (state.json, results.json, runs/, etc.) and exit')
    parser.add_argument('--archive', action='store_true',
                        help='Archive current runtime files (state, results, runs, task source) into a timestamped zip and exit')
    parser.add_argument('--restore', type=str, default=None, metavar='ARCHIVE',
                        help='Restore runtime state from a previously created archive and exit. '
                             'Accepts a filename (looked up in archives/) or a full path.')
    parser.add_argument('--list-archives', action='store_true',
                        help='List all available archives and exit')
    parser.add_argument('--template', type=str, default=None,
                        help='Path to a custom prompt template file (see build-prompt --init-template)')
    parser.add_argument('--init-template', nargs='?', const='.prompt-template.md', metavar='PATH',
                        help='Generate a default prompt template file for customization and exit')
    
    # Optional flags to override default output locations (useful if not running in current dir)
    parser.add_argument('--work-dir', type=str, default='.', help='Working directory for output files (state, results, runs)')
    
    args = parser.parse_args()

    work_dir = Path(args.work_dir).absolute()

    if args.init_template is not None:
        output_path = build_prompt.init_template(args.init_template)
        print(f"✓ Template generated: {output_path.absolute()}")
        print(f"  Edit it to customize your prompt, then use:")
        print(f"  scheduler-harness --task-source tasks.md --template {output_path}")
        sys.exit(0)

    if args.list_archives:
        do_list_archives(work_dir)
        sys.exit(0)

    if args.restore:
        archive_path = Path(args.restore)
        if not archive_path.is_absolute():
            archive_path = work_dir / 'archives' / archive_path
        do_restore(work_dir, archive_path)
        sys.exit(0)

    if args.reset:
        task_source = Path(args.task_source).absolute() if args.task_source else None
        do_reset(work_dir, task_source)
        sys.exit(0)

    if args.archive:
        task_source = Path(args.task_source).absolute() if args.task_source else None
        do_archive(work_dir, task_source)
        sys.exit(0)

    if not args.task_source:
        parser.error('--task-source is required (unless using --reset)')

    runs_dir = work_dir / 'runs'
    state_file = work_dir / 'state.json'
    results_file = work_dir / 'results.json'

    # Ensure task source exists and get absolute path
    task_source = Path(args.task_source).absolute()
    if not task_source.exists():
        print(f"Error: Task file not found: {task_source}")
        sys.exit(1)
        
    args.task_source = task_source

    runs_dir.mkdir(parents=True, exist_ok=True)

    if state_file.exists():
        state = json.loads(state_file.read_text())
        state["max_retries"] = args.max_retries
    else:
        state = {
            "round": 0,
            "task_source": "",
            "last_batch": [],
            "last_run_file": None,
            "retry_count": 0,
            "max_retries": args.max_retries,
            "current_phase": None
        }

    state['rounds_this_run'] = 0

    # When --tasks is used, implicitly set mode to 'task'
    if args.tasks:
        args.mode = 'task'

    phases = get_phases(task_source)

    print("═" * 60)
    print("  Scheduler Harness for Long-Running")
    print("═" * 60)
    print(f"  Task source:   {task_source}")
    print(f"  Working dir:   {work_dir}")
    print(f"  Batch size:    {args.batch_size}")
    print(f"  Max rounds:    {args.max_rounds}")
    print(f"  Start round:   {state['round']}")
    print(f"  Mode:          {args.mode} (batch size: {args.batch_size if args.mode == 'task' else 'ALL'})")
    if args.tasks:
        print(f"  Task filter:   {args.tasks}")
    print(f"  Max retries:   {args.max_retries}")
    print(f"  Template:      {args.template or '(built-in default)'}")
    print(f"  Results file:  {results_file}")
    print(f"  Phases found:  {len(phases)}")

    # Get selected task IDs for highlighting (if --tasks is used)
    selected_task_ids = set()
    if args.tasks:
        selected_raw = get_selected_tasks(task_source, args.tasks)
        selected_task_ids = {t['id'] for t in selected_raw}

    if phases:
        print(f"\n{'─' * 60}")
        print("  Phase Overview:")
        print(f"{'─' * 60}")
        for p in phases:
            status = "✓ DONE" if p['all_done'] else f"  {p['remaining']} remaining"
            phase_filter = " ← (selected)" if args.phase and p['phase'] == args.phase else ""
            print(f"  [{status}] {p['phase']} ({p['completed']}/{p['total']}){phase_filter}")
            # If --tasks is used, highlight selected tasks under each phase
            if selected_task_ids:
                phase_selected = [tid for tid in p.get('task_ids', []) if tid in selected_task_ids]
                if phase_selected:
                    print(f"           ↳ selected: {phase_selected}")
    print("═" * 60)

    # --tasks mode: run only selected tasks (bypass phase logic)
    if args.tasks:
        completed = run_selected_tasks(args, work_dir, runs_dir, state, results_file)

        if not completed:
            pass  # fall through to final summary
    else:
        # Normal phase-based execution
        if args.phase:
            target_phases = [p for p in phases if p['phase'] == args.phase]
            if not target_phases:
                print(f"\nError: Phase '{args.phase}' not found.")
                print(f"Available phases: {[p['phase'] for p in phases]}")
                sys.exit(1)
        else:
            target_phases = [p for p in phases if not p['all_done']]

        if not target_phases:
            print("\n✓ All phases are already complete!")
            sys.exit(0)

        for phase_info in target_phases:
            phase_name = phase_info['phase']

            if phase_info['all_done']:
                print(f"\n  ⏭ Skipping '{phase_name}' (already complete)")
                continue

            completed = run_phase(
                phase_name, args, work_dir, runs_dir, state, results_file
            )

            if not completed:
                break

        accumulated = load_accumulated_results(results_file)
        if accumulated:
            print(f"\n{'─' * 60}")
            print(f"  Accumulated Results ({len(accumulated)} tasks):")
            print(f"{'─' * 60}")
            for tid, res in accumulated.items():
                status_icon = "✓" if res.get('status') == 'completed' else "✗"
                output = res.get('output', 'no output')[:60]
                print(f"    {status_icon} {tid}: {output}")
            print(f"{'─' * 60}")

    print(f"\n{'═' * 60}")
    final_results = load_accumulated_results(results_file)
    completed_count = sum(1 for r in final_results.values() if r.get('status') == 'completed')
    total_count = len(final_results)
    print(f"  Complete. Total rounds: {state['round']}")
    print(f"  Results: {completed_count}/{total_count} tasks completed")
    print(f"  Results saved to: {results_file}")
    print("═" * 60)

if __name__ == '__main__':
    main()
