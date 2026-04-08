# LUCID Agent Core — Manual Install on Ubuntu 20.04

Ubuntu 20.04 ships with Python 3.8 and `install-service` requires Python 3.11+.
On machines with LDAP authentication, `install-service` also fails because it tries
to create a local `lucid` system user. This guide covers the full manual setup.

## 1. Install Python 3.11 (build from source)

The deadsnakes PPA is unreliable on Ubuntu 20.04 (expired keys, hangs). Build from source instead.

```bash
# Install build dependencies (single line — do not use backslash continuation)
sudo apt install build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev wget

# Download and build Python 3.11
wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
tar xzf Python-3.11.9.tgz
cd Python-3.11.9
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
sudo make altinstall

# Verify
python3.11 --version
```

## 2. Create agent directory and venv

```bash
mkdir -p ~/lucid-agent-core/{data,logs,run}
python3.11 -m venv ~/lucid-agent-core/venv
```

## 3. Install lucid-agent-core

From a GitHub release wheel:

```bash
~/lucid-agent-core/venv/bin/pip install https://github.com/LucidLabPlatform/lucid-agent-core/releases/download/v2.0.0/lucid_agent_core-2.0.0-py3-none-any.whl
```

Or from a local wheel file:

```bash
~/lucid-agent-core/venv/bin/pip install /path/to/lucid_agent_core-*.whl
```

## 4. Configure

Extract the bundled env.example and edit it:

```bash
~/lucid-agent-core/venv/bin/python -c \
  "from importlib import resources; print(resources.files('lucid_agent_core').joinpath('env.example').read_text())" \
  > ~/lucid-agent-core/agent-core.env

nano ~/lucid-agent-core/agent-core.env
```

Set at minimum:

```
MQTT_HOST=<your broker address>
MQTT_PORT=1883
AGENT_USERNAME=<agent id>
AGENT_PASSWORD=<password>
```

## 5. Test run (manual)

```bash
set -a
source ~/lucid-agent-core/agent-core.env
set +a
export LUCID_AGENT_BASE_DIR=~/lucid-agent-core
~/lucid-agent-core/venv/bin/lucid-agent-core run
```

Ctrl+C to stop once you confirm it connects.

## 6. Install as a systemd service

Replace `<your-username>` with your actual Linux/LDAP username (e.g. `forfaly`).

```bash
sudo tee /etc/systemd/system/lucid-agent-core.service << 'EOF'
[Unit]
Description=LUCID Agent Core
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=forfaly
WorkingDirectory=/home/forfaly/lucid-agent-core
ExecStart=/home/forfaly/lucid-agent-core/venv/bin/lucid-agent-core run
EnvironmentFile=/home/forfaly/lucid-agent-core/agent-core.env
Environment=PYTHONUNBUFFERED=1
Environment=LUCID_AGENT_BASE_DIR=/home/forfaly/lucid-agent-core
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lucid-agent-core
```

## 7. Verify

```bash
sudo systemctl status lucid-agent-core
sudo journalctl -u lucid-agent-core -f   # follow logs
```

## Upgrading

```bash
~/lucid-agent-core/venv/bin/pip install --upgrade <new-wheel-url-or-path>
sudo systemctl restart lucid-agent-core
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Missing required environment variable: MQTT_HOST` | Env file not loaded — check `EnvironmentFile` path in the service unit matches your actual file |
| `python3.11: command not found` after build | It's at `/usr/local/bin/python3.11` — use the full path |
| Service won't start (permission denied) | Make sure `User=` in the unit file matches the owner of `~/lucid-agent-core/` |
