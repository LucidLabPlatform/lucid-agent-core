# LUCID Agent Core - /home/lucid Refactor Verification Checklist

## Pre-Installation Verification

- [ ] Raspberry Pi or similar Linux system with systemd
- [ ] Python 3.11+ installed
- [ ] User `lucid` exists (or will be created by installer)
- [ ] Internet connectivity for downloading wheel from GitHub releases

## Clean Installation Test

### 1a. Install Service from GitHub Release (Default)

```bash
# Install the package
pip install lucid-agent-core

# Run installer (as root)
sudo lucid-agent-core install-service
```

**Expected Output:**
```
User 'lucid' already exists
Creating virtual environment using /usr/bin/python3.11...
Virtual environment created: /home/lucid/lucid-agent-core/venv
Installing from GitHub release: https://github.com/...
✓ lucid-agent-core installed and enabled successfully!
```

### 1b. Install Service from Local Wheel (Alternative)

This is useful for development, CI/CD, or offline installations.

```bash
# Build the wheel locally (if developing)
python -m build

# Or download a pre-built wheel
# wget https://github.com/.../lucid_agent_core-X.Y.Z-py3-none-any.whl

# Install using local wheel with --wheel flag
sudo lucid-agent-core install-service --wheel dist/lucid_agent_core-1.0.0-py3-none-any.whl

# Alternative: use environment variable
export LUCID_AGENT_CORE_WHEEL=/path/to/lucid_agent_core-1.0.0-py3-none-any.whl
sudo -E lucid-agent-core install-service
```

**Expected Output:**
```
User 'lucid' already exists (or "Creating user 'lucid'..." if new)
Creating virtual environment...
Installing from local wheel: /path/to/lucid_agent_core-1.0.0-py3-none-any.whl
Installation successful: /home/lucid/lucid-agent-core/venv/bin/lucid-agent-core
✓ lucid-agent-core installed and enabled successfully!
```

**Verify:**
- [ ] Directory `/home/lucid/lucid-agent-core` exists and owned by `lucid:lucid`
- [ ] Virtual environment created at `/home/lucid/lucid-agent-core/venv`
- [ ] Configuration file exists at `/home/lucid/lucid-agent-core/agent-core.env`
- [ ] Systemd unit installed at `/etc/systemd/system/lucid-agent-core.service`
- [ ] Service enabled: `systemctl is-enabled lucid-agent-core`
- [ ] User `lucid` exists with home `/home/lucid` and shell `/bin/bash`

```bash
# Verify directory structure
ls -la /home/lucid/lucid-agent-core/
# Expected: venv/, data/, logs/, run/, agent-core.env

# Verify ownership
stat -c '%U:%G' /home/lucid/lucid-agent-core
# Expected: lucid:lucid

# Verify venv
/home/lucid/lucid-agent-core/venv/bin/python --version
# Expected: Python 3.11.x or higher

# Verify CLI installed
/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core --version
# Expected: version string

# Verify user exists with correct settings
id lucid
# Expected: uid=... gid=... groups=...

getent passwd lucid
# Expected: lucid:x:...:...::/home/lucid:/bin/bash
```

### 2. Configure Environment

```bash
# Edit configuration
sudo -u lucid nano /home/lucid/lucid-agent-core/agent-core.env
```

**Update with your MQTT credentials:**
```
MQTT_HOST=your.mqtt.broker
MQTT_PORT=1883
AGENT_USERNAME=your-agent-id
AGENT_PASSWORD=your-secure-password
AGENT_HEARTBEAT=30
```

**Verify:**
- [ ] Configuration file has correct permissions (640)
- [ ] File owned by `lucid:lucid`

### 3. Start Service

```bash
# Start the service
sudo systemctl start lucid-agent-core

# Check status
sudo systemctl status lucid-agent-core
```

**Verify:**
- [ ] Service is `active (running)`
- [ ] No error messages in status output
- [ ] Log shows successful MQTT connection

```bash
# Check logs
sudo journalctl -u lucid-agent-core -n 50 --no-pager

# Expected in logs:
# - "LUCID Agent Core"
# - "Version: X.Y.Z"
# - "Runtime config loaded"
# - "Agent running"
```

### 4. Verify Runtime Files

```bash
# Check that data directory was created
ls -la /home/lucid/lucid-agent-core/data/

# Check logs directory
ls -la /home/lucid/lucid-agent-core/logs/

# Check runtime directory
ls -la /home/lucid/lucid-agent-core/run/
```

**Verify:**
- [ ] All directories exist
- [ ] All owned by `lucid:lucid`
- [ ] Correct permissions (750 for data/logs/run)

## Component Installation Test

### 5. Install Dummy Component

Publish MQTT command to install component:

```json
{
  "request_id": "test-install-1",
  "component_id": "dummy",
  "version": "0.0.1",
  "entrypoint": "lucid_component_dummy.component:DummyComponent",
  "source": {
    "type": "github_release",
    "owner": "LucidLabPlatform",
    "repo": "lucid-component-dummy",
    "tag": "v0.0.1",
    "asset": "lucid_component_dummy-0.0.1-py3-none-any.whl",
    "sha256": "be40ca30b95feae58d866b0cbd6979e116d22bbb7d9b0afeafe6027b820401a8"
  }
}
```

**Publish to topic:** `lucid/agents/{agent_id}/test/core/cmd/install_component`

