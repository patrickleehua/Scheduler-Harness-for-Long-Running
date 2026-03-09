#!/usr/bin/env python3
"""
Scheduler Harness - Main Runner

Executes tasks phase by phase. Each phase completes fully before moving to the next.
Previous phase results are passed as context to subsequent phases.

Usage:
    python run.py --task-source ./tasks.md --batch-size 1 --max-rounds 20
    python run.py --task-source ./tasks.md --batch-size 3 --max-rounds 10 --phase "Phase 1: File Operations"
    python run.py --reset                          # Clean generated files (no task-source needed)
    python run.py --reset --task-source ./tasks.md  # Also reset task checkboxes in tasks.md
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def do_reset(base_dir: Path, task_source: Path = None):
    """
    Clean up all runtime-generated files, restoring the project to a fresh state.

    Files/directories removed:
      - state.json
      - results.json
      - runs/  (entire directory with round-*.json files)
      - .tasks_cache.json  (temp file, if leftover)
      - .results_context.json  (temp file, if leftover)

    If a task source file is provided, all completed task checkboxes
    (- [x]) are reset back to unchecked (- [ ]).
    """
    print("=" * 60)
    print("  [RESET] Cleaning generated files...")
    print("=" * 60)

    removed = []
    skipped = []

    # Files to remove
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

    # Remove runs/ directory (contains round-*.json)
    runs_dir = base_dir / 'runs'
    if runs_dir.exists():
        file_count = sum(1 for _ in runs_dir.iterdir())
        shutil.rmtree(runs_dir)
        removed.append(f"runs/  ({file_count} file(s))")
    else:
        skipped.append("runs/")

    # Reset task checkboxes in task source file  (- [x] -> - [ ])
    if task_source and task_source.exists():
        content = task_source.read_text(encoding='utf-8')
        updated = re.sub(r'^(\s*- )\[x\]', r'\1[ ]', content, flags=re.MULTILINE | re.IGNORECASE)
        if updated != content:
            task_source.write_text(updated, encoding='utf-8')
            removed.append(f"Reset checkboxes in {task_source.name}")
        else:
            skipped.append(f"No checked boxes in {task_source.name}")

    # Summary
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


def strip_code_fences(text: str) -> str:
    """
    Strip markdown code fences from text.
    Handles: ```json ... ``` or ``` ... ```
    Returns the inner content if fences are found, otherwise returns original text.
    """
    if not text:
        return ""
    # Strip leading/trailing whitespace
    stripped = text.strip()

    # Pattern: ```json\n...\n``` or ```\n...\n```
    pattern = re.compile(r'^```(?:json)?\s*\n(.*?)\n\s*```\s*$', re.DOTALL)
    match = pattern.match(stripped)
    if match:
        return match.group(1).strip()

    return text


def load_accumulated_results(runs_dir: Path, results_file: Path) -> dict:
    """
    Load accumulated task results from results.json.
    This file is maintained by apply_results.py and contains all previous task outputs.
    """
    if results_file.exists():
        try:
            return json.loads(results_file.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            pass
    return {}


def get_phases(scripts_dir: Path, task_source: Path) -> list[dict]:
    """Get all phases from the task source file."""
    result = subprocess.run(
        [sys.executable, str(scripts_dir / 'parse_tasks.py'),
         '--task-source', str(task_source),
         '--list-phases', '--json'],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        return json.loads(result.stdout)
    return []


def get_uncompleted_tasks_for_phase(scripts_dir: Path, task_source: Path,
                                     phase: str, limit: int = None) -> list[dict]:
    """Get uncompleted tasks for a specific phase."""
    cmd = [
        sys.executable, str(scripts_dir / 'parse_tasks.py'),
        '--task-source', str(task_source),
        '--phase', phase,
        '--json'
    ]
    if limit is not None:
        cmd.extend(['--limit', str(limit)])
        
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error fetching tasks: {result.stderr}")
        return []
        
    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return []


def run_phase(phase_name: str, args, base_dir: Path, scripts_dir: Path,
              runs_dir: Path, state: dict, results_file: Path, tasks_cache: Path) -> bool:
    """
    Run all tasks in a single phase until complete.
    Returns True if all tasks in the phase completed, False if stopped early.
    """
    task_source = Path(args.task_source)

    print(f"\n{'━' * 60}")
    print(f"  ▶ Phase: {phase_name}")
    print(f"{'━' * 60}")

    phase_rounds = 0

    while True:
        # Check max rounds
        if state['rounds_this_run'] >= args.max_rounds:
            print(f"\n⚠ Reached max rounds ({args.max_rounds}). Pausing.")
            return False

        # Get uncompleted tasks for this phase
        limit = None if args.mode == 'phase' else args.batch_size
        tasks = get_uncompleted_tasks_for_phase(
            scripts_dir, task_source, phase_name, limit
        )

        if not tasks:
            print(f"\n  ✓ Phase '{phase_name}' complete!")
            return True

        # Increment round
        state['round'] += 1
        state['rounds_this_run'] += 1
        phase_rounds += 1

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

        # Save tasks cache
        tasks_cache.write_text(json.dumps(tasks))

        # Load accumulated results from previous rounds
        accumulated_results = load_accumulated_results(runs_dir, results_file)

        # Build prompt (pass previous results for context)
        build_cmd = [
            sys.executable, str(scripts_dir / 'build_prompt.py'),
            '--tasks-file', str(tasks_cache)
        ]

        # If we have previous results, write them to a temp file and pass it
        if accumulated_results:
            results_context_file = base_dir / '.results_context.json'
            results_context_file.write_text(
                json.dumps(accumulated_results, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
            build_cmd.extend(['--results-file', str(results_context_file)])
            print(f"    Passing {len(accumulated_results)} previous result(s) as context")

        prompt_result = subprocess.run(build_cmd, capture_output=True, text=True)
        prompt = prompt_result.stdout

        # Output file
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
            # Strip markdown code fences (```json ... ```) from output
            cleaned_output = strip_code_fences(claude_result.stdout)
            output_file.write_text(cleaned_output, encoding='utf-8')
            print(f"    Output saved to: {output_file}")
        except FileNotFoundError:
            print("   ! Claude CLI not found, creating mock output...")
            task_ids = [t['id'] for t in tasks]
            mock_output = {
                "completed": task_ids,
                "failed": [],
                "blocked": []
            }
            output_file.write_text(json.dumps(mock_output, indent=2), encoding='utf-8')
            print(f"    Mock output saved to: {output_file}")

        # Apply results (with --results-file to accumulate results)
        print("    Applying results...")
        apply_cmd = [
            sys.executable, str(scripts_dir / 'apply_results.py'),
            '--output-file', str(output_file),
            '--task-source', str(task_source),
            '--results-file', str(results_file)
        ]
        apply_result = subprocess.run(apply_cmd, capture_output=True, text=True)
        print(apply_result.stdout)

        if apply_result.returncode != 0:
            print(f"    Apply failed: {apply_result.stderr}")

        # Update state
        state_file = base_dir / 'state.json'
        state['task_source'] = str(task_source)
        state['last_run_file'] = output_file.name
        state['current_phase'] = phase_name
        state_file.write_text(json.dumps(state, indent=2))

        print(f"    ✓ Round {state['round']} done.")

        # Cleanup
        if tasks_cache.exists():
            tasks_cache.unlink()
        results_context = base_dir / '.results_context.json'
        if results_context.exists():
            results_context.unlink()

        time.sleep(1)

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
    parser.add_argument('--reset', action='store_true',
                        help='Clean up all generated files (state.json, results.json, runs/, etc.) and exit')
    args = parser.parse_args()

    # Paths
    base_dir = Path(__file__).parent

    # Handle --reset before anything else
    if args.reset:
        task_source = Path(args.task_source) if args.task_source else None
        do_reset(base_dir, task_source)
        sys.exit(0)

    # For normal execution, --task-source is required
    if not args.task_source:
        parser.error('--task-source is required (unless using --reset)')

    # Paths (continued)
    scripts_dir = base_dir / 'scripts'
    runs_dir = base_dir / 'runs'
    state_file = base_dir / 'state.json'
    tasks_cache = base_dir / '.tasks_cache.json'
    results_file = base_dir / 'results.json'

    task_source = Path(args.task_source)
    if not task_source.exists():
        print(f"Error: Task file not found: {task_source}")
        sys.exit(1)

    # Ensure runs directory
    runs_dir.mkdir(exist_ok=True)

    # Load or init state
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

    # Get all phases
    phases = get_phases(scripts_dir, task_source)

    print("═" * 60)
    print("  Scheduler Harness for Long-Running")
    print("═" * 60)
    print(f"  Task source:   {task_source}")
    print(f"  Batch size:    {args.batch_size}")
    print(f"  Max rounds:    {args.max_rounds}")
    print(f"  Start round:   {state['round']}")
    print(f"  Mode:          {args.mode} (batch size: {args.batch_size if args.mode == 'task' else 'ALL'})")
    print(f"  Max retries:   {args.max_retries}")
    print(f"  Results file:  {results_file}")
    print(f"  Phases found:  {len(phases)}")

    # Show phase overview
    if phases:
        print(f"\n{'─' * 60}")
        print("  Phase Overview:")
        print(f"{'─' * 60}")
        for p in phases:
            status = "✓ DONE" if p['all_done'] else f"  {p['remaining']} remaining"
            phase_filter = " ← (selected)" if args.phase and p['phase'] == args.phase else ""
            print(f"  [{status}] {p['phase']} ({p['completed']}/{p['total']}){phase_filter}")
    print("═" * 60)

    # Determine which phases to run
    if args.phase:
        # Run only the specified phase
        target_phases = [p for p in phases if p['phase'] == args.phase]
        if not target_phases:
            print(f"\nError: Phase '{args.phase}' not found.")
            print(f"Available phases: {[p['phase'] for p in phases]}")
            sys.exit(1)
    else:
        # Run all phases in order, skipping completed ones
        target_phases = [p for p in phases if not p['all_done']]

    if not target_phases:
        print("\n✓ All phases are already complete!")
        sys.exit(0)

    # Execute phases in order
    for phase_info in target_phases:
        phase_name = phase_info['phase']

        if phase_info['all_done']:
            print(f"\n  ⏭ Skipping '{phase_name}' (already complete)")
            continue

        completed = run_phase(
            phase_name, args, base_dir, scripts_dir,
            runs_dir, state, results_file, tasks_cache
        )

        if not completed:
            # Max rounds reached, stop
            break

        # Show accumulated results summary before moving to next phase
        accumulated = load_accumulated_results(runs_dir, results_file)
        if accumulated:
            print(f"\n{'─' * 60}")
            print(f"  Accumulated Results ({len(accumulated)} tasks):")
            print(f"{'─' * 60}")
            for tid, res in accumulated.items():
                status_icon = "✓" if res.get('status') == 'completed' else "✗"
                output = res.get('output', 'no output')[:60]
                print(f"    {status_icon} {tid}: {output}")
            print(f"{'─' * 60}")

    # Final summary
    print(f"\n{'═' * 60}")
    final_results = load_accumulated_results(runs_dir, results_file)
    completed_count = sum(1 for r in final_results.values() if r.get('status') == 'completed')
    total_count = len(final_results)
    print(f"  Complete. Total rounds: {state['round']}")
    print(f"  Results: {completed_count}/{total_count} tasks completed")
    print(f"  Results saved to: {results_file}")
    print("═" * 60)


if __name__ == '__main__':
    main()
