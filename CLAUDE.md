# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## General Workflow

* When I ask a question, answer the question.
* When I instruct you to change something:
  * For minor change of a few lines, just change it and run unit tests.
  * All other changes:
    * first create a plan and then come back to me.
      * Prefer minimal solutions that keep the system as consistent and reliable as possible.
    * After I give the GO, implement the change.
    * Update tests and documentation automatically if necessary.
    * Run unit tests automatically.
    * Only when the current iteration has made a feature complete and all unit tests passed, execute a functional system test. To do that, execute the tool with as few test documents as possible, check output pdf and compare the csv output to the test_data/journal_testbase.csv
      * Fix all errors found in the test.
    * Evaluate our current development process and suggest improvements for the next round.
    * Make the one refactoring suggestion that has most impact with the most minimal change. What would make the system more maintainable and understandable for new developers?

## Development Environment

This project runs inside a Docker container (Python 3.12 + Node.js + Claude Code CLI). All development happens inside the container.

**Build and start the container (run from the repo root on the host):**

```bash
docker build -t fibutool-dev .

# Windows (Git Bash / MSYS2):
MSYS_NO_PATHCONV=1 docker run -it -v "$(pwd -W)":/workspace -w /workspace --name fibutool-dev fibutool-dev

# Linux / macOS:
docker run -it -v "$(pwd)":/workspace -w /workspace --name fibutool-dev fibutool-dev
```

The host repo is bind-mounted to `/workspace` inside the container, so edits on either side are reflected immediately.

## Python Dependencies

Dependencies are managed via `requirements.txt`. After adding a package, rebuild the image or install it directly inside a running container:

```bash
pip install -r requirements.txt
```
