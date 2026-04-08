# Issues: lucid-agent-core
_Generated 2026-04-01 — 28 issues found_

## Summary

The biggest themes are: (1) a **dependency version mismatch** in `requirements.txt` that would break the dev environment; (2) a **`.env` double-load** that can let a local file override systemd-injected secrets; and (3) **missing rollback on component upgrade** meaning a failed upgrade can leave the installed package and registry permanently out of sync. Beyond those, there are scattered inconsistencies in defaults, a test fixture with an invalid agent ID, and several minor maintainability issues.

---

## Critical

### [CRITICAL] `requirements.txt` pins `paho-mqtt==1.6.1` but the codebase uses the paho-mqtt 2.x API
**File:** `requirements.txt:2` / `pyproject.toml:14`

`pyproject.toml` declares `paho-mqtt>=2.0.0` as a runtime dependency. The entire `mqtt/client.py` relies on paho 2.x-only APIs: `mqtt.CallbackAPIVersion.VERSION2` (line 471), the five-argument callback signatures (`_on_connect`, `_on_disconnect`), and `connect_flags` / `reason_code` parameters. `requirements.txt` pins `paho-mqtt==1.6.1`.

Anyone who runs `make test-deps` (which does `pip install -r requirements.txt`) will install the wrong version and immediately crash with `AttributeError: module 'paho.mqtt.client' has no attribute 'CallbackAPIVersion'`. The `requirements.txt` file is therefore **actively harmful** — it should either be deleted (the `pyproject.toml` already pins deps) or updated to `paho-mqtt>=2.0.0`.

---

### [CRITICAL] `config.py` loads `.env` twice — second pass with `override=True` can silently override systemd-injected credentials
**File:** `src/lucid_agent_core/config.py:88-106`

`load_config()` first loops over all env paths calling `load_dotenv(p, override=False)` (so process env wins), but then does a **second call** on line 102-106:
```python
load_dotenv(Path(".env"), override=True)
```
This call with `override=True` can overwrite environment variables that systemd set via `EnvironmentFile=/home/lucid/lucid-agent-core/agent-core.env`. On a production Pi, `AGENT_PASSWORD` could be silently replaced by a stale `.env` file left in the working directory. The comment says "allow local .env to override explicitly if desired" but `.env` was already loaded (without override) in the first pass — this second pass serves no legitimate purpose and is a security risk.

---

### [CRITICAL] Component upgrade leaves agent in an inconsistent state on failure after pip install
**File:** `src/lucid_agent_core/core/upgrade/component_upgrader.py:150-154`

`handle_component_upgrade()` runs `pip_upgrade_wheel()` inside a `tempfile.TemporaryDirectory` context, then exits the context and **separately** calls `write_registry()`. If pip install succeeds but `write_registry()` raises (e.g., disk full, permission error), the new wheel is now installed in the venv but the registry still records the old version. On the next agent restart, the component will be loaded from the new binary but the registry metadata is stale.

`component_installer.py` correctly handles this with a rollback step (`pip_uninstall_dist`). The upgrader has no rollback.

---

## High

### [HIGH] `component_upgrader.py` returns `restart_required=True` even on validation failure
**File:** `src/lucid_agent_core/core/upgrade/component_upgrader.py:113-117`

When payload validation fails, the result is:
```python
return ComponentUpgradeResult(..., ok=False, ..., restart_required=True)
```
A validation failure means nothing was installed, so a restart is not needed. The `install_handler.py` and `core_upgrader.py` correctly return `restart_required=False` on validation failure. This inconsistency would cause the agent to restart on every malformed upgrade command.

---

### [HIGH] `client.py` sets `_connected_since_ts` before the TCP connection is established
**File:** `src/lucid_agent_core/mqtt/client.py:466-468`

In `connect()`:
```python
if self._connected_since_ts is None:
    self._connected_since_ts = _utc_iso()
    self._connected_ts = time.time()
```
This runs _before_ `client.connect(host, port)` is called (line 487). If the TCP handshake takes a few seconds (or fails and a retry occurs), the "connected since" timestamp is earlier than the actual connection. `_on_connect` checks `if self._connected_since_ts is None` to avoid re-setting it, so it never corrects the pre-set value. The timestamp visible to Central Command will be slightly earlier than reality and will reset to the wrong value if the connection drops and recovers.

