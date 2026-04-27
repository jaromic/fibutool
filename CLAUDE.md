# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
