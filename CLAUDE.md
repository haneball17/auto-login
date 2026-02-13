# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows 11 game automation system for DNF Taiwan that automates:
- Launcher startup and login button detection
- Web-based authentication via Playwright (headless browser automation)
- Game client operations (channel selection, character selection, in-game check-in, logout)
- Scheduled execution with two daily cycles (1.5-hour minimum intervals)
- Multi-account rotation with retry logic

## Common Commands

### Running the Application
```bash
# Default: scheduled mode (runs on configured schedule)
poetry run python -m src.main

# Launcher only: start launcher and click start button
poetry run python -m src.main --launcher-only

# Launcher + web login (keeps browser open for debugging)
poetry run python -m src.main --launcher-web-login

# Once mode: execute all accounts once sequentially
poetry run python -m src.main --once

# Launch GUI configuration interface
poetry run python -m src.ui

# Skip path/anchor validation (useful for development)
poetry run python -m src.main --skip-path-check
```

### Testing
```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_config.py

# Run with verbose output
poetry run pytest -v
```

### Dependencies
```bash
# Install dependencies
poetry install

# Add a dependency
poetry add <package>

# Update dependencies
poetry update
```

## Architecture

### Core Execution Flow

The main entry point is `src/main.py`, which routes to one of four execution modes:
1. **Scheduled mode** → `src/scheduler.py` - APScheduler-based periodic execution
2. **Launcher-only** → `src/runner.py:run_launcher_flow()` - Minimal launcher interaction
3. **Launcher + web-login** → `src/runner.py:run_launcher_web_login_flow()` - Launcher + authentication
4. **Once mode** → `src/runner.py:run_all_accounts_once()` - Full sequential execution

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `config.py` | Pydantic-based configuration loading from `config.yaml` and `.env` |
| `runner.py` | Core automation logic; manages account flow, retries, and state transitions |
| `scheduler.py` | APScheduler wrapper with file locking and auto-restart |
| `web_login.py` | Playwright headless browser automation for authentication |
| `ui_ops.py` | OpenCV template matching + PyAutoGUI for UI interaction |
| `ocr_ops.py` | cnocr-based Chinese text recognition for validation/error detection |
| `process_ops.py` | psutil-based process/window lifecycle management |
| `evidence.py` | Screenshot and context capture on failures |
| `ui.py` | PyQt6 GUI for configuration management and log viewing |

### Configuration System

Configuration is loaded in layers:
1. **`config.yaml`** - Main configuration (schedule, accounts, flow control, evidence settings)
2. **`.env`** - Machine-specific values (e.g., `LAUNCHER__EXE_PATH`)
3. **`anchors/*/roi.json`** - ROI coordinates for different resolutions and scenes

The `config.py` module uses Pydantic for type-safe validation and supports:
- Multiple schedule modes (`random_window`, `fixed_times`)
- Account pool with enabled/disabled states and retry limits
- Anchor path validation with resolution fallbacks
- Flow control parameters (timeouts, retry counts)

### Template Matching System

UI detection uses OpenCV template matching with:
- **Scene-based organization**: `launcher_start_enabled`, `channel_select`, `character_select`, `in_game`
- **Multi-resolution support**: 640x480, 960x720, 1280x960, 1920x1440
- **ROI definitions**: JSON files define click coordinates and OCR regions
- **Color validation**: RGB-based rules for additional UI state verification

Template images are stored as PNG files in `anchors/<scene>/` with corresponding `roi.json` files.

### Error Handling & Evidence

The `evidence.py` module automatically captures debugging context on failures:
- Screenshots saved to timestamped directories in `evidence/`
- OCR text extraction for error messages
- Configurable retention policy (days to keep)

All blocking operations use timeouts and retry mechanisms defined in `config.yaml`.

## Important Notes

### Account Flow
Each account flows through these stages (configurable via `config.yaml`):
1. Launcher startup → wait for start button → click
2. Web login (URL capture from browser → Playwright authentication)
3. Channel selection → click specific channel
4. Character selection → select character
5. In-game presence verification → logout

### File Locking
The scheduler uses file locking (`scheduler.lock`) to prevent concurrent executions. A `stop.flag` file can be created to gracefully stop the scheduler.

### Browser Requirements
Web login requires Chrome or Edge installed. The system monitors clipboard for login URLs from the launcher process.

### Windows-Specific
This project uses `pywin32` for window management and is designed for Windows 11. Some operations may not work on other platforms.