---

### [HIGH] `build_cfg_logging()` defaults to `"ERROR"` but `level_from_cfg_or_env()` defaults to `INFO` — published state disagrees with actual behavior
**File:** `src/lucid_agent_core/core/snapshots.py:140` / `src/lucid_agent_core/core/log_config.py:31`

```python
# snapshots.py — what Central Command reads from /cfg/logging:
"log_level": str(cfg.get("log_level", "ERROR"))

# log_config.py — what the agent actually applies:
return _parse_level(raw) if raw else logging.INFO
```
When no `log_level` has been configured, the retained `cfg/logging` topic publishes `"ERROR"` but the agent is actually running at `INFO`. Any dashboard or operator relying on the retained topic to know the current log level will see the wrong value until they explicitly set it.

---

### [HIGH] `conftest.py` test fixture uses `"test-agent"` (hyphen) as `AGENT_USERNAME`, which is invalid per the topic schema
**File:** `tests/conftest.py:18`

```python
'AGENT_USERNAME': 'test-agent',
```
`TopicSchema.__post_init__` validates agent IDs against `^[a-z0-9_]+$` — hyphens are not allowed. Any test that uses the `mock_env` fixture and subsequently creates an `AgentMQTTClient` or `TopicSchema` with `agent_1 = cfg.agent_username` will raise a `TopicSchemaError`. The tests that explicitly use `"agent_1"` as their username happen to avoid this, but it is a latent bug for future tests.

---

### [HIGH] `ensure_dirs()` in `paths.py` creates the `venv_dir` at agent startup
**File:** `src/lucid_agent_core/paths.py:125-134` / `src/lucid_agent_core/main.py:137`

`run_agent()` calls `ensure_dirs(paths)` which includes `venv_dir` in the directories to create. On a fresh install this is fine, but on a running agent that's been deployed without that directory for some reason, it will silently create an empty `venv/` directory. The pip-based upgrade machinery (`_pip.py`) checks for `pip_path.exists()` before running pip — it will now find an empty dir and raise `FileNotFoundError: pip executable not found` rather than a clearer error.

This also means running the agent from a development checkout (without the `/home/lucid/lucid-agent-core/venv` path) will create those directories under `/home/lucid/` even in dev mode.

---

### [HIGH] `_github_release.py` has no size limit on GitHub API response body
**File:** `src/lucid_agent_core/core/upgrade/_github_release.py:39-41`

```python
with urlopen(api_req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
    data = json.loads(resp.read().decode("utf-8"))
```
The full response is read into memory with no byte cap. GitHub release metadata is normally small, but a release with many large assets (or a malicious redirect) could exhaust memory on a Pi with limited RAM. The `_download.py` module correctly uses a chunked loop with `MAX_WHEEL_BYTES`; the same protection should apply here.

---

### [HIGH] `_pip.py` captures unlimited pip stdout/stderr into memory and publishes to MQTT
**File:** `src/lucid_agent_core/core/upgrade/_pip.py:37-48, 73-95`

`pip install` output is captured entirely with `capture_output=True` and returned in the result dataclass, which is then serialized to JSON and published over MQTT. On a slow install with verbose output (e.g., compiling C extensions), this could be megabytes of text. The `install_handler` truncates debug logs to 500 chars but the MQTT payload itself is uncapped.

---

## Medium

### [MEDIUM] `components/` subpackage has no `__init__.py` — inconsistent with all other subpackages
**File:** `src/lucid_agent_core/components/` (directory)

Every other sub-package (`mqtt/`, `core/`, `core/config/`, `core/handlers/`, `core/upgrade/`) has an `__init__.py`. The `components/` directory does not. Python 3.3+ namespace packages make this work, but it's inconsistent and can cause issues with some build tools, IDEs, and code scanners that expect explicit package markers.

---

### [MEDIUM] `telemetry.py` imports private symbols from `snapshots.py`
**File:** `src/lucid_agent_core/mqtt/telemetry.py:140-145`

