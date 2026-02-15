# LUCID Agent Core - /home/lucid Refactor Summary

## Overview

Successfully refactored `lucid-agent-core` to use `/home/lucid/lucid-agent-core` as the base directory for all runtime state, configuration, logs, and virtual environment. No system-level directories (`/opt`, `/var/lib`, `/var/log`, `/etc/lucid`) are used.

## New Directory Structure

```
/home/lucid/lucid-agent-core/
├── venv/                           # Python virtual environment
│   └── bin/
│       ├── pip
│       ├── python
│       └── lucid-agent-core       # CLI executable
├── data/                           # Persistent data (750)
│   ├── components_registry.json   # Component registry
│   ├── core_config.json           # Runtime configuration
│   └── *.lock                     # Lock files for atomic writes
├── logs/                           # Application logs (750)
│   └── agent-core.log
├── run/                            # Runtime state (750)
│   └── restart.requested          # Restart sentinel
└── agent-core.env                 # Environment configuration (640)
```

## Modified Files

### Core Module - New Files

1. **`src/lucid_agent_core/paths.py`** (NEW)
   - Central path configuration module
   - `build_paths()`: Creates path structure from base directory
   - `ensure_dirs()`: Creates all required directories with correct permissions
   - `get_paths()`: Singleton accessor for global paths
   - Environment variable override: `LUCID_AGENT_BASE_DIR`

### Core Module - Modified Files

2. **`src/lucid_agent_core/components/registry.py`**
   - Removed hardcoded `REGISTRY_PATH` and `LOCK_PATH`
   - Now uses `get_paths().registry_path` and `get_paths().registry_lock_path`
   - Path: `/home/lucid/lucid-agent-core/data/components_registry.json`

3. **`src/lucid_agent_core/core/config_store.py`**
   - Updated default path from `/var/lib/lucid/core_config.json` to paths module
   - Constructor accepts optional path (defaults to `get_paths().config_path`)
   - Lock file from `get_paths().config_lock_path`
   - Path: `/home/lucid/lucid-agent-core/data/core_config.json`

4. **`src/lucid_agent_core/core/component_installer.py`**
   - Removed hardcoded `PIP_PATH`
   - Now uses `get_paths().pip_path`
   - Path: `/home/lucid/lucid-agent-core/venv/bin/pip`

5. **`src/lucid_agent_core/core/component_uninstaller.py`**
   - Removed hardcoded `PIP_PATH`
   - Now uses `get_paths().pip_path`
   - Path: `/home/lucid/lucid-agent-core/venv/bin/pip`

6. **`src/lucid_agent_core/core/restart.py`**
   - Removed hardcoded `_SENTINEL_PATH`
   - Now uses `get_paths().restart_sentinel_path`
   - Path: `/home/lucid/lucid-agent-core/run/restart.requested`

7. **`src/lucid_agent_core/config.py`**
   - Updated `_env_paths()` to look for env file at new location
   - Old: `/etc/lucid/agent-core.env`
   - New: `/home/lucid/lucid-agent-core/agent-core.env`

8. **`src/lucid_agent_core/main.py`**
   - Added directory creation logic
   - Calls `ensure_dirs()` to create directory structure on startup

9. **`src/lucid_agent_core/installer.py`** (REWRITTEN)
    - Completely refactored for new base directory
    - Creates `/home/lucid/lucid-agent-core` instead of `/opt/lucid/agent-core`
    - Creates all subdirectories (venv, data, logs, run)
    - Environment file at `/home/lucid/lucid-agent-core/agent-core.env`
    - No references to `/opt`, `/var/lib`, `/var/log`, or `/etc/lucid`
    - Everything owned by `lucid:lucid`

### Systemd and Configuration

10. **`src/lucid_agent_core/systemd/lucid-agent-core.service`** (UPDATED)
    - `WorkingDirectory`: `/home/lucid/lucid-agent-core`
    - `EnvironmentFile`: `/home/lucid/lucid-agent-core/agent-core.env`
    - `ExecStart`: `/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core run`
    - `ReadWritePaths`: `/home/lucid/lucid-agent-core`
    - `ProtectHome`: `false` (required to access /home/lucid)

11. **`src/lucid_agent_core/env.example`** (UPDATED)
    - Updated documentation to reflect new location
    - Location: `/home/lucid/lucid-agent-core/agent-core.env`

### Tests - New Files

12. **`tests/unit/test_paths.py`** (NEW)
    - Tests for paths module
    - Validates default paths
    - Tests custom base directory
    - Tests environment variable override
    - Tests singleton behavior
    - Tests directory creation

