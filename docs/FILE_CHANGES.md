# LUCID Agent Core - File Changes Summary

## Files Created (5 new files)

### Source Files
1. **`src/lucid_agent_core/paths.py`**
   - Central path configuration module
   - 192 lines
   - Provides `build_paths()`, `ensure_dirs()`, `get_paths()`, `set_paths()`, `reset_paths()`
   - Base directory: `/home/lucid/lucid-agent-core`

### Test Files
2. **`tests/unit/test_paths.py`**
   - Comprehensive tests for paths module
   - 108 lines
   - Tests defaults, custom paths, env var override, singleton, directory creation

### Documentation
3. **`docs/VERIFICATION_CHECKLIST.md`**
   - Step-by-step verification checklist for Raspberry Pi deployment
   - 300+ lines
   - Installation, runtime, component ops, troubleshooting

4. **`docs/HOME_LUCID_REFACTOR.md`**
   - Complete refactor documentation
   - 300+ lines
   - Architecture, design decisions, security considerations

5. **`docs/FILE_CHANGES.md`** (this file)
   - Summary of all file changes

## Files Modified (10 files)

### Core Module Changes

1. **`src/lucid_agent_core/components/registry.py`**
   - **Lines changed**: 8 lines (imports + function updates)
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths`
     - Removed: `REGISTRY_PATH` and `LOCK_PATH` constants
     - Updated: `load_registry()` to use `get_paths().registry_path`
     - Updated: `write_registry()` to use `get_paths().registry_path` and `get_paths().registry_lock_path`
   - **Old path**: `/var/lib/lucid/components.json`
   - **New path**: `/home/lucid/lucid-agent-core/data/components_registry.json`

2. **`src/lucid_agent_core/core/config_store.py`**
   - **Lines changed**: ~15 lines
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths`
     - Updated: `__init__()` to accept optional path, defaults to `get_paths().config_path`
     - Updated: `save()` to use `get_paths().config_lock_path`
     - Updated docstrings
   - **Old path**: `/var/lib/lucid/core_config.json`
   - **New path**: `/home/lucid/lucid-agent-core/data/core_config.json`

3. **`src/lucid_agent_core/core/component_installer.py`**
   - **Lines changed**: 3 lines
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths`
     - Removed: `PIP_PATH` constant
     - Updated: `_pip_install()` to use `get_paths().pip_path`
   - **Old path**: `/opt/lucid/agent-core/venv/bin/pip`
   - **New path**: `/home/lucid/lucid-agent-core/venv/bin/pip`

4. **`src/lucid_agent_core/core/component_uninstaller.py`**
   - **Lines changed**: 5 lines
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths`
     - Removed: `PIP_PATH` constant
     - Updated: `_pip_uninstall()` to use `get_paths().pip_path`
   - **Old path**: `/opt/lucid/agent-core/venv/bin/pip`
   - **New path**: `/home/lucid/lucid-agent-core/venv/bin/pip`

