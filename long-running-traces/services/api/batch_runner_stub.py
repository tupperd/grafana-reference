"""
Lightweight shim — the API container calls this when /api/batch/trigger is hit.
It simply makes an HTTP call to the batch service's trigger endpoint so the
real batch runner (with its own OTel service name) emits the trace.
"""
import os
import requests

BATCH_URL = os.environ.get("BATCH_SERVICE_URL", "http://foo-batch:8001/run")
try:
    requests.post(BATCH_URL, timeout=5)
except Exception as e:
    print(f"[stub] batch trigger failed: {e}")