### Documentation

13. **`docs/VERIFICATION_CHECKLIST.md`** (NEW)
    - Step-by-step verification checklist for Raspberry Pi deployment
    - Installation verification steps
    - Component install/uninstall tests
    - Permission and ownership verification
    - Troubleshooting guide

14. **`docs/HOME_LUCID_REFACTOR.md`** (this file)
    - Complete refactor documentation

## Key Design Decisions

### 1. Central Path Module
All paths derived from a single `paths.py` module. This provides:
- Single source of truth
- Easy testing (can override base directory)
- Consistent path structure
- No hardcoded paths scattered across codebase

### 2. Atomic Writes Preserved
All atomic write guarantees maintained:
- Temp file + fsync + rename pattern unchanged
- Lock files for concurrent access protection
- Directory fsync for durability

### 3. Service User
Service runs as `lucid` user (not root):
- All files under `/home/lucid` owned by `lucid:lucid`
- Base directory: 755 permissions
- Data/logs/run: 750 permissions (sensitive data)
- Config file: 640 permissions (contains credentials)

### 4. Systemd Hardening
Systemd hardening maintained:
- `NoNewPrivileges=true`
- `PrivateTmp=true`
- `ProtectSystem=strict`
- `ProtectHome=false` (needed for /home/lucid access)
- `ReadWritePaths=/home/lucid/lucid-agent-core`
- `MemoryDenyWriteExecute=true`
- Other security restrictions preserved

## Installation Flow

1. **Install Package**
   ```bash
   pip install lucid-agent-core
   sudo lucid-agent-core install-service
   ```

2. **Installer Actions**
   - Creates `lucid` user if not exists
   - Creates `/home/lucid/lucid-agent-core/` with subdirectories
   - Creates venv at `/home/lucid/lucid-agent-core/venv`
   - Installs package into venv
   - Copies `env.example` to `agent-core.env`
   - Installs systemd unit
   - Enables service
   - Sets correct ownership and permissions

3. **Configuration**
   ```bash
   sudo -u lucid nano /home/lucid/lucid-agent-core/agent-core.env
   ```

4. **Start Service**
   ```bash
   sudo systemctl start lucid-agent-core
   ```

5. **First Run**
   - Directories created if missing
   - MQTT connection established
   - Components loaded

## Testing Strategy

### Unit Tests
- All existing tests preserved
- Tests use mocking (no hardcoded paths)
- New tests added for paths module

### Integration Tests
- Verification checklist provides manual test procedures
- Covers clean install, component operations
- Includes permission and ownership checks
- Troubleshooting guidance

## Security Considerations

### Permissions
- Base: `755` (world-readable, only lucid can write)
- Data: `750` (only lucid and group can read)
- Logs: `750` (only lucid and group can read)
- Run: `750` (only lucid and group can read)
- Env file: `640` (only lucid can read, contains credentials)

### Systemd Isolation
- Runs as unprivileged user
- Strict system protection
- Private /tmp
- No privilege escalation
- Memory execute protection
- Limited filesystem access

### Attack Surface
- No setuid/setgid binaries
- No world-writable files
- No unnecessary system access
- All files under single user home directory

## Benefits

1. **Simplified Deployment**
   - Single base directory
   - No system-level directories to manage
   - Easy to backup/restore (just tar /home/lucid)

2. **Better Security**
   - Everything under user home
   - No mixed ownership across system
   - Systemd hardening fully effective

3. **Easier Development**
   - Can run without root privileges
   - Can override base directory for testing
   - Clear separation of concerns

4. **Better Maintenance**
   - Single location to check for issues
   - Clear ownership model

## Known Limitations

1. **ProtectHome Relaxed**
   - Must set `ProtectHome=false` to access `/home/lucid`
   - Trade-off for simpler deployment

2. **Single User**
   - All components share same venv
   - No per-user isolation (not a use case for this system)

## Future Enhancements

1. **Configurable Base Directory**
   - Already supported via `LUCID_AGENT_BASE_DIR` env var
   - Could add to installer CLI arguments

2. **Multi-Instance Support**
   - Could support multiple agents on same machine
   - Each with its own base directory

## Conclusion

The refactor successfully moves all runtime state to `/home/lucid/lucid-agent-core` while preserving:
- Atomic write guarantees
- Security hardening
- Component isolation

The codebase is now cleaner with a single source of truth for paths, making it easier to maintain and test.