5. **`src/lucid_agent_core/core/restart.py`**
   - **Lines changed**: ~12 lines
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths`
     - Removed: `_SENTINEL_PATH` constant
     - Updated: `request_systemd_restart()` to use `get_paths().restart_sentinel_path`
   - **Old path**: `/var/lib/lucid/restart.requested`
   - **New path**: `/home/lucid/lucid-agent-core/run/restart.requested`

6. **`src/lucid_agent_core/config.py`**
   - **Lines changed**: 2 lines
   - **Changes**:
     - Updated: `_env_paths()` first yield to `/home/lucid/lucid-agent-core/agent-core.env`
     - Updated: Docstring to reflect new path
   - **Old path**: `/etc/lucid/agent-core.env`
   - **New path**: `/home/lucid/lucid-agent-core/agent-core.env`

7. **`src/lucid_agent_core/main.py`**
   - **Lines changed**: ~10 lines
   - **Changes**:
     - Added: `from lucid_agent_core.paths import get_paths, ensure_dirs`
     - Updated: `run_agent()` to call `ensure_dirs()` on startup
   - **Behavior**: Creates directory structure on first run

8. **`src/lucid_agent_core/installer.py`**
   - **Complete rewrite**: 203 lines
   - **Changes**:
     - All path constants updated to use `/home/lucid/lucid-agent-core`
     - Removed: `ENV_DIR`, `OPT_DIR`, `VAR_LIB`, `VAR_LOG` paths
     - Added: `BASE_DIR`, updated all derived paths
     - Updated: `_ensure_dirs()` to create subdirectories under base
     - Updated: `_ensure_env_file()` to use new location
     - Updated: All ownership commands to use base directory
     - Updated: Print output to show new paths
   - **Old paths**:
     - `/etc/lucid/agent-core.env`
     - `/opt/lucid/agent-core/venv`
     - `/var/lib/lucid`
     - `/var/log/lucid`
   - **New paths**: All under `/home/lucid/lucid-agent-core/`

### Systemd and Config

9. **`src/lucid_agent_core/systemd/lucid-agent-core.service`**
   - **Lines changed**: 5 lines
   - **Changes**:
     - `WorkingDirectory`: `/var/lib/lucid` → `/home/lucid/lucid-agent-core`
     - `EnvironmentFile`: `/etc/lucid/agent-core.env` → `/home/lucid/lucid-agent-core/agent-core.env`
     - `ExecStart`: `/opt/lucid/agent-core/venv/bin/...` → `/home/lucid/lucid-agent-core/venv/bin/...`
     - `ProtectHome`: `true` → `false` (required to access /home/lucid)
     - `ReadWritePaths`: `/var/lib/lucid /var/log/lucid` → `/home/lucid/lucid-agent-core`

10. **`src/lucid_agent_core/env.example`**
    - **Lines changed**: 1 line
    - **Changes**:
      - Updated location comment: `/etc/lucid/agent-core.env` → `/home/lucid/lucid-agent-core/agent-core.env`

## Files NOT Modified (Existing Tests)

The following test files were **not modified** because they already use proper mocking and don't have hardcoded paths:
- `tests/unit/test_component_installer.py` ✓
- `tests/unit/test_config.py` ✓
- `tests/unit/test_registry.py` ✓
- `tests/unit/test_loader.py` ✓
- `tests/unit/test_installer.py` ✓
- All other existing test files ✓

## Statistics

### Code Changes
- **New files**: 5 (1 source, 1 test, 3 docs)
- **Modified files**: 10 (8 source, 1 systemd, 1 config)
- **Unchanged test files**: All existing tests preserved
- **Total new lines**: ~800 lines (code + docs)
- **Total modified lines**: ~60 lines

### Path Migrations
- **Registry**: `/var/lib/lucid/components.json` → `/home/lucid/lucid-agent-core/data/components_registry.json`
- **Config**: `/var/lib/lucid/core_config.json` → `/home/lucid/lucid-agent-core/data/core_config.json`
- **Pip**: `/opt/lucid/agent-core/venv/bin/pip` → `/home/lucid/lucid-agent-core/venv/bin/pip`
- **Sentinel**: `/var/lib/lucid/restart.requested` → `/home/lucid/lucid-agent-core/run/restart.requested`
- **Env file**: `/etc/lucid/agent-core.env` → `/home/lucid/lucid-agent-core/agent-core.env`
- **Venv**: `/opt/lucid/agent-core/venv` → `/home/lucid/lucid-agent-core/venv`

## Git Commands

Stage all changes:
```bash
git add src/lucid_agent_core/paths.py
git add src/lucid_agent_core/components/registry.py
git add src/lucid_agent_core/core/config_store.py
git add src/lucid_agent_core/core/component_installer.py
git add src/lucid_agent_core/core/component_uninstaller.py
git add src/lucid_agent_core/core/restart.py
git add src/lucid_agent_core/config.py
git add src/lucid_agent_core/main.py
git add src/lucid_agent_core/installer.py
git add src/lucid_agent_core/systemd/lucid-agent-core.service
git add src/lucid_agent_core/env.example
git add tests/unit/test_paths.py
git add docs/VERIFICATION_CHECKLIST.md
git add docs/HOME_LUCID_REFACTOR.md
git add docs/FILE_CHANGES.md
```

Commit:
```bash
git commit -m "Refactor: Move all paths to /home/lucid/lucid-agent-core

- Created central paths.py module for path management
- Updated all modules to use paths module instead of hardcoded paths
- Refactored installer for new base directory
- Updated systemd service file
- Added comprehensive tests and documentation

BREAKING CHANGE: All files now under /home/lucid/lucid-agent-core
For new installations only (no migration from old paths)"
```

## Verification Commands

```bash
# Check for any remaining old paths in code (should find none)
rg -i '/opt/lucid|/var/lib/lucid|/var/log/lucid|/etc/lucid' src/

# Run linter
ruff check src/

# Run tests (when pytest is available)
pytest tests/unit/ -v
```

## Documentation Cross-References

- **Architecture**: See `docs/HOME_LUCID_REFACTOR.md`
- **Testing**: See `docs/VERIFICATION_CHECKLIST.md`
- **Paths**: See `src/lucid_agent_core/paths.py` docstrings
