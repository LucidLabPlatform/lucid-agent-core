# LUCID Agent Core - Local Wheel Installation Smoke Tests

## Purpose

Test installation from local wheel files for:
- Development workflows
- CI/CD pipelines
- Offline/air-gapped installations
- Custom builds

## Prerequisites

- Root/sudo access
- Python 3.11+ installed
- Built wheel file available

## Test 1: Fresh Install with --wheel Flag

### Steps

```bash
# Build wheel (if developing)
cd /path/to/lucid-agent-core
python -m build

# Or use pre-built wheel
WHEEL_PATH="dist/lucid_agent_core-1.0.0-py3-none-any.whl"

# Install from local wheel
sudo lucid-agent-core install-service --wheel "$WHEEL_PATH"
```

### Expected Output

```
User 'lucid' already exists
Creating virtual environment using /usr/bin/python3.11...
Virtual environment created: /home/lucid/lucid-agent-core/venv
Installing from local wheel: dist/lucid_agent_core-1.0.0-py3-none-any.whl
Installation successful: /home/lucid/lucid-agent-core/venv/bin/lucid-agent-core
Systemd unit installed: /etc/systemd/system/lucid-agent-core.service
Service enabled: lucid-agent-core

============================================================
✓ lucid-agent-core installed and enabled successfully!
============================================================
Base directory: /home/lucid/lucid-agent-core
Configuration: /home/lucid/lucid-agent-core/agent-core.env

Next steps:
1. Edit /home/lucid/lucid-agent-core/agent-core.env with your MQTT credentials
2. Start the service: sudo systemctl start lucid-agent-core
3. Check status: sudo systemctl status lucid-agent-core
============================================================
```

### Verification

```bash
# Verify installation
/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core --version

# Verify user
id lucid
getent passwd lucid | grep "/bin/bash"

# Verify directory structure
ls -la /home/lucid/lucid-agent-core/
# Expected: venv/, data/, logs/, run/, agent-core.env

# Verify ownership
stat -c '%U:%G' /home/lucid/lucid-agent-core
# Expected: lucid:lucid

# Verify service
systemctl is-enabled lucid-agent-core
# Expected: enabled
```

**Pass Criteria:**
- [x] Installation completes without errors
- [x] CLI executable works and shows correct version
- [x] User `lucid` exists with `/home/lucid` and `/bin/bash`
- [x] All directories created with correct ownership
- [x] Service enabled

---

## Test 2: Install with Environment Variable

### Steps

```bash
# Set environment variable
export LUCID_AGENT_CORE_WHEEL="/path/to/lucid_agent_core-1.0.0-py3-none-any.whl"

# Install (note: use -E to preserve environment)
sudo -E lucid-agent-core install-service
```

### Expected Output

```
Using wheel from LUCID_AGENT_CORE_WHEEL: /path/to/lucid_agent_core-1.0.0-py3-none-any.whl
User 'lucid' already exists
...
✓ lucid-agent-core installed and enabled successfully!
```

### Verification

```bash
# Verify same as Test 1
/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core --version
```

**Pass Criteria:**
- [x] Environment variable is recognized and used
- [x] Installation succeeds

---

## Test 3: User Creation on Fresh System

### Setup

```bash
# Remove user if exists (for testing)
sudo userdel -r lucid 2>/dev/null || true
```

### Steps

```bash
# Install
sudo lucid-agent-core install-service --wheel dist/lucid_agent_core-1.0.0-py3-none-any.whl
```

### Expected Output

```
Creating user 'lucid'...
User 'lucid' created successfully
Creating virtual environment...
...
```

### Verification

```bash
# Verify user was created
id lucid

# Verify home directory
ls -la /home/lucid
# Expected: home directory exists

# Verify shell
getent passwd lucid
# Expected: lucid:x:...:...::/home/lucid:/bin/bash
```

**Pass Criteria:**
- [x] User created automatically
- [x] Home directory `/home/lucid` created
- [x] Shell set to `/bin/bash`
- [x] Installation completes successfully

---

## Test 4: Idempotency - Re-run Installation

### Steps

```bash
# First install
sudo lucid-agent-core install-service --wheel dist/lucid_agent_core-1.0.0-py3-none-any.whl

# Re-run immediately
sudo lucid-agent-core install-service --wheel dist/lucid_agent_core-1.0.0-py3-none-any.whl
```

### Expected Output

