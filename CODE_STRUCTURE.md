# LUCID Agent-Core Code Structure

## Overview
Minimal Phase 1 agent that connects to MQTT broker and publishes agent status. No component management.

---

## Directory Structure

```
lucid-agent-core/
├── src/                    # Source code
│   ├── __init__.py        # Package initialization
│   ├── main.py            # Entry point
│   ├── config.py          # Configuration from environment
│   ├── mqtt_client.py     # MQTT connection & status publishing
│   └── mqtt_topics.py     # Topic schema definitions
│
├── tests/                  # Test suite
│   ├── __init__.py
│   ├── conftest.py        # Pytest fixtures & config
│   └── unit/              # Unit tests
│       ├── test_config.py
│       ├── test_main.py
│       ├── test_mqtt_client.py
│       └── test_mqtt_topics.py
│
├── docs/                   # Documentation
│   └── DEPLOYMENT_MODES.md
│
├── .gitignore              # Git ignore rules
├── Makefile                # Development commands
├── README.md               # Project overview & quick start
├── env.example             # Environment template
├── requirements.txt        # Python dependencies
└── pytest.ini              # Pytest configuration
```

---

## File Descriptions

### Source Code (`src/`)

#### `src/__init__.py`
- **Purpose**: Python package initialization
- **Content**: Empty package marker

#### `src/main.py`
- **Purpose**: Application entry point
- **Responsibilities**:
  - Initialize logging
  - Load configuration from environment
  - Create and connect MQTT client
  - Register signal handlers (SIGINT, SIGTERM) for graceful shutdown
  - Run main event loop (keeps agent alive)
- **Key Functions**:
  - `main()`: Main entry point
  - `signal_handler()`: Graceful shutdown on signals

#### `src/config.py`
- **Purpose**: Single source of configuration from environment variables
- **Responsibilities**:
  - Read required environment variables (MQTT_HOST, MQTT_PORT, AGENT_USERNAME, AGENT_PASSWORD)
  - Read optional variables (AGENT_HEARTBEAT, default: 30)
  - Derive agent version from installed package metadata
  - Exit with error if required variables are missing
- **Key Variables**:
  - `MQTT_HOST`, `MQTT_PORT`: Broker connection
  - `AGENT_USERNAME`, `AGENT_PASSWORD`: MQTT authentication
  - `AGENT_VERSION`: Agent version string (from package metadata)
  - `AGENT_HEARTBEAT`: Status publish interval (seconds)

#### `src/mqtt_client.py`
- **Purpose**: MQTT client wrapper for agent lifecycle
- **Responsibilities**:
  - Connect to MQTT broker with authentication
  - Publish agent status (online/offline) with heartbeat
  - Configure Last Will and Testament (LWT) for offline detection
  - Handle connection/disconnection events
  - Maintain connection health
- **Key Classes**:
  - `AgentMQTTClient`: Main MQTT client class
- **Key Methods**:
  - `connect()`: Establish MQTT connection
  - `disconnect()`: Clean disconnect
  - `is_connected()`: Check connection status
  - `_publish_status()`: Publish status payload
  - `_heartbeat_loop()`: Periodic status updates
- **Status Payload**:
  ```json
  {
    "state": "online|offline",
    "ts": "<iso8601>",
    "version": "<version>"
  }
  ```

#### `src/mqtt_topics.py`
- **Purpose**: Centralized MQTT topic schema definitions
- **Responsibilities**:
  - Define topic structure for agent
  - Build topic strings consistently
- **Key Classes**:
  - `TopicSchema`: Topic builder for agent
- **Key Methods**:
  - `status()`: Returns `lucid/agents/{username}/status`
- **Topic Structure**:
  - Base: `lucid/agents/{username}`
  - Status: `{base}/status` (retained, QoS 1)

---

### Tests (`tests/`)

#### `tests/conftest.py`
- **Purpose**: Pytest configuration and shared fixtures
- **Fixtures**:
  - `mock_env`: Sets up mock environment variables for testing
  - `mock_mqtt_client`: Creates mock MQTT client for tests
