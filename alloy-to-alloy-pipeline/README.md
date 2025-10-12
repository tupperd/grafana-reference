## Use Case

This demonstrates sending logs from one Alloy instance to another. This particular example assumes that both Alloy instances are running in the same k8s cluster.

The instructions below allow you to deploy the upstream and downstream Alloy instances, a log generator to generate some test logs, and a secrets file to allow logs to be sent to Grafana Cloud, if desired.

## Instructions 

### Create secrets file
(Optional) Create a namespace for the Alloy instances:
```python
kubectl create namespace <NAMESPACE>
```
```python
kubectl apply --namespace <NAMESPACE> -f secret.yaml
```

### Create upstream / downstream Alloy instances
```python
helm repo add grafana https://grafana.github.io/helm-charts
```
```python
helm repo update
```
Install the downstream Alloy:
```python
helm install --namespace <NAMESPACE> downstream grafana/alloy
```
Install the upstream Alloy:
```python
helm install --namespace <NAMESPACE> upstream grafana/alloy
```
Upgrade upstream / downstream Alloy instances:

```python
helm upgrade --namespace <NAMESPACE> downstream grafana/alloy -f downstream-alloy.yaml
```
```python
helm upgrade --namespace <NAMESPACE> upstream grafana/alloy -f upstream-alloy.yaml
```

Verify that the Alloy pods are running:
```python
kubectl get pods --namespace <NAMESPACE>
```

### Create log generator
```python
kubectl apply --namespace <NAMESPACE> -f log-generator.yaml 
```

## Reference Docs
https://grafana.com/docs/alloy/latest/set-up/install/kubernetes/
https://grafana.com/docs/alloy/latest/configure/kubernetes/