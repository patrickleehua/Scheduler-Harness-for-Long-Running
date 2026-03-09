#!/usr/bin/env python3
"""
Build worker prompt for the current round of tasks.

Supports a template-based system with customizable prompts.
Users can generate a default template, modify it freely, and pass it at runtime.

Runtime placeholders (auto-populated from task data, NOT user-editable):
    {{PREVIOUS_RESULTS}}  - Previous completed task results (auto-generated)
    {{TASK_ID_LIST}}      - Newline-separated list of task IDs to work on
    {{TASK_DETAILS}}      - Formatted task descriptions (### T001\\nDescription...)

Everything else in the template is plain text that users edit directly.

Usage:
    # Use default built-in template
    build-prompt --tasks-file tasks.json

    # Generate a template file for customization
    build-prompt --init-template
    build-prompt --init-template my_template.md

    # Use a custom template
    build-prompt --tasks-file tasks.json --template my_template.md
"""

import argparse
import json
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# Default template — written as plain text.
# Only 3 runtime placeholders exist (auto-populated from data).
# Everything else is directly editable by the user.
# ──────────────────────────────────────────────────────────────

DEFAULT_TEMPLATE = """\
You are a stateless coding worker.
{{PREVIOUS_RESULTS}}
Work ONLY on these task IDs:
{{TASK_ID_LIST}}

Task Details:
{{TASK_DETAILS}}

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
{
  "completed": ["T001"],
  "failed": [],
  "blocked": [],
  "results": {
    "T001": {
      "output": "Created file /path/to/file.txt",
      "files": ["path/to/file.txt"],
      "data": {}
    }
  }
}
```

- completed/failed/blocked: arrays of task IDs
- results: optional dict with task ID keys and execution details
  - output: human-readable summary of what was done
  - files: array of files created/modified
  - data: any structured data to pass to future tasks
"""

# ──────────────────────────────────────────────────────────────
# Template file header (comments stripped at runtime)
# ──────────────────────────────────────────────────────────────

TEMPLATE_FILE_HEADER = """\
# ─────────────────────────────────────────────────────────────
# Prompt Template for Scheduler Harness
# ─────────────────────────────────────────────────────────────
#
# Edit this file freely to customize the prompt sent to the LLM worker.
# All text is sent as-is, except for 3 runtime placeholders:
#
#   {{PREVIOUS_RESULTS}}  - Auto-replaced with completed task results
#   {{TASK_ID_LIST}}      - Auto-replaced with the task IDs for this round
#   {{TASK_DETAILS}}      - Auto-replaced with full task descriptions
#
# These 3 placeholders are filled automatically from your task data.
# Everything else is plain text — edit it directly!
#
# Examples of customizations you can make:
#   - Change the role description (first line)
#   - Add domain-specific instructions (e.g. "Always write unit tests")
#   - Remove or reorder sections
#   - Change the output format
#   - Add project-specific context
#
# Lines starting with # at the TOP of the file are stripped as comments.
# ─────────────────────────────────────────────────────────────

"""


def _strip_template_comments(template: str) -> str:
    """
    Strip leading comment lines (lines starting with #) from the template.
    Stops at the first non-comment, non-empty line.
    """
    lines = template.split('\n')
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == '' or stripped.startswith('#'):
            start = i + 1
        else:
            break
    return '\n'.join(lines[start:])


def _build_previous_results_section(previous_results: dict) -> str:
    """Build the previous results context section from accumulated results."""
    if not previous_results:
        return ""

    context_lines = []
    for tid, result in previous_results.items():
        if result.get('status') == 'completed' and result.get('output'):
            context_lines.append(f"- {tid}: {result['output']}")

    if not context_lines:
        return ""

    return (
        "\n## Previous Task Results (for context)\n"
        "The following tasks were completed previously. You can use their results:\n\n"
        + "\n".join(context_lines)
        + "\n"
    )


def _build_task_id_list(tasks: list[dict]) -> str:
    """Build newline-separated list of task IDs."""
    return '\n'.join(t['id'] for t in tasks)


def _build_task_details(tasks: list[dict]) -> str:
    """Build formatted task details section."""
    return '\n\n'.join(
        f"### {t['id']}\n{t['description']}"
        for t in tasks
    )


def load_template(template_path: str | Path | None) -> str:
    """
    Load prompt template from file, or return the built-in default.

    Args:
        template_path: Path to a template file, or None for default

    Returns:
        Template string with {{PLACEHOLDER}} markers
    """
    if template_path is None:
        return DEFAULT_TEMPLATE

    path = Path(template_path)
    if not path.exists():
        print(f"Warning: Template file not found: {path}, using default template.",
              file=sys.stderr)
        return DEFAULT_TEMPLATE

    raw = path.read_text(encoding='utf-8')
    return _strip_template_comments(raw)