- **Configuration**: Adds `src/` to Python path for imports

#### `tests/unit/test_config.py`
- **Purpose**: Unit tests for configuration module
- **Tests**: Environment variable reading, defaults, required variables

#### `tests/unit/test_main.py`
- **Purpose**: Unit tests for main entry point
- **Tests**: Import validation, signal handling, startup sequence

#### `tests/unit/test_mqtt_client.py`
- **Purpose**: Unit tests for MQTT client
- **Tests**: Connection, status publishing, heartbeat, LWT, disconnection

#### `tests/unit/test_mqtt_topics.py`
- **Purpose**: Unit tests for topic schema
- **Tests**: Topic construction, schema initialization

---

### Configuration Files

#### `env.example`
- **Purpose**: Template for environment configuration
- **Variables**:
  - `LUCID_MODE=local`: Deployment mode
  - `MQTT_HOST`, `MQTT_PORT`: Broker connection
  - `AGENT_USERNAME`, `AGENT_PASSWORD`: MQTT credentials
  - Version is derived from the installed `lucid-agent-core` package metadata
  - `AGENT_HEARTBEAT`: Status interval (optional, default: 30)

#### `requirements.txt`
- **Purpose**: Python dependencies
- **Dependencies**:
  - `paho-mqtt==1.6.1`: MQTT client library
  - `pytest==7.4.3`: Testing framework
  - `pytest-cov==4.1.0`: Coverage reporting
  - `pytest-mock==3.12.0`: Mocking utilities

#### `pytest.ini`
- **Purpose**: Pytest configuration
- **Settings**:
  - Test discovery paths
  - Coverage reporting (HTML + terminal)
  - Markers: `unit`, `integration`, `e2e`, `slow`
  - Logging configuration

#### `.gitignore`
- **Purpose**: Git ignore patterns
- **Ignores**: `.env`, `__pycache__/`, `.pytest_cache/`, `htmlcov/`, etc.

---

### Documentation

#### `README.md`
- **Purpose**: Project overview and quick start guide
- **Sections**:
  - Quick Start (setup, configure, run)
  - Deployment (local run)
  - MQTT Topics (published topics)
  - Tests (unit, integration)
  - Troubleshooting

#### `docs/DEPLOYMENT_MODES.md`
- **Purpose**: Detailed deployment instructions
- **Content**: Local run setup, configuration, running, troubleshooting

---

### Build & Development

#### `Makefile`
- **Purpose**: Development commands
- **Key Targets**:
  - `make setup`: Create `.env` from `env.example`
  - `make dev`: Run agent locally (Python process)
  - `make test-unit`: Run unit tests
  - `make test-integration`: Run integration tests
  - `make test-coverage`: Run tests with coverage report

---

## Data Flow

1. **Startup**:
   - `main.py` → loads `config.py` → creates `AgentMQTTClient` → connects to broker

2. **Runtime**:
   - `AgentMQTTClient` publishes status every `AGENT_HEARTBEAT` seconds
   - Status topic: `lucid/agents/{username}/status` (retained, QoS 1)

3. **Shutdown**:
   - Signal handler → `agent.disconnect()` → LWT triggers → publishes offline status

---

## MQTT Topics

### Published
- `lucid/agents/{username}/status` (retained, QoS 1)
  - Payload: JSON with `state`, `ts`, `version`

### Subscribed
- None (Phase 1 minimal version)

---

## Testing

- **Unit Tests**: Fast, no external dependencies (`pytest -m unit`)
- **Integration Tests**: Require MQTT broker (`pytest -m integration`)
- **Coverage**: 78% overall (core modules: 94-100%)

---

## Phase 1 Scope

✅ MQTT connection and authentication  
✅ Status publishing with heartbeat  
✅ Last Will and Testament (LWT)  
✅ Graceful shutdown  
✅ Configuration from environment  
✅ Unit tests  

❌ Component management (Phase 2)  
❌ Command subscriptions (Phase 2)  
❌ Production registry (Phase 2)