**Verify:**
- [ ] Component wheel downloaded
- [ ] Installed into `/home/lucid/lucid-agent-core/venv`
- [ ] Registry updated at `/home/lucid/lucid-agent-core/data/components_registry.json`
- [ ] Install result published to MQTT
- [ ] Service restarted automatically

```bash
# Check registry
sudo cat /home/lucid/lucid-agent-core/data/components_registry.json | jq .

# Expected: entry for "dummy" component with version, repo, sha256

# Check installed packages
/home/lucid/lucid-agent-core/venv/bin/pip list | grep dummy
# Expected: lucid-component-dummy  0.0.1

# Check service restarted
sudo journalctl -u lucid-agent-core -n 20 --no-pager
# Expected: recent restart messages
```

## Component Uninstallation Test

### 6. Uninstall Dummy Component

Publish MQTT command:

```json
{
  "request_id": "test-uninstall-1",
  "component_id": "dummy"
}
```

**Publish to topic:** `lucid/agents/{agent_id}/test/core/cmd/uninstall_component`

**Verify:**
- [ ] Component uninstalled from venv
- [ ] Registry entry removed
- [ ] Uninstall result published to MQTT
- [ ] Service restarted automatically

```bash
# Check registry
sudo cat /home/lucid/lucid-agent-core/data/components_registry.json | jq .
# Expected: no "dummy" entry

# Check pip list
/home/lucid/lucid-agent-core/venv/bin/pip list | grep dummy
# Expected: no output (component removed)
```

## Path Validation

### 7. Verify No Old Paths in Use

```bash
# Check that service doesn't reference /opt or /var/lib
sudo systemctl cat lucid-agent-core.service | grep -E '/opt|/var/lib|/var/log|/etc/lucid'
# Expected: no matches (except maybe in comments)

# Verify WorkingDirectory
sudo systemctl cat lucid-agent-core.service | grep WorkingDirectory
# Expected: WorkingDirectory=/home/lucid/lucid-agent-core

# Verify ExecStart
sudo systemctl cat lucid-agent-core.service | grep ExecStart
# Expected: ExecStart=/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core run

# Verify EnvironmentFile
sudo systemctl cat lucid-agent-core.service | grep EnvironmentFile
# Expected: EnvironmentFile=/home/lucid/lucid-agent-core/agent-core.env
```

### 8. Verify File Permissions and Ownership

```bash
# Base directory
stat -c '%a %U:%G' /home/lucid/lucid-agent-core
# Expected: 755 lucid:lucid

# Data directory (sensitive)
stat -c '%a %U:%G' /home/lucid/lucid-agent-core/data
# Expected: 750 lucid:lucid

# Logs directory
stat -c '%a %U:%G' /home/lucid/lucid-agent-core/logs
# Expected: 750 lucid:lucid

# Runtime directory
stat -c '%a %U:%G' /home/lucid/lucid-agent-core/run
# Expected: 750 lucid:lucid

# Config file
stat -c '%a %U:%G' /home/lucid/lucid-agent-core/agent-core.env
# Expected: 640 lucid:lucid

# Registry file (if exists)
stat -c '%a %U:%G' /home/lucid/lucid-agent-core/data/components_registry.json
# Expected: 640 lucid:lucid (created by service with default umask)
```

## Cleanup

### 9. Service Stop and Disable

```bash
# Stop service
sudo systemctl stop lucid-agent-core

# Disable service
sudo systemctl disable lucid-agent-core

# Remove service file
sudo rm /etc/systemd/system/lucid-agent-core.service
sudo systemctl daemon-reload
```

### 10. Remove Installation (Optional)

```bash
# Remove all files under /home/lucid/lucid-agent-core
sudo rm -rf /home/lucid/lucid-agent-core
```

## Summary Checklist

### Installation
- [ ] Service installs successfully
- [ ] All directories created under `/home/lucid/lucid-agent-core`
- [ ] No files created in `/opt`, `/var/lib`, `/var/log`, or `/etc/lucid`
- [ ] Correct ownership (`lucid:lucid`)
- [ ] Correct permissions

### Runtime
- [ ] Service starts and connects to MQTT
- [ ] Configuration loaded from `/home/lucid/lucid-agent-core/agent-core.env`
- [ ] Registry and config stored in `/home/lucid/lucid-agent-core/data/`
- [ ] No errors in logs

### Component Management
- [ ] Component installation works
- [ ] Registry updated correctly
- [ ] Component uninstallation works
- [ ] Registry cleaned up

### Security
- [ ] Service runs as `lucid` user
- [ ] Systemd hardening active (NoNewPrivileges, ProtectSystem, etc.)
- [ ] Sensitive files have restrictive permissions (640/750)

## Issues & Troubleshooting

### Service Won't Start
- Check `/home/lucid/lucid-agent-core/agent-core.env` is configured correctly
- Check MQTT credentials
- Check journalctl logs: `sudo journalctl -u lucid-agent-core -xe`

### Permission Denied Errors
- Verify all files under `/home/lucid/lucid-agent-core` owned by `lucid:lucid`
- Run: `sudo chown -R lucid:lucid /home/lucid/lucid-agent-core`

### Component Installation Fails
- Check internet connectivity
- Verify SHA256 in install command matches actual wheel
- Check pip path exists: `/home/lucid/lucid-agent-core/venv/bin/pip`
- Check disk space: `df -h /home/lucid`
