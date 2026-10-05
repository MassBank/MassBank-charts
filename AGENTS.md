# Agent guidance for MassBank-charts

## Repository purpose and layout

This repository packages Helm charts for deploying the MassBank system to Kubernetes.
The main installation is the `massbank` umbrella chart at `charts/massbank`; its
`Chart.yaml` declares dependencies on the API, frontend, data, export API, similarity
API, dbtool, and PostgreSQL charts. Source charts live under `charts/`, while
`msbi-values.yaml`, `msbi-values-dev.yaml`, and `massbank.eu-values.yaml` are
example deployment configuration files at the repository root.

Read the root `README.md` and the relevant chart's `Chart.yaml`, `values.yaml`, and
templates before changing chart behavior. Run local chart commands from the repository
root using `./charts/<chart>` paths. The README shows how to lint the frontend chart
and render the complete `massbank` umbrella chart with development values.

## Helm conventions

- Keep the umbrella chart's dependency declarations, `Chart.lock`, and vendored
  archives under `charts/massbank/charts/` consistent. Avoid changing dependency
  versions or refreshing dependencies unless the task requires it.
- Preserve the existing chart helper, naming, labels, and template conventions in
  each chart's `templates/_helpers.tpl` and templates.
- Umbrella values use YAML anchors for shared host, path prefix, and database
  settings. Preserve those shared values and update all affected subchart values
  when changing cross-chart configuration.
- The data PVC name is shared by multiple services through `sharedDataPvcName`.
  Keep its naming and mount configuration synchronized across dependent charts.
- PostgreSQL credentials are expected via the pre-created `postgres-pw` Secret;
  do not add passwords, tokens, or other deployment secrets to tracked files.
- Chart versions are not uniform: some use date-like versions and others semantic
  versions. Follow the existing chart's versioning convention rather than
  normalizing versions across the repository.

## Making changes

- Keep changes scoped to the relevant chart, and consider both direct chart use and
  umbrella-chart use when editing a subchart.
- When changing values, check the chart defaults, templates, and example values for
  compatibility. Do not assume root example values are production credentials or
  copy real deployment secrets into examples.
- For dependency changes, update the dependency declaration and lock/archive state
  deliberately; do not hand-edit a packaged `.tgz` as if it were source.
- Avoid unrelated formatting or generated-file changes. No CI workflow or dedicated
  test suite is currently documented, so record any additional manual validation
  needed in the change summary.

## Validation

Run Helm lint on every chart changed and on the umbrella chart when applicable. For
example, from the repository root:

```sh
helm lint ./charts/massbank
helm lint ./charts/massbank-api
```

Render manifests to check template output when relevant:

```sh
helm template massbank ./charts/massbank -f msbi-values-dev.yaml
```

Use the appropriate example values file for the target environment, and do not
include secret values in command output or commits. A cluster-backed install/upgrade
or `helm test` requires a suitable Kubernetes environment and should not be assumed
to be available for local validation.

## Development Environment & Container Execution

All Helm chart development and AI Agent tasks must run inside the devcontainer environment configured under `.devcontainer/`.

- When executing commands or automated validation as an AI Agent, run inside the Podman devcontainer using:
  ```sh
  ./.devcontainer/run.sh <command>
  ```
- Alternatively, run commands directly inside an active container shell where all tools (`helm`, plugins `diff` and `unittest`, `kubectl`, `yq`, `kubeconform`, `ct`, `helm-docs`, `yamllint`) are preinstalled and configured.

