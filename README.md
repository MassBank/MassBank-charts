# MassBank-charts
This repo contains the helm charts to deploy a full MassBank software system into a Kubernetes instance. The charts are available from a helm repo. You can add them to your helm with:
```
helm repo add massbank https://massbank.github.io/MassBank-charts
```

## Update charts
Update to the latest charts with:
```
helm repo update
```

## Install
Take a look into the example value files in the root of this repo. This
app is deployed via an umbrella chart `massbank`. 

First create a secret with the database password:
```
kubectl create secret generic postgres-pw -n massbank \
  --from-literal=password=postgresPassword
```
Then you can install the app with your custom values file:
```
helm install massbank -n massbank massbank/massbank -f msbi-values-dev.yaml
```
and later updates can be performed via 
```
helm upgrade massbank -n massbank massbank/massbank -f msbi-values-dev.yaml
```
