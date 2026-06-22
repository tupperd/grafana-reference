"""Environment-driven settings. Loads .env once at import time so the OTLP
exporters (which read OTEL_* from os.environ) see the values before telemetry init."""
import os

from dotenv import load_dotenv

load_dotenv()

# macOS Python installs often ship without a usable CA bundle, which breaks the
# Sigil HTTP exporter's TLS verification (SSL: CERTIFICATE_VERIFY_FAILED). Point
# urllib at certifi's bundle unless the user already set their own.
if not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except Exception:  # pragma: no cover - certifi is a transitive dep, should exist
        pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# --- Light auth (plaintext is intentional for a local learning app) ---
APP_USERNAME = _get("APP_USERNAME", "admin")
APP_PASSWORD = _get("APP_PASSWORD", "wardrobe")
SESSION_SECRET = _get("SESSION_SECRET", "dev-insecure-secret-change-me")

# --- Local OSS LLM (Ollama, OpenAI-compatible endpoint) ---
OLLAMA_BASE_URL = _get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.2:3b")
LLM_PROVIDER = _get("LLM_PROVIDER", "ollama")  # recorded as the Sigil model provider

# --- Storage ---
DB_PATH = _get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wardrobe.db"),
)

# --- Sigil generation export (Grafana Cloud AI Observability) ---
SIGIL_ENDPOINT = _get("SIGIL_ENDPOINT")
SIGIL_PROTOCOL = _get("SIGIL_PROTOCOL", "http")
SIGIL_AUTH_MODE = _get("SIGIL_AUTH_MODE", "basic")
SIGIL_AUTH_TENANT_ID = _get("SIGIL_AUTH_TENANT_ID")
SIGIL_AUTH_TOKEN = _get("SIGIL_AUTH_TOKEN")

# --- OTel traces + metrics (exporters read OTEL_EXPORTER_OTLP_* from env) ---
OTEL_EXPORTER_OTLP_ENDPOINT = _get("OTEL_EXPORTER_OTLP_ENDPOINT")
OTEL_SERVICE_NAME = _get("OTEL_SERVICE_NAME", "wardrobe-ai")

SIGIL_ENABLED = bool(SIGIL_ENDPOINT and SIGIL_AUTH_TENANT_ID and SIGIL_AUTH_TOKEN)
OTEL_ENABLED = bool(OTEL_EXPORTER_OTLP_ENDPOINT)
