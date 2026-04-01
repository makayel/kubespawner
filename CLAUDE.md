# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

### Python Virtual Environment

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies for development
pip install -e ".[test]"
```

## Development Commands

```bash
# Run all tests
pytest

# Run all tests
pytest

# Run a specific test file
pytest tests/test_spawner.py

# Format Python code
black kubespawner tests
isort kubespawner tests

# Format Jinja templates
djlint --reformat kubespawner/templates/
```

## Architecture Overview

**KubeSpawner** is a JupyterHub spawner that creates user notebook servers as Kubernetes Pods.

### Core Components

1. **kubespawner/spawner.py** - Main `KubeSpawner` class that extends JupyterHub's `Spawner`. Handles:
   - Pod lifecycle management (start, stop, poll)
   - Configuration through traitlets
   - Expansion of user properties in templates
   - Integration with JupyterHub's proxy system

2. **kubespawner/objects.py** - Helper functions to construct Kubernetes API objects:
   - `make_pod()` - Creates pod specifications from spawner config
   - `make_pvc()` - Creates persistent volume claims
   - `make_secret()`, `make_service()`, `make_ingress()` - Resource builders

3. **kubespawner/reflector.py** - `ResourceReflector` class that watches Kubernetes resources via the API server and maintains a local cache:
   - `PodReflector` - Tracks pods in the namespace
   - `EventReflector` - Tracks Kubernetes events
   - Uses watch API with reconnection logic on timeouts

4. **kubespawner/clients.py** - Manages shared Kubernetes API client instances:
   - `shared_client()` - Caches clients per asyncio loop + args
   - `load_config()` - Loads k8s config (in-cluster or kubeconfig file)
   - Patches ThreadPool to avoid unused thread creation

5. **kubespawner/multicluster/** - Experimental support for multiple Kubernetes clusters:
   - `MultiClusterKubeSpawner` - Extends KubeSpawner with context-aware spawners
   - `MultiResourceReflector` - Cross-cluster resource reflection

### Key Design Patterns

- **Reflector Pattern**: Shared singleton reflectors track k8s state across multiple spawner instances, reducing API server load
- **Async-first**: Uses `kubernetes_asyncio` for non-blocking I/O
- **Template expansion**: User properties (e.g., `{{hub.user}}`) expanded through traitlets validation
- **Configuration via traitlets**: All spawner options defined as traitlets with validation and defaults

### Testing

Tests require a running Kubernetes cluster (e.g., minikube):
- Tests create real pods/services in the test namespace
- Use pytest fixtures from `tests/conftest.py`
- Configuration is in `tests/jupyterhub_config.py`
