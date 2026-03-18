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

## Development

When changing something, you can check nothing broke via `helm lint massbank-frontend`,
and you could dry-run a helm action to see the resulting k8s yaml files via `helm upgrade massbank ./massbank-frontend ... --dry-run`.
(Note: the sub-charts like massbank-api or massbank-similarity-api are
usually NOT deployed separately, but come in as dependencies of
massbank-frontend.)
