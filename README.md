# MassBank-charts
This repo contains the helm charts to deploy a full MassBank software system into a Kubernetes instance. 

## Installing MassBank from helm repo

The charts are available from our helm repo. You can add them to your helm with:
```
helm repo add massbank https://massbank.github.io/MassBank-charts
```
and update them later with:
```
helm repo update
```

The whole installation is triggered by installing the umbrella chart `massbank`.
To install, we recommend keeping (local) values files with the helm variables and real passwords:
```
helm install massbank massbank/massbank -f msbi-values.yaml -n massbank
```
and later updates can be performed via 
```
helm upgrade massbank massbank/massbank --version v2025.06.2 -f msbi-values.yaml -n massbank
```
Some example values files can be found in the root of this repo.

## Shared JPA database

The umbrella chart uses one PostgreSQL database for the API and export API.
Only the export API's `/app-import.jar` creates the JPA tables and imports the
records. The legacy `massbank-dbtool` is no longer an umbrella dependency.
PostgreSQL initialization installs Bingo in the shared database; the importer
adds the API's live read views and Bingo index. The frontend's internal and
public API URLs target these two services, not the old databases.

The example values use one `massbankDatabase` YAML anchor for
`postgres.auth.database`, `massbank-api.massbankApiDatabase`, and
`massbank-export-api.massbankExportApiDatabase`. All three must match; inconsistent
overrides fail chart rendering. When using `--set`, override all three resolved
values rather than only the top-level anchor.

This branch pins the tested `test-shared-jpa-<commit>` Quay images; it is not a
production release. The changed subcharts use local `file://` dependencies so
their source and packaged versions can be tested before publishing releases:

```sh
helm dependency build ./charts/massbank
helm lint ./charts/massbank-api ./charts/massbank-export-api ./charts/massbank
helm unittest ./charts/massbank-api ./charts/massbank-export-api ./charts/massbank
helm template massbank-dev ./charts/massbank -n massbank-dev -f msbi-values-dev.yaml
```

### Upgrading the development deployment

`msbi-values-dev.yaml` configures the complete system at
**https://msbi.ipb-halle.de/MassBank3/**, using `massbank_shared` and the full
dataset on `massbank-dev-massbank-data-pvc`. It preserves the existing CSP-enabled
frontend image. The older `massbank` and `records` databases are not removed.

PostgreSQL init scripts run only for an empty data volume. For an existing PVC,
first create `massbank_shared` owned by `massbank`, run the installed
`/opt/bingo-postgres/init-scripts/000_bingo_install.sql` in that database, and set
`bingo.bingo_config.ALLOW_NON_UNIQUE_DEAROMATIZATION` to `1`. Use administrator
access for this provisioning; keep credentials in the existing `postgres-pw`
Secret. No record tables or records are created by this provisioning step.

When changing `postgres.auth.database` on an existing release, first roll the
PostgreSQL StatefulSet to the matching `POSTGRES_DB` environment value and wait
for it to be ready. This prevents its restart from interrupting the new import.
Then run:

```sh
helm upgrade massbank-dev ./charts/massbank -n massbank-dev \
  -f msbi-values-dev.yaml --reset-values --wait --wait-for-jobs --timeout 2h
```

The export API waits for the import completion marker before starting. The Go
API's readiness probe checks the database, not just its version endpoint. Both
API Deployments restart when their connection ConfigMaps change.

Imports **replace** the configured dataset and require a maintenance window.
Jobs use a chart-versioned name, no automatic retry, and no default TTL: retaining
the completed Job prevents an ordinary same-version upgrade from repeating the
import. A new export chart version creates a new import Job. Set
`massbank-export-api.dataImport.enabled=false` for upgrades that must not import
data, or deliberately delete only the named import Job to rerun it. Disabling
the importer never re-enables dbtool.

## Development Environment

A development container with Podman is configured under `.devcontainer/` providing all necessary tools for Helm chart development (`helm`, plugins `diff` and `unittest`, `kubectl`, `yq`, `kubeconform`, `helm-docs`, and `chart-testing`).

To open a shell or run commands inside the container using Podman:
```bash
./.devcontainer/run.sh
./.devcontainer/run.sh helm lint ./charts/massbank-frontend
```

See `.devcontainer/README.md` for complete documentation.

Opening the project in PyCharm does not start the devcontainer automatically. Open `.devcontainer/devcontainer.json` to create or connect to the devcontainer. The helper script above starts separate, disposable containers for commands and shells.