```python
from lucid_agent_core.core.snapshots import (
    build_cfg_telemetry,
    _system_cpu_percent,
    _system_memory_percent,
    _system_disk_percent,
)
```
The three underscore-prefixed functions are private by Python convention. They should be exposed as public API from `snapshots.py` (rename or re-export) so that modules outside `snapshots` don't need to reach into private implementation details.

---

### [MEDIUM] `Makefile` help text still says `LUCID Agent Core v1.0.0`
**File:** `Makefile:7`

```makefile
@echo "LUCID Agent Core v1.0.0"
```
The project is at v2.x (`dist/` contains 2.0.1 and 2.0.2 wheels). This misleads any developer running `make help`.

---

### [MEDIUM] `pytest.ini` and `pyproject.toml` both define `[tool.pytest.ini_options]` — `pytest.ini` wins and enables coverage on every test run
**File:** `pytest.ini` / `pyproject.toml:50-58`

`pytest.ini` defines:
```ini
addopts = -v --tb=short --strict-markers --color=yes --cov=src --cov-report=term-missing --cov-report=html
```
`pyproject.toml` defines:
```toml
addopts = "-q"
```
Pytest reads `pytest.ini` first and ignores `pyproject.toml`'s pytest section. The `--cov=src` flag means every `pytest` run produces coverage, adding 1-2 seconds of overhead even for quick unit tests. The duplicate configuration is also confusing.

---

### [MEDIUM] `conftest.py` adds `src/` to `sys.path` unnecessarily
**File:** `tests/conftest.py:10`

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
```
The package is installed in editable mode (`pip install -e ".[dev]"`), so `lucid_agent_core` is already importable. This path manipulation is redundant and can cause subtle import confusion — the same module could theoretically be importable via two different paths (the installed path and this injected path), leading to the "duplicate module" problem where `isinstance` checks fail across boundaries.

---

### [MEDIUM] `test_loader.py` has two nearly-identical tests
**File:** `tests/unit/test_loader.py:68-103`

`test_loads_but_does_not_start_when_disabled` and `test_skips_start_when_disabled` are functionally identical — same setup, same assertions, same behavior under test. One should be removed.

---

### [MEDIUM] `write_registry()` and `atomic_write()` leave behind `.lock` files permanently
**File:** `src/lucid_agent_core/components/registry.py:100-121` / `src/lucid_agent_core/core/config/_file_io.py:38-56`

Lock files (`components_registry.json.lock`, `core_config.json.lock`) are opened and locked but never deleted. They accumulate indefinitely. While `flock` works correctly on open file descriptors and the presence of the files doesn't break correctness, it's messy and can confuse operators inspecting the data directory.

---

### [MEDIUM] `installer.py` calls `_user_ids()` / `pwd.getpwnam()` twice for every chown operation
**File:** `src/lucid_agent_core/installer.py:62-70`

`_owner_spec()` and `_service_group_spec()` each call `_user_ids()` which calls `pwd.getpwnam(SYSTEM_USER)`. They're called together in `_write_systemd_unit()` (lines 312-313), resulting in two `getpwnam` calls that could be one. Minor inefficiency but worth cleaning up.

---

### [MEDIUM] `core_upgrader.py` and `installer.py` hardcode the GitHub org `LucidLabPlatform`
**File:** `src/lucid_agent_core/core/upgrade/core_upgrader.py:29-30` / `src/lucid_agent_core/installer.py:272-278`

```python
CORE_GITHUB_OWNER = "LucidLabPlatform"
CORE_GITHUB_REPO = "lucid-agent-core"
```
Any fork, white-label, or self-hosted deployment must edit source code. These should be configurable via environment variable with the current value as default.

---

### [MEDIUM] `refresh_handler.py` has a fallback branch that will never be executed in production
**File:** `src/lucid_agent_core/core/handlers/refresh_handler.py:51-65`

```python
if hasattr(ctx.mqtt, "publish_retained_refresh"):
    ctx.mqtt.publish_retained_refresh(components_list)
else:
    # inline fallback: republish manually
