## Use Case

This demonstrates sending logs from one Alloy instance to another. This particular example assumes that both Alloy instances are running in the same k8s cluster.

The instructions below allow you to deploy the upstream and downstream Alloy instances, a log generator to generate some test logs, and a secrets file to allow logs to be sent to Grafana Cloud, if desired.

## Instructions 

### Create secrets file
(Optional) Create a namespace for the Alloy instances:
```bash
kubectl create namespace alloy-to-alloy
```
```bash
kubectl apply --namespace alloy-to-alloy -f secret.yaml
```

### Create upstream / downstream Alloy instances
```bash
helm repo add grafana https://grafana.github.io/helm-charts
```
```bash
helm repo update
```
Install the upstream / downstream Alloy:
```bash
helm install --namespace alloy-to-alloy downstream grafana/alloy
helm install --namespace alloy-to-alloy upstream grafana/alloy
```
Upgrade upstream / downstream Alloy instances:
```bash
helm upgrade --namespace alloy-to-alloy downstream grafana/alloy -f downstream-alloy.yaml
helm upgrade --namespace alloy-to-alloy upstream grafana/alloy -f upstream-alloy.yaml
```

Verify that the Alloy pods are running:
```bash
kubectl get pods --namespace alloy-to-alloy
```

### Create log generator
```bash
kubectl apply --namespace alloy-to-alloy -f log-generator.yaml 
```


## Cleaup

When you're finished with this demo, you can clean up the resources by running the following commands:
```bash
chmod +x teardown.sh
./teardown.sh
```

## Reference Docs
https://grafana.com/docs/alloy/latest/set-up/install/kubernetes/
https://grafana.com/docs/alloy/latest/configure/kubernetes/