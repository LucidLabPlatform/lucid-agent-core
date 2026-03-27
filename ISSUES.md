# Issues: lucid-agent-core

*Generated 2026-03-26 — 33 issues found*

## Summary

The most pressing concerns are unauthenticated GitHub API calls in the component installer, and a threading race condition at startup. Beyond those, the main themes are missing test coverage for critical paths (telemetry thresholds, connection failures, concurrency), a handful of security concerns in the installer, and general maintainability debt (duplicated patterns, oversized modules, silent exception swallowing).

---

## High

### [HIGH] GitHub API requests are unauthenticated

- **File**: `src/lucid_agent_core/core/component_installer.py` lines 248–262
- **Issue**: All GitHub API requests go out without an auth token. Public rate limit is 60 req/hour. Under any load (multiple installs, retries) the agent hits that limit and component installation silently fails.
- **Impact**: Reliability DoS; production fleets that reinstall components will hit this regularly.

### [HIGH] No URL/path validation on custom wheel installs

- **File**: `src/lucid_agent_core/installer.py` lines 180–223
- **Issue**: `LUCID_AGENT_CORE_WHEEL` env var is accepted and passed to `Path(args.wheel)` without sanitisation. A path like `../../../etc/passwd` is valid input. The installer typically runs as root/sudo.
- **Impact**: Local file access / path traversal in a privileged context.

---

## Medium

### [MEDIUM] Race condition: `_connected_ts` set after `_on_connect` can fire

- **File**: `src/lucid_agent_core/mqtt_client.py` lines 720–723, 798–802
- **Issue**: `_connected_ts` is assigned in `connect()` (line 801) but `_on_connect()` is a callback that fires on the MQTT network thread. If the callback fires before the assignment, `_connected_ts` is still `None` when uptime is calculated.
- **Impact**: Potential `None` dereference; malformed status payload at startup.

### [MEDIUM] Inconsistent log level defaults — docstring, basicConfig, and apply_log_level all disagree

- **File**: `src/lucid_agent_core/main.py` lines 25–36
- **Issue**: Docstring says DEBUG, `basicConfig` sets INFO, then `apply_log_level_from_config()` defaults to ERROR. Three different values in a chain; actual output is unpredictable.
- **Impact**: Operators cannot determine log verbosity from reading the code.

### [MEDIUM] Silent exception swallowing in MQTT log handler

- **File**: `src/lucid_agent_core/core/mqtt_log_handler.py` lines 82–86, 126–128, 187–189
- **Issue**: Three `except Exception: pass` blocks — one in traceback formatting, one in `emit()`, one in publish. Errors in the logging path vanish completely.
- **Impact**: Impossible to diagnose logging failures; agents appear healthy when logging is broken.

### [MEDIUM] Private attribute access across module boundary

- **File**: `src/lucid_agent_core/core/mqtt_log_handler.py` lines 177–179
- **Issue**: `MQTTLogHandler` reaches into `mqtt_client._client` (private paho attribute). Any internal refactor of `AgentMQTTClient` silently breaks log publishing.
- **Impact**: Tight coupling; architectural violation per CLAUDE.md "no hidden state".

### [MEDIUM] `handlers.py` is a 620-line monolith

- **File**: `src/lucid_agent_core/core/handlers.py`
- **Issue**: Twelve+ command handlers (ping, cfg, components, core upgrade) all in one file. Violates CLAUDE.md "small focused modules".
- **Impact**: Hard to test individual handlers; merge conflicts on every new command; onboarding friction.

### [MEDIUM] Registry validation silently drops corrupt entries

- **File**: `src/lucid_agent_core/components/registry.py` lines 39–48
- **Issue**: `_validate_registry_shape()` does `if not isinstance(v, dict): continue` with no log message. A corrupted or tampered registry entry is silently discarded.
- **Impact**: Registry tampering goes undetected; components fail to load with no actionable error.

### [MEDIUM] No tests for telemetry threshold calculation

- **File**: `tests/unit/` (missing)
- **Issue**: `_should_publish_telemetry()` in `mqtt_client.py` (lines 541–571) implements interval gating, delta-%, and zero-value handling but has no dedicated test cases.
- **Impact**: Core telemetry gating is untested; regressions will not be caught.

### [MEDIUM] No tests for MQTT connection failure paths

- **File**: `tests/unit/` (missing)
- **Issue**: `connect()` is only tested for the success path. Bad host, timeout, and auth rejection scenarios have no coverage.
- **Impact**: Error handling in the most critical path is unverified.

### [MEDIUM] No tests for threading / concurrency

- **File**: `tests/unit/` (missing)
- **Issue**: `_hb_thread`, `_telemetry_thread`, and `_components_lock` have no tests for concurrent access, stop/start races, or resource cleanup on shutdown.
- **Impact**: Concurrency bugs slip through and are hard to reproduce in production.

### [MEDIUM] No authoritative MQTT topic reference

- **File**: Documentation (missing `topics.txt`, `MQTT_CONTRACT_V1.md`)
- **Issue**: CLAUDE.md references `topics.txt` and README references `MQTT_CONTRACT_V1.md`; neither file exists in the repo.
- **Impact**: No single authoritative source for topic schemas; developers invent patterns.

---

## Low

### [LOW] Duplicate `_COMPONENT_ID_RE` regex defined in three places

- **File**: `src/lucid_agent_core/core/component_installer.py` line 35, `component_uninstaller.py` line 24, `mqtt_topics.py` line 18
- **Issue**: Identical pattern `r"^[a-z0-9_]+$"` duplicated. A change to the valid character set must be made in three places.
- **Impact**: Validation can silently diverge between install and uninstall paths.

### [LOW] Unused parameters in `build_components_list()`

- **File**: `src/lucid_agent_core/core/snapshots.py` lines 80–92
- **Issue**: `component_manager` and `components` parameters are documented as unused but retained for "compatibility". Callers pass values that are ignored.
- **Impact**: Misleading API; future callers will assume parameters have effect.

### [LOW] `_batch_timestamps` list grows unbounded under high log rate

- **File**: `src/lucid_agent_core/core/mqtt_log_handler.py` line 145
- **Issue**: Rate-limiting window implemented as a plain list rebuilt on every emit with a list comprehension. Under high log rates, the list grows until the cutoff prunes it, consuming growing memory.
- **Impact**: Memory growth in long-running agents with DEBUG logging enabled.

### [LOW] `config.py` loads `.env` twice with different `override` semantics

- **File**: `src/lucid_agent_core/config.py` lines 88–106
- **Issue**: `.env` is loaded first with `override=False` and again with `override=True`. The second load always wins. The intent is unclear and the first load is effectively a no-op.
- **Impact**: Confusing config precedence logic; hard to reason about which value wins.

### [LOW] `fcntl` import makes `config_store.py` Linux-only without abstraction

- **File**: `src/lucid_agent_core/core/config_store.py` line ~150
- **Issue**: `import fcntl` is lazy-imported and absent on Windows/Mac. No platform shim or clear documentation that this is intentional.
- **Impact**: Cannot run the agent or its tests on macOS without workarounds.

### [LOW] Lazy import inside `_build_handlers()` obscures dependency graph

- **File**: `src/lucid_agent_core/mqtt_client.py` lines 138–151
- **Issue**: `from lucid_agent_core.core.handlers import (...)` is done inside a method to avoid circular imports. The circular import should be resolved structurally rather than papered over.
- **Impact**: Module dependency graph is invisible to static analysis tools and IDEs.

### [LOW] Magic numbers in startup connection wait loop

- **File**: `src/lucid_agent_core/main.py` lines 135–140
- **Issue**: `for _ in range(50): ... time.sleep(0.1)` — comment says "5 seconds". The comment is the only documentation of the intent; change the numbers and the comment is wrong.
- **Impact**: Timeout is fragile and the relationship between constants is implicit.

