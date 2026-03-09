#!/usr/bin/env python3
"""
Build worker prompt for the current round of tasks.

Usage:
    python3 scripts/build_prompt.py --tasks '[{"id":"T001","description":"Do something"}]'
    python3 scripts/build_prompt.py --tasks-file ./current_tasks.json
    python3 scripts/build_prompt.py --tasks-file ./current_tasks.json --results-file ./results.json
"""

import argparse
import json
import sys
from pathlib import Path


def build_prompt(tasks: list[dict], previous_results: dict = None) -> str:
    """
    Generate worker prompt for the given tasks.

    Args:
        tasks: List of task dicts with 'id' and 'description' keys
        previous_results: Dict of previous task results {task_id: result_data}

    Returns:
        Prompt string for Claude worker
    """
    if not tasks:
        return ""

    task_ids = [t['id'] for t in tasks]
    task_id_list = '\n'.join(task_ids)

    task_details = '\n\n'.join([
        f"### {t['id']}\n{t['description']}"
        for t in tasks
    ])

    # Build context from previous results
    context_section = ""
    if previous_results:
        context_lines = []
        for tid, result in previous_results.items():
            if result.get('status') == 'completed' and result.get('output'):
                context_lines.append(f"- {tid}: {result['output']}")
        if context_lines:
            context_section = f"""
## Previous Task Results (for context)
The following tasks were completed previously. You can use their results:

{chr(10).join(context_lines)}

"""

    prompt = f"""You are a stateless coding worker.
{context_section}
Work ONLY on these task IDs:
{task_id_list}

Task Details:
{task_details}

Rules:
- Do only the assigned tasks listed above
- Do not start other tasks
- If a task is completed, report it clearly by task ID
- If a task is blocked or failed, report it clearly by task ID
- Do not claim unfinished work is done
- After completing each task, verify your work
- Include meaningful output info for each completed task (file paths, key values, etc.)

At the end, output a JSON object in this exact shape (no additional text after it):

```json
{{
  "completed": ["T001"],
  "failed": [],
  "blocked": [],
  "results": {{
    "T001": {{
      "output": "Created file /path/to/file.txt",
      "files": ["path/to/file.txt"],
      "data": {{}}
    }}
  }}
}}
```

- completed/failed/blocked: arrays of task IDs
- results: optional dict with task ID keys and execution details
  - output: human-readable summary of what was done
  - files: array of files created/modified
  - data: any structured data to pass to future tasks
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(description='Build worker prompt for tasks')
    parser.add_argument('--tasks', help='JSON array of tasks')
    parser.add_argument('--tasks-file', help='Path to JSON file containing tasks')
    parser.add_argument('--results-file', help='Path to JSON file containing previous task results')

    args = parser.parse_args()

    tasks = []
    previous_results = None

    if args.tasks:
        tasks = json.loads(args.tasks)
    elif args.tasks_file:
        with open(args.tasks_file, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    else:
        print("Error: Must provide --tasks or --tasks-file", file=sys.stderr)
        sys.exit(1)

    # Load previous results if provided
    if args.results_file:
        results_path = Path(args.results_file)
        if results_path.exists():
            with open(results_path, 'r', encoding='utf-8') as f:
                previous_results = json.load(f)

    prompt = build_prompt(tasks, previous_results)
    print(prompt)


if __name__ == '__main__':
    main()
