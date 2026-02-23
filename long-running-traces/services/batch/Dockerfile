FROM python:3.12-slim

# pymssql uses FreeTDS — available for arm64 via standard apt
RUN apt-get update && apt-get install -y --no-install-recommends \
        freetds-dev freetds-bin \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY batch_runner.py .

EXPOSE 8001

CMD ["python", "batch_runner.py"]