```
`ctx.mqtt` is always `AgentMQTTClient`, which always has `publish_retained_refresh`. The `else` branch is dead code in every production and test path. It duplicates logic from `mqtt/retained.py` and will silently drift as the retained schema evolves. It should be removed.

---

### [MEDIUM] `_configure_logging()` runs at module import time in `main.py`
**File:** `src/lucid_agent_core/main.py:41`

```python
_configure_logging()
logger = logging.getLogger(__name__)
```
Calling `logging.basicConfig(...)` as a module-level side effect means that importing `lucid_agent_core.main` in tests (or any other context) configures the global logging system. This can interfere with pytest's own log capture and any test that tries to configure logging independently.

---

## Low

### [LOW] `_SEMVER_RE` doesn't support prerelease or build metadata
**File:** `src/lucid_agent_core/core/upgrade/_validation.py:15`

```python
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
```
Legitimate semver values like `1.2.3-rc.1` or `1.2.3+build.42` are rejected. This is intentionally strict (install commands must specify exact releases) but it's undocumented.

---

### [LOW] `_github_release.py` makes unauthenticated GitHub API calls — subject to rate limiting
**File:** `src/lucid_agent_core/core/upgrade/_github_release.py:31-45`

No `Authorization` header. Unauthenticated GitHub API calls are rate-limited to 60/hour per IP. On a fleet of Pis all behind the same NAT, a wave of simultaneous component installs could hit the limit, causing installs to fail with a cryptic `failed to fetch release` error. A `GITHUB_TOKEN` environment variable override would be simple to add and would raise the limit to 5,000/hour.

---

### [LOW] `.env.example` comment says `/etc/lucid/agent-core.env` but the actual path is `/home/lucid/lucid-agent-core/agent-core.env`
**File:** `.env.example:4`

```
# Location on device: /etc/lucid/agent-core.env
```
The real path, as written by the installer and read by systemd, is `/home/lucid/lucid-agent-core/agent-core.env`. This stale comment will confuse operators trying to find and edit the config file on a deployed Pi.

---

### [LOW] `env.example` is duplicated — one at repo root, one inside the package
**File:** `.env.example` (root) / `src/lucid_agent_core/env.example`

Two separate example env files exist. The root one has a stale path comment (above issue). The packaged one (`src/lucid_agent_core/env.example`) is what the installer uses. They're not kept in sync and will continue to diverge.

---

### [LOW] `test_installer.py` `test_write_systemd_unit_uses_overridden_user_and_base_dir` hardcodes the custom user as `"forfaly"`
**File:** `tests/unit/test_installer.py:383`

```python
monkeypatch.setattr(inst, "SYSTEM_USER", "forfaly")
```
This is a real name, apparently the developer's username. Using a generic placeholder like `"testuser"` is less surprising.

---

### [LOW] `dummy.py` component's `component_id` property returns a hardcoded `"dummy"` regardless of registry
**File:** `src/lucid_agent_core/components/dummy.py:17`

```python
@property
def component_id(self) -> str:
    return "dummy"
