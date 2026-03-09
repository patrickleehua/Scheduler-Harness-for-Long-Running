# Scheduler Harness for Long-Running

A task execution harness that orchestrates LLMs (specifically Claude) to execute long-running coding and automation tasks completely autonomously. It parses Markdown task lists, organizes them by phase, executes them progressively, and persists results statefully across steps and phases.

## Features

- **Phase-Aware Execution**: Groups tasks into logical phases (e.g., `Phase 1: File Operations`, `Phase 2: Data Processing`). A phase is completed entirely before the harness moves to the next one.
- **Granular Execution Modes (`--mode`)**:
  - `phase` mode (default): Fetches all remaining tasks in the current phase and passes them to the LLM at once.
  - `task` mode: Fetches and assigns tasks individually (controlled by `--batch-size`) to ensure maximum focus.
- **Stateful Results Accumulation**: Each task's output is recorded into `results.json` and automatically provided as context for subsequent rounds and phases. The LLM dynamically remembers exactly what it did previously.
- **Retry Mechanism**: Automatically detects when the agent stalls or fails to complete a task. Controlled via `--max-retries` (default: 3). If it repeatedly fails a batch, the execution is safely aborted to prevent infinite cost loops.
- **Resumable**: Saves execution state to `state.json`. If execution stops or is killed, you can run it again and it picks up right where it left off.

## Installation

You can install it directly via pip or uv:

```bash
# Using pip
pip install scheduler-harness

# Or using uv (recommended for isolated tools)
uv tool install scheduler-harness
```

If you download the source code, you can also install it locally:
```bash
uv pip install -e .
```

## Usage

```bash
scheduler-harness --task-source <path_to_tasks.md> [options]
```

### Options

- `--task-source`: (Required) Path to the Markdown file containing lists of tasks.
- `--mode {phase,task}`: Execution mode. `phase` runs all remaining tasks in a phase together. `task` runs them sequentially, subdivided by batches. (Default: `phase`)
- `--batch-size`: How many tasks to pass to Claude per round in `task` mode. (Default: 1)
- `--phase <PHASE_NAME>`: Run only a specific phase by exactly matching its title. Example: `--phase "Phase 1: File Operations"`
- `--tasks <SELECTION>`: Select specific tasks to execute. Supported formats:
  - **Range**: `--tasks "T001:T005"` — execute from T001 to T005 (inclusive, in file order)
  - **Cherry-pick**: `--tasks "T001,T003,T007"` — execute only the listed tasks
  - **Single**: `--tasks T003` — execute just one task
  - Automatically implies `--mode task`. Already-completed tasks are skipped.
- `--max-rounds`: Maximum number of round requests to execute in one run. (Default: 20)
- `--max-retries`: Maximum consecutive retries allowed for a failing or stalled batch before aborting. (Default: 3)
- `--reset`: Clean up all runtime-generated files (`state.json`, `results.json`, `runs/`, temp files) and exit. If `--task-source` is also provided, resets all completed checkboxes (`- [x]` → `- [ ]`) in the task file.
- `--archive`: Archive all current runtime-generated files (`state.json`, `results.json`, `runs/`, task source) into a timestamped directory under `archives/` and exit. Archive naming format: `<task_filename>_<yyyy-mm-dd_HH-MM-SS>/`.
- `--restore <ARCHIVE>`: Restore runtime state from a previously created archive directory. Accepts a folder name (looked up in `archives/`) or a full path. Overwrites current files.
- `--list-archives`: List all available archives with metadata (task source, file count, size, timestamp) and exit.
- `--work-dir`: Working directory for output files (state, results, runs). Defaults to the current directory.
- `--template <PATH>`: Path to a custom prompt template file. See [Prompt Template Customization](#prompt-template-customization) below.
- `--init-template [PATH]`: Generate a default prompt template file for customization and exit. Defaults to `.prompt-template.md`.

### Examples

**Default execution (process phase by phase until everything is done):**
```bash
scheduler-harness --task-source demo_tasks.md
```

**One-by-one execution (safest for complex iterative tasks):**
```bash
scheduler-harness --task-source demo_tasks.md --mode task
```

**Run only a specific Phase, passing max 2 tasks at a time:**
```bash
scheduler-harness --task-source demo_tasks.md --mode task --batch-size 2 --phase "Phase 2: Data Processing"
```

**Reset all generated files (start fresh):**
```bash
scheduler-harness --reset
```

**Reset including task checkboxes in the task file:**
```bash
scheduler-harness --reset --task-source demo_tasks.md
```

**Execute a range of tasks (T002 through T005):**
```bash
scheduler-harness --task-source demo_tasks.md --tasks "T002:T005"
```

**Execute specific cherry-picked tasks:**
```bash
scheduler-harness --task-source demo_tasks.md --tasks "T001,T003,T008"
```

**Execute a single task:**
```bash
scheduler-harness --task-source demo_tasks.md --tasks T006
```

**Execute selected tasks with batch size 2:**
```bash
scheduler-harness --task-source demo_tasks.md --tasks "T003:T007" --batch-size 2
```

## Task File Format (`tasks.md`)

Tasks are defined in standard Markdown checklists under Phase headers (`##`). The header format and checkbox formats are evaluated strictly:

```markdown
## Phase 1: Setup

- [ ] T001 Initialize the project structure
- [x] T002 Task that is already completed

## Phase 2: Implementation

- [ ] T003 Implement core logic
```
*Note: Phase headers must be exactly `## Phase Title`. Task lines must be `- [ ] ID Description` where ID starts with alphabetical letters followed by numbers (e.g., T001, B23).*

## Prompt Template Customization

The prompt sent to the LLM is fully customizable. The template is plain text — just edit it directly. Only 3 runtime placeholders (`{{PREVIOUS_RESULTS}}`, `{{TASK_ID_LIST}}`, `{{TASK_DETAILS}}`) are auto-filled from task data; everything else is your own text.

```bash
# Generate a default template, edit it, then use it
scheduler-harness --init-template                                        # → .prompt-template.md
scheduler-harness --task-source tasks.md --template .prompt-template.md  # use custom template
```

## How it Works

1. **`parse-tasks`** scans the Markdown text to find the first Phase with uncompleted tasks.
2. **`scheduler-harness`** fetches the tasks according to the selected `--mode` (`phase` or `task`).
3. **`scheduler-harness`** loads the accumulated historical results from `results.json` and injects them as active context.
4. **`build-prompt`** constructs the instruction prompt for Claude using the template (custom or built-in default).
5. Claude executes the requested commands/bash shell prompts.
6. **`apply-results`** parses Claude's JSON output, marks the tasks as `[x]` in the original `tasks.md`, and pushes the execution traces backward into `results.json`.
7. Increments the state tracking in `state.json` and loops back to step 1 automatically.


```bash
# Execute all tasks in order of Phase
scheduler-harness --task-source demo_tasks.md --batch-size 2 --max-rounds 20

# Execute only the specified Phase
scheduler-harness --task-source demo_tasks.md --phase "Phase 2: Data Processing"

# Check the status of Phases
parse-tasks --task-source demo_tasks.md --list-phases

# Clear all generated files and restore to the initial state
scheduler-harness --reset

# Clear generated files, and also reset the checkboxes in the task file
scheduler-harness --reset --task-source demo_tasks.md

# Archive current state (creates archives/demo_tasks_2026-03-09_14-30-00/)
scheduler-harness --archive --task-source demo_tasks.md

# List all available archives
scheduler-harness --list-archives

# Restore from a specific archive
scheduler-harness --restore demo_tasks_2026-03-09_14-30-00
```