Second run should show:
```
User 'lucid' already exists
Virtual environment already exists: /home/lucid/lucid-agent-core/venv
Environment file already exists: /home/lucid/lucid-agent-core/agent-core.env
Installing from local wheel: dist/lucid_agent_core-1.0.0-py3-none-any.whl
...
✓ lucid-agent-core installed and enabled successfully!
```

### Verification

```bash
# Verify no errors
echo $?
# Expected: 0

# Verify service still works
systemctl status lucid-agent-core
```

**Pass Criteria:**
- [x] Re-run completes without errors
- [x] Existing files not corrupted
- [x] Service still functional

---

## Test 5: GitHub Fallback When No Wheel Provided

### Steps

```bash
# Install without --wheel flag
sudo lucid-agent-core install-service
```

### Expected Output

```
User 'lucid' already exists
Creating virtual environment...
Installing from GitHub release: https://github.com/LucidLabPlatform/lucid-agent-core/releases/download/v1.0.0/lucid_agent_core-1.0.0-py3-none-any.whl
...
✓ lucid-agent-core installed and enabled successfully!
```

### Verification

```bash
# Verify installation succeeded
/home/lucid/lucid-agent-core/venv/bin/lucid-agent-core --version
```

**Pass Criteria:**
- [x] Falls back to GitHub release URL
- [x] Installation succeeds
- [x] CLI works correctly

---

## Test 6: Invalid Wheel Path Handling

### Steps

```bash
# Try with non-existent wheel
sudo lucid-agent-core install-service --wheel /nonexistent/wheel.whl
```

### Expected Output

```
Error: Wheel file not found: /nonexistent/wheel.whl
```

### Verification

```bash
# Verify command failed
echo $?
# Expected: non-zero exit code
```

**Pass Criteria:**
- [x] Clear error message shown
- [x] Installation aborts gracefully
- [x] Non-zero exit code

---

## Test 7: CI/CD Pipeline Simulation

### Steps

```bash
#!/bin/bash
set -e

# Simulate CI/CD pipeline
echo "Building wheel..."
python -m build

echo "Installing on target..."
WHEEL=$(ls dist/*.whl | tail -1)
sudo lucid-agent-core install-service --wheel "$WHEEL"

echo "Configuring..."
sudo tee /home/lucid/lucid-agent-core/agent-core.env <<EOF
MQTT_HOST=mqtt.example.com
MQTT_PORT=1883
AGENT_USERNAME=ci-test-agent
AGENT_PASSWORD=test-password
AGENT_HEARTBEAT=30
EOF

echo "Starting service..."
sudo systemctl start lucid-agent-core

echo "Waiting for startup..."
sleep 5

echo "Checking status..."
sudo systemctl is-active lucid-agent-core

echo "Checking logs..."
sudo journalctl -u lucid-agent-core -n 20 --no-pager

echo "CI/CD pipeline test complete!"
```

### Expected Output

```
Building wheel...
Installing on target...
...
✓ lucid-agent-core installed and enabled successfully!
Configuring...
Starting service...
Waiting for startup...
active
Checking logs...
...LUCID Agent Core...
...Agent running...
CI/CD pipeline test complete!
```

**Pass Criteria:**
- [x] Full pipeline runs without errors
- [x] Service starts and runs
- [x] Logs show successful operation

---

## Summary Checklist

### Installation Methods
- [ ] Install with `--wheel PATH` flag
- [ ] Install with `LUCID_AGENT_CORE_WHEEL` env var
- [ ] Install without wheel (GitHub fallback)

### User Creation
- [ ] User created if missing
- [ ] Home directory `/home/lucid` created
- [ ] Shell set to `/bin/bash`
- [ ] Existing user preserved

### Idempotency
- [ ] Re-running installer safe
- [ ] Existing files preserved
- [ ] Service remains functional

### Error Handling
- [ ] Invalid wheel path rejected with clear error
- [ ] Missing wheel file detected
- [ ] Non-zero exit code on failure

### Integration
- [ ] CI/CD pipeline scenario works
- [ ] Service starts after installation
- [ ] Configuration can be applied
- [ ] Logs accessible

## Cleanup After Tests

```bash
# Stop and disable service
sudo systemctl stop lucid-agent-core
sudo systemctl disable lucid-agent-core

# Remove service file
sudo rm /etc/systemd/system/lucid-agent-core.service
sudo systemctl daemon-reload

# Remove installation
sudo rm -rf /home/lucid/lucid-agent-core

# Optionally remove user
sudo userdel -r lucid
```