def render_template(template: str, variables: dict) -> str:
    """
    Replace {{PLACEHOLDER}} markers in the template with actual values.

    Args:
        template: Template string with {{KEY}} placeholders
        variables: Dict mapping placeholder names to replacement values

    Returns:
        Rendered prompt string
    """
    result = template
    for key, value in variables.items():
        placeholder = '{{' + key + '}}'
        result = result.replace(placeholder, value)
    return result


def build_prompt(
    tasks: list[dict],
    previous_results: dict = None,
    template_path: str | Path | None = None,
    extra_variables: dict = None,
) -> str:
    """
    Generate worker prompt for the given tasks.

    Args:
        tasks: List of task dicts with 'id' and 'description' keys
        previous_results: Dict of previous task results {task_id: result_data}
        template_path: Path to custom template file, or None for default
        extra_variables: Additional custom variables to inject into the template

    Returns:
        Prompt string for LLM worker
    """
    if not tasks:
        return ""

    template = load_template(template_path)

    # Build runtime variables (these 3 are auto-populated from data)
    variables = {
        'PREVIOUS_RESULTS': _build_previous_results_section(previous_results),
        'TASK_ID_LIST': _build_task_id_list(tasks),
        'TASK_DETAILS': _build_task_details(tasks),
    }

    # Merge any extra custom variables
    if extra_variables:
        variables.update(extra_variables)

    return render_template(template, variables)


def init_template(output_path: str | Path | None = None) -> Path:
    """
    Generate a default template file that users can customize.

    Args:
        output_path: Where to write the template. Defaults to .prompt-template.md

    Returns:
        Path to the generated template file
    """
    if output_path is None:
        path = Path('.prompt-template.md')
    else:
        path = Path(output_path)

    content = TEMPLATE_FILE_HEADER + DEFAULT_TEMPLATE
    path.write_text(content, encoding='utf-8')
    return path


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Build worker prompt for tasks (template-based)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Build prompt with default template
  build-prompt --tasks-file tasks.json

  # Build prompt with custom template
  build-prompt --tasks-file tasks.json --template my_prompt.md

  # Generate a template file for customization
  build-prompt --init-template
  build-prompt --init-template custom_prompt.md

  # Override/add a custom variable in the template
  build-prompt --tasks-file tasks.json --var PROJECT_NAME="My App"
""",
    )

    # ── Mutually exclusive primary actions ──
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        '--init-template',
        nargs='?',
        const='.prompt-template.md',
        metavar='PATH',
        help='Generate a default template file for customization (default: .prompt-template.md)',
    )

    # ── Prompt building options ──
    parser.add_argument('--tasks', help='JSON array of tasks (inline)')
    parser.add_argument('--tasks-file', help='Path to JSON file containing tasks')
    parser.add_argument('--results-file', help='Path to JSON file containing previous task results')
    parser.add_argument(
        '--template',
        metavar='PATH',
        help='Path to a custom prompt template file',
    )
    parser.add_argument(
        '--var',
        action='append',
        metavar='KEY=VALUE',
        help='Add a custom template variable (can be used multiple times, e.g. --var PROJECT="MyApp")',
    )

    args = parser.parse_args()

    # ── Action: init-template ──
    if args.init_template is not None:
        output_path = init_template(args.init_template)
        print(f"Template generated: {output_path.absolute()}", file=sys.stderr)
        print(f"  Edit it to customize your prompt, then use:", file=sys.stderr)
        print(f"  build-prompt --tasks-file tasks.json --template {output_path}", file=sys.stderr)
        return

    # ── Action: build prompt ──
    tasks = []
    previous_results = None

    if args.tasks:
        tasks = json.loads(args.tasks)
    elif args.tasks_file:
        with open(args.tasks_file, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
    else:
        print("Error: Must provide --tasks or --tasks-file (or use --init-template)",
              file=sys.stderr)
        sys.exit(1)

    # Load previous results if provided
    if args.results_file:
        results_path = Path(args.results_file)
        if results_path.exists():
            with open(results_path, 'r', encoding='utf-8') as f:
                previous_results = json.load(f)

    # Parse --var custom variables
    extra_variables = {}
    if args.var:
        for var_str in args.var:
            if '=' not in var_str:
                print(f"Error: --var must be in KEY=VALUE format, got: {var_str}",
                      file=sys.stderr)
                sys.exit(1)
            key, value = var_str.split('=', 1)
            extra_variables[key.strip()] = value.strip()

    prompt = build_prompt(
        tasks,
        previous_results,
        template_path=args.template,
        extra_variables=extra_variables,
    )
    print(prompt)


if __name__ == '__main__':
    main()
