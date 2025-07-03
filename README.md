# MassBank-charts
This repo contains the different helm charts to deploy a full MassBank software system.

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

To install, we recommend keeping (local) values files with the variables and real passwords:
```
helm install massbank ./massbank-frontend/ -f msbi-values.yaml -n massbank
```
and later updates can be performed via 
```
helm upgrade massbank ./massbank-frontend/ --version v2025.06.2 -f msbi-values.yaml -n massbank
```
