#!/bin/bash

helm delete downstream -n alloy-to-alloy
helm delete upstream -n alloy-to-alloy

kubectl delete deployment log-generator -n alloy-to-alloy

kubectl delete ns alloy-to-alloy