# MassBank-charts Devcontainer

This directory provides a complete development container configuration optimized for Helm chart development and AI Agent execution using **Podman** (or Docker).

## Features & Included Tools

The container is based on `mcr.microsoft.com/devcontainers/base:ubuntu26.04` and includes:

- **Helm 3**: Kubernetes package manager
- **Helm Plugins**:
  - `helm-diff`: Preview chart differences before deployment (`helm diff`)
  - `helm-unittest`: Unit test Helm charts locally in YAML (`helm unittest`)
  - MassBank Helm repository pre-configured (`https://massbank.github.io/MassBank-charts`)
- **Kubernetes Tooling**:
  - `kubectl`: Official Kubernetes CLI
  - `kubeconform`: Fast Kubernetes manifest validator against OpenAPI schemas
  - `chart-testing` (`ct`): Helm chart linting and testing tool with default schemas
  - `helm-docs`: Auto-generate documentation from Helm chart metadata and `values.yaml`
- **Data & Linting Utilities**:
  - `yq` and `jq`: YAML/JSON processors
  - `yamllint`: Linter for YAML files
  - `yamale`: Schema validator for YAML
- **Development Runtimes**:
  - Python 3 & pip/venv
  - Git, curl, wget, rsync, make, nano, vim
  - Bash completion configured for Helm and kubectl

## Using with Podman

### Option 1: Via the Helper Script (`.devcontainer/run.sh`)

A helper script is provided at `.devcontainer/run.sh` to run commands or start an interactive shell inside the container using Podman:

```bash
# Open an interactive shell inside the container
./.devcontainer/run.sh

# Lint a chart inside the container
./.devcontainer/run.sh helm lint ./charts/massbank-frontend

# Render templates with development values
./.devcontainer/run.sh helm template massbank ./charts/massbank -f msbi-values-dev.yaml

# Run chart-testing
./.devcontainer/run.sh ct lint --all

# Force rebuild of the container image
./.devcontainer/run.sh --build
```

### Option 2: Using Podman CLI Directly

```bash
# 1. Build the image
podman build -t massbank-charts-dev -f .devcontainer/Dockerfile .devcontainer

# 2. Run container with rootless user namespace mapping and workspace volume mount
podman run -it --rm \
  --userns=keep-id \
  --security-opt label=disable \
  -v "$PWD":/workspaces/MassBank-charts:Z \
  -w /workspaces/MassBank-charts \
  massbank-charts-dev bash
```

### Option 3: In PyCharm or VS Code

- **PyCharm**: Select Podman under **Settings -> Build, Execution, Deployment -> Docker** (or configure `/run/user/1000/podman/podman.sock`). Open `.devcontainer/devcontainer.json`, use the gutter action **Create Dev Container -> Create Dev Container and Mount Sources**, select the IDE backend, and connect when it is ready. Merely opening the project does not start or switch to the devcontainer automatically; start/connect to it from the IDE.
- **VS Code**: Ensure the *Dev Containers* extension is installed. Configure Podman in VS Code settings (`"dev.containers.dockerPath": "podman"`). Run **Dev Containers: Reopen in Container**.

The configuration disables Dev Containers' automatic remote-user UID/GID rewrite (`updateRemoteUserUID: false`). With rootless Podman, the build-time recursive `chown` can fail for files in the base image; Podman's `--userns=keep-id` remains configured for container runtime access.

### IDE state, sign-in, and chat history

When using native Dev Container support in PyCharm (**Settings -> Advanced Settings -> Open devcontainer projects natively**), the IDE runs on the host and uses the container directly for tooling and runtime operations. Settings, sign-ins (e.g. GitHub Copilot, JetBrains AI), and chat histories remain with your host IDE without requiring container-side volume persistence.

For disposable shells or commands, `.devcontainer/run.sh` starts a container with `--rm`.

## AI Agent Guidance

When an AI Agent is tasked with modifying or validating Helm charts in this repository:
- All commands (linting, templating, validation, chart updates) should be run inside this container environment.
- Use `./.devcontainer/run.sh <command>` to execute commands in the container from the host, or attach the agent runner directly to the running container.
