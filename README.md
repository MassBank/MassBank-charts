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

## Development Environment

A development container is configured under `.devcontainer/` and provides all necessary tools for Helm chart development (`helm`, plugins `diff` and `unittest`, `kubectl`, `yq`, `kubeconform`, `helm-docs`, and `chart-testing`).

See `.devcontainer/README.md` for instructions on opening the project in the development container and running commands there.

Opening the project in PyCharm does not start the devcontainer automatically. Open `.devcontainer/devcontainer.json` to create or connect to the devcontainer.
