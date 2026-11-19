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

### Using Podman CLI

```bash
# Build the image
podman build -t massbank-charts-dev -f .devcontainer/Dockerfile .devcontainer

# Run container with rootless user namespace mapping and workspace volume mount
podman run -it --rm \
  --userns=keep-id:uid=1000,gid=1000 \
  --security-opt label=disable \
  -v "$PWD":/workspaces/MassBank-charts:Z \
  -w /workspaces/MassBank-charts \
  massbank-charts-dev bash
```

### Option 3: In PyCharm or VS Code

- **PyCharm**: Select Podman under **Settings -> Build, Execution, Deployment -> Docker** (or configure `/run/user/1000/podman/podman.sock`). Open `.devcontainer/devcontainer.json`, use the gutter action **Create Dev Container -> Create Dev Container and Mount Sources**, select the IDE backend, and connect when it is ready. Merely opening the project does not start or switch to the devcontainer automatically; start/connect to it from the IDE.
- **VS Code**: Ensure the *Dev Containers* extension is installed. Configure Podman in VS Code settings (`"dev.containers.dockerPath": "podman"`). Run **Dev Containers: Reopen in Container**.

The configuration disables Dev Containers' automatic remote-user UID/GID rewrite (`updateRemoteUserUID: false`). With rootless Podman, the build-time recursive `chown` can fail for files in the base image.

Use `--userns=keep-id:uid=1000,gid=1000` so the host user is mapped to the image user `vscode` (1000/1000). Bare `--userns=keep-id` keeps the host numeric IDs, which breaks writes for UIDs that are not 1000. `--security-opt=label=disable` supports JetBrains with SELinux alongside the `:Z` workspace mount.

### Using an IDE

Use native Dev Container support in PyCharm (**Settings -> Advanced Settings -> Open devcontainer projects natively**) or VS Code's **Dev Containers: Reopen in Container** command. The IDE runs on the host and uses the container directly for tooling and runtime operations; settings, sign-ins, and chat histories remain with the host IDE.

Run development and validation commands from a shell inside the running devcontainer. When using an AI agent, attach its runner to that container so commands use the same environment.
