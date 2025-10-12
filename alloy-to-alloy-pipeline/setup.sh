kubectl create namespace alloy-to-alloy
kubectl apply --namespace alloy-to-alloy -f secret.yaml

helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm install --namespace alloy-to-alloy downstream grafana/alloy
helm install --namespace alloy-to-alloy upstream grafana/alloy

helm upgrade --namespace alloy-to-alloy downstream grafana/alloy -f downstream-alloy.yaml
helm upgrade --namespace alloy-to-alloy upstream grafana/alloy -f upstream-alloy.yaml

kubectl apply --namespace alloy-to-alloy -f log-generator.yaml 