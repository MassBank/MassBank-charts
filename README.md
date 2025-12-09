# MassBank-charts
This repo contains the different helm charts to deploy a full MassBank software system into a Kubernetes instance.

## Charts Overview

- **massbank-frontend**: The main frontend application (includes massbank-api and massbank-export-api as dependencies)
- **massbank-api**: The backend API service (includes postgresql and massbank-similarity-api as dependencies)
- **massbank-export-api**: Export API service
- **massbank-similarity-api**: Similarity search API service
- **massbank-dbtool**: Database initialization tool (deployed separately)
- **massbank-data**: Shared data volume chart (optional, for deploying all services together)

## Deployment Modes

### Standalone Deployment (Default)
In standalone mode, each service downloads its own copy of MassBank-data using initContainers or environment variables. This is the default behavior and works well for individual service deployments.

### Shared Data Deployment (Recommended for Full Stack)
When deploying all services together, you can use the `massbank-data` chart to create a shared PersistentVolumeClaim (PVC) that all services can mount. This approach:
- Reduces storage requirements (single copy of data)
- Speeds up deployment (data downloaded once)
- Ensures data consistency across services

To enable shared data mode, see the `massbank-shared-data-example.yaml` file for configuration example.

## Development

After clonging this repo, the chart dependencies need to be updated:

```
helm repo add bitnami https://charts.bitnami.com/bitnami # Only needed once
helm dependency build massbank-api
helm dependency build massbank-frontend
```

When changing something, you can check nothing broke via `helm lint massbank-frontend`,
and you could dry-run a helm action to see the resulting k8s yaml files via `helm upgrade massbank ./massbank-frontend ... --dry-run`.
(Note: the sub-charts like massbank-api or massbank-similarity-api are
usually NOT deployed separately, but come in as dependencies of
massbank-frontend.)

## Installation

### Standalone Deployment
To install with standalone data downloads (default), we recommend keeping (local) values files with the variables and real passwords:
```
helm install massbank ./massbank-frontend/ -f msbi-values.yaml -n massbank
```

### Shared Data Deployment
To install with shared data volume:
```bash
# Install with shared data enabled
helm install massbank ./massbank-frontend/ -f massbank-shared-data-example.yaml -n massbank

# After frontend is installed, deploy the dbtool to initialize the database
helm install massbank-dbtool ./massbank-dbtool/ \
  --set useSharedData=true \
  --set sharedDataPvcName=massbank-massbank-data-pvc \
  --set massbankReleaseName=massbank \
  -n massbank
```

### Upgrading
Later updates can be performed via:
```
helm upgrade massbank ./massbank-frontend/ --version v2025.06.2 -f msbi-values.yaml -n massbank
```

## Configuration Options

### massbank-data Chart
- `enabled`: Enable/disable the massbank-data chart (default: false)
- `storageSize`: Size of the PVC (default: 1Gi, recommended: 5Gi for production)

### Service Configuration (massbank-export-api, massbank-similarity-api)
- `useSharedData`: Enable shared data mode (default: false)
- `sharedDataPvcName`: Name of the massbank-data PVC to mount (required when useSharedData is true)

### massbank-dbtool Configuration
- `useSharedData`: Use shared data PVC instead of git clone (default: false)
- `sharedDataPvcName`: Name of the massbank-data PVC to mount (required when useSharedData is true)

**Note**: The PVC name follows the pattern `<release-name>-massbank-data-pvc`. For a release named "massbank", the PVC name would be `massbank-massbank-data-pvc`.