### [LOW] `Any` types used where specific types exist

- **File**: `src/lucid_agent_core/mqtt_client.py` lines 170, 292, 330
- **Issue**: `components: list[Any]` should use the `Component` protocol or base class. CLAUDE.md requires "type hints required".
- **Impact**: Static analysis misses type errors in component handler wiring.

### [LOW] No tests for publish failure in mock fixtures

- **File**: `tests/conftest.py` lines 34–39
- **Issue**: Mock `publish()` always returns `(0, 1)`. Error paths for publish failures (e.g., queue full, not connected) are never exercised.
- **Impact**: Code paths that handle publish failures are never executed in tests.

### [LOW] Inconsistent result type naming (`InstallResult` vs `ComponentUpgradeResult`)

- **File**: Multiple files in `src/lucid_agent_core/core/`
- **Issue**: Result classes use different naming conventions: `InstallResult`, `UninstallResult`, `ComponentUpgradeResult`, `CoreUpgradeResult`. No consistent suffix or pattern.
- **Impact**: Code navigation; searching for result types requires knowing each variant.

### [LOW] No upgrade / migration guide in documentation

- **File**: Documentation
- **Issue**: No guidance on upgrading between versions or what breaking changes exist between releases.
- **Impact**: Operators don't know how to update fleets safely.

---

## Per-File Breakdown

### `.env`

- [CRITICAL] Hardcoded `AGENT_PASSWORD=123456789` — credentials in version control, permanent in git history

### `src/lucid_agent_core/main.py`

- [MEDIUM] Three conflicting log level defaults (lines 25–36)
- [LOW] Magic numbers in startup wait loop (lines 135–140)

### `src/lucid_agent_core/mqtt_client.py`

- [MEDIUM] Race condition on `_connected_ts` initialization (lines 720–723, 798–802)
- [MEDIUM] No telemetry threshold tests
- [LOW] Lazy import of handlers to avoid circular dependency (lines 138–151)
- [LOW] `Any` typed parameters where specific types exist (lines 170, 292, 330)

### `src/lucid_agent_core/core/mqtt_log_handler.py`

- [MEDIUM] Three silent `except Exception: pass` blocks (lines 82–86, 126–128, 187–189)
- [MEDIUM] Accesses private `mqtt_client._client` across module boundary (lines 177–179)
- [LOW] `_batch_timestamps` list grows unbounded under high log rates (line 145)

### `src/lucid_agent_core/core/handlers.py`

- [MEDIUM] 620-line monolith with 12+ unrelated command handlers

### `src/lucid_agent_core/core/component_installer.py`

- [HIGH] Unauthenticated GitHub API requests (lines 248–262)
- [LOW] Duplicate `_COMPONENT_ID_RE` pattern (line 35)

### `src/lucid_agent_core/core/component_uninstaller.py`

- [LOW] Duplicate `_COMPONENT_ID_RE` pattern (line 24)

### `src/lucid_agent_core/installer.py`

- [HIGH] No path validation on custom wheel path (lines 180–223)

### `src/lucid_agent_core/components/registry.py`

- [MEDIUM] Silent discard of invalid registry entries without logging (lines 39–48)

### `src/lucid_agent_core/core/snapshots.py`

- [LOW] Unused parameters kept for undocumented "compatibility" (lines 80–92)

### `src/lucid_agent_core/config.py`

- [LOW] `.env` loaded twice with conflicting `override` semantics (lines 88–106)

### `src/lucid_agent_core/core/config_store.py`

- [LOW] `fcntl` lazy import makes module Linux-only with no abstraction (line ~150)

### `tests/conftest.py`

- [LOW] Mock publish always succeeds; error paths never tested (lines 34–39)

### `tests/unit/` (missing coverage)

- [MEDIUM] No tests for telemetry threshold calculation
- [MEDIUM] No tests for MQTT connection failures
- [MEDIUM] No tests for threading race conditions

