# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## General Workflow

* When I ask a question, answer the question.
* When I instruct you to change something:
  * STOP. Before anything else — including forming a plan — run ALL before instructions from CLAUDE.local.md. This is not a checkbox. It requires genuine critical thinking on every dimension listed there. Only proceed to (A) or (B) after completing this.
  * (A) For minor change of a few lines
    * STOP. Before anything else, run ALL instructions in "Minor Change Before instructions" in CLAUDE.local.md. Only proceed after that.
    * Change it if still necessary and run unit tests
  * (B) All other changes:
    * first create a plan and then come back to me.
      * Prefer minimal solutions that keep the system as consistent and reliable as possible.
      * Check the relevant requirements in `requirements/` and flag any conflict or gap before planning.
      * Check that `config.example.yaml` and `tests/acceptance/fixtures/config.yaml.template` are consistent with the requirements being changed — flag any key that is mentioned in requirements but missing from the example, or any default that contradicts the spec.
    * After I give the GO, implement the change.
    * Update tests and documentation automatically if necessary.
    * If the change affects behaviour described in `requirements/`, update the relevant requirements file.
    * Run unit tests with branch coverage automatically: `python -m pytest --cov=. --cov-branch --cov-report=term-missing -q`
    * Only when the current iteration has made a feature complete and all unit tests passed, execute a functional system test. To do that, execute the tool with as few test documents as possible, check output pdf and compare the csv output to the test_data/journal_testbase.csv
      * Fix all errors found in the test.
    * Evaluate our current development process and suggest improvements for the next round.
    * Make the one refactoring suggestion that has most impact with the most minimal change. What would make the system more maintainable and understandable for new developers?
    * After every completed task, do not start the next before completing this:
    ** Run the respective steps ("after instructions") in @CLAUDE.local.md

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

## Code Style

Baseline: [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).

The following project-specific rules override or extend it:

* **No comments unless the WHY is non-obvious** — hidden constraints, subtle invariants, workarounds for specific bugs, or behaviour that would surprise a reader. Never describe what the code does; well-named identifiers do that. Never reference the current task or callers.
* **No premature abstraction** — three similar lines is better than an early helper. Only abstract when a third real use case exists.
* **No over-splitting** — a function that stays at one abstraction level is clean even if it is 30 lines. Split at I/O boundaries (API calls, file access), not at arbitrary length thresholds.
* **No error handling for impossible cases** — trust internal code and framework guarantees. Validate only at system boundaries (user input, external APIs, LLM responses).
* **No side effects on shared state** — functions should return values, not mutate arguments or module-level state as a by-product.
* **Apply opportunistically, not in dedicated passes** — clean up when you touch a function for another reason. New code is held to this standard from the start; existing code is improved in place.

## Python Dependencies

Dependencies are managed via `requirements.txt`. After adding a package, rebuild the image or install it directly inside a running container:

```bash
pip install -r requirements.txt
```