```
The loader explicitly warns when the component's `component_id` doesn't match the registry key (loader.py:81-86). If `DummyComponent` is ever registered under a key other than `"dummy"`, the mismatch warning fires every time it loads. The `component_id` should be derived from the `ComponentContext` as other real components do, not hardcoded.

---

### [LOW] `dist/` directory contains committed wheel files
**File:** `dist/lucid_agent_core-2.0.1-py3-none-any.whl`, `dist/lucid_agent_core-2.0.2-py3-none-any.whl` (and tarballs)

Build artifacts (`dist/*.whl`, `dist/*.tar.gz`) should not be committed to the repo. They should be in `.gitignore`. They bloat the repo history and the committed wheels may not match the current source.

---

## Per-File Breakdown

### `requirements.txt`
- [CRITICAL] Pins `paho-mqtt==1.6.1` while codebase requires paho 2.x API — will break any environment that runs `make test-deps`

### `src/lucid_agent_core/config.py`
- [CRITICAL] Double `.env` load: lines 88-96 load with `override=False`, then lines 100-106 reload with `override=True`, which can silently overwrite systemd-injected credentials

### `src/lucid_agent_core/core/upgrade/component_upgrader.py`
- [CRITICAL] No rollback on failure after pip install — registry and installed package can permanently diverge
- [HIGH] Returns `restart_required=True` on validation failure — causes unnecessary agent restart

### `src/lucid_agent_core/mqtt/client.py`
- [HIGH] `connect()` sets `_connected_since_ts` before the TCP connection is established — timestamp will be earlier than reality

### `src/lucid_agent_core/core/snapshots.py` + `src/lucid_agent_core/core/log_config.py`
- [HIGH] `build_cfg_logging()` defaults to `"ERROR"` but `level_from_cfg_or_env()` defaults to `INFO` — MQTT state disagrees with actual runtime behavior

### `tests/conftest.py`
- [HIGH] `mock_env` fixture uses `AGENT_USERNAME='test-agent'` (hyphen) — invalid per `TopicSchema` regex `^[a-z0-9_]+$`
- [LOW] Adds `src/` to `sys.path` unnecessarily — editable install already covers this

### `src/lucid_agent_core/paths.py`
- [HIGH] `ensure_dirs()` creates `venv_dir` at agent startup, which can confuse pip upgrade machinery

### `src/lucid_agent_core/core/upgrade/_github_release.py`
- [HIGH] No size limit on GitHub API response body
- [LOW] Unauthenticated API calls — 60/hr rate limit can block fleet deployments

### `src/lucid_agent_core/core/upgrade/_pip.py`
- [HIGH] Captures unlimited pip stdout/stderr into memory and publishes to MQTT

### `src/lucid_agent_core/components/` (directory)
- [MEDIUM] Missing `__init__.py` — inconsistent with all other subpackages

### `src/lucid_agent_core/mqtt/telemetry.py`
- [MEDIUM] Imports private underscore symbols `_system_cpu_percent` etc. from `snapshots.py`

### `Makefile`
- [MEDIUM] Help text says `v1.0.0` — project is at v2.x

### `pytest.ini` + `pyproject.toml`
- [MEDIUM] Duplicate pytest config — `pytest.ini` wins and forces `--cov` on every run

### `src/lucid_agent_core/core/handlers/refresh_handler.py`
- [MEDIUM] Dead code `else` branch for `publish_retained_refresh` that will never execute

### `src/lucid_agent_core/main.py`
- [MEDIUM] `_configure_logging()` runs at import time — side effect on test environments

### `src/lucid_agent_core/installer.py`
- [MEDIUM] Calls `_user_ids()` / `pwd.getpwnam()` twice per chown operation
- [LOW] Hardcodes `LucidLabPlatform` org name — forks/white-labels must edit source

### `src/lucid_agent_core/core/upgrade/core_upgrader.py`
- [MEDIUM] Hardcodes `LucidLabPlatform` org name

### `src/lucid_agent_core/components/registry.py` + `src/lucid_agent_core/core/config/_file_io.py`
- [MEDIUM] `.lock` files are never cleaned up after use

### `tests/unit/test_loader.py`
- [MEDIUM] `test_loads_but_does_not_start_when_disabled` and `test_skips_start_when_disabled` are duplicates

### `.env.example`
- [LOW] Stale path comment says `/etc/lucid/agent-core.env` — actual path is `/home/lucid/lucid-agent-core/agent-core.env`

### `src/lucid_agent_core/env.example` + `.env.example`
- [LOW] Two example env files that will drift out of sync

### `tests/unit/test_installer.py`
- [LOW] Hardcodes test user `"forfaly"` — should use a generic placeholder

### `src/lucid_agent_core/components/dummy.py`
- [LOW] `component_id` returns hardcoded `"dummy"` — could cause loader mismatch warnings if registered under a different key

### `dist/`
- [LOW] Build artifacts (`*.whl`, `*.tar.gz`) should not be committed — add to `.gitignore`

### `src/lucid_agent_core/core/upgrade/_validation.py`
- [LOW] `_SEMVER_RE` rejects valid prerelease semver (`1.2.3-rc.1`) — intentionally strict but undocumented
