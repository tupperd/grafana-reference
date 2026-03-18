FROM grafana/grafana:12.2.0-ubuntu

USER root

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*

# DuckDB CLI for Linux ARM64 (aarch64)
ARG DUCKDB_VERSION=v1.2.1
RUN curl -fsSL \
      "https://github.com/duckdb/duckdb/releases/download/${DUCKDB_VERSION}/duckdb_cli-linux-aarch64.zip" \
      -o /tmp/duckdb.zip \
    && unzip /tmp/duckdb.zip -d /tmp/ \
    && mv /tmp/duckdb /usr/local/bin/duckdb \
    && chmod +x /usr/local/bin/duckdb \
    && rm /tmp/duckdb.zip \
    && duckdb --version

USER grafana
