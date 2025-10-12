## Use Case

This demonstrates sending logs from one Alloy instance to another. This particular example assumes that both Alloy instances are running in the same k8s cluster.

The instructions below allow you to deploy the upstream and downstream Alloy instances, a log generator to generate some test logs, and a secrets file to allow logs to be sent to Grafana Cloud, if desired.

## Instructions 

### Create secrets file / namespace 
Create a namespace and secret:
```bash
kubectl create namespace alloy-to-alloy
kubectl apply --namespace alloy-to-alloy -f secret.yaml
```
Be sure to change the loki_username and loki_api_key fields in the secret.yaml file to your actual values.

### Create upstream / downstream Alloy instances
```bash
helm repo add grafana https://grafana.github.io/helm-charts
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

## Troubleshooting
### Invalid credentials 401 error
If logs do not reach Grafana Cloud, and you are seeing 401 errors in your downstream Alloy instance, check that the credentials in your secrets file are correct with this command:
```bash
# Replace 815040 with your stack ID and glc_xxx with your actual token     
TS=$(date +%s%N)

curl -u <LOKI_USERNAME>:<API_TOKEN> \
  -H 'Content-Type: application/json' \
  -X POST <GC_LOKI_ENDPOINT> \
  -d "{\"streams\":[{\"stream\":{\"test\":\"ok\"},\"values\":[[\"$TS\",\"hello from curl\"]]}]}"
```


## Reference Docs
https://grafana.com/docs/alloy/latest/set-up/install/kubernetes/
https://grafana.com/docs/alloy/latest/configure/kubernetes/