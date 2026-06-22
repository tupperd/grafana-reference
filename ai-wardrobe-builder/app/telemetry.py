"""Telemetry wiring for Grafana Cloud AI Observability (Sigil) + OpenTelemetry.

Two hard rules baked in here:
  1. OTel TracerProvider/MeterProvider MUST be set before the Sigil client is
     constructed, or gen_ai.* metrics/traces are silently dropped.
  2. The app must run fine with Sigil/OTel unconfigured (graceful no-op), so you
     can build and test the app before wiring up Grafana Cloud.
"""
import logging
from contextlib import contextmanager

from . import config

log = logging.getLogger("wardrobe.telemetry")

_sigil_client = None
_tp = None
_mp = None
_initialized = False


class _NoOpRecorder:
    """Stand-in recorder when Sigil is not configured."""

    def set_result(self, *args, **kwargs):  # noqa: D401 - matches SDK surface
        return None

    def err(self):
        return None


def init_telemetry() -> None:
    global _sigil_client, _tp, _mp, _initialized
    if _initialized:
        return
    _initialized = True

    # 1) OTel providers FIRST (order matters - see module docstring).
    if config.OTEL_ENABLED:
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({"service.name": config.OTEL_SERVICE_NAME})
            _tp = TracerProvider(resource=resource)
            _tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            trace.set_tracer_provider(_tp)
            _mp = MeterProvider(
                resource=resource,
                metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
            )
            metrics.set_meter_provider(_mp)
            log.info(
                "OTel traces+metrics enabled -> %s",
                config.OTEL_EXPORTER_OTLP_ENDPOINT,
            )
        except Exception as e:  # pragma: no cover - defensive
            log.warning("OTel setup failed (%s); continuing without traces/metrics", e)
            _tp = _mp = None
    else:
        log.info("OTel disabled (OTEL_EXPORTER_OTLP_ENDPOINT unset)")

    # 2) Sigil generation-export client.
    if config.SIGIL_ENABLED:
        try:
            from sigil_sdk import (
                AuthConfig,
                Client,
                ClientConfig,
                GenerationExportConfig,
            )

            _sigil_client = Client(
                ClientConfig(
                    generation_export=GenerationExportConfig(
                        protocol=config.SIGIL_PROTOCOL,
                        endpoint=config.SIGIL_ENDPOINT,
                        auth=AuthConfig(
                            mode=config.SIGIL_AUTH_MODE,
                            tenant_id=config.SIGIL_AUTH_TENANT_ID,
                            basic_password=config.SIGIL_AUTH_TOKEN,
                        ),
                    ),
                    tags={"app": "wardrobe-ai", "env": "local"},
                )
            )
            log.info("Sigil AI Observability enabled -> %s", config.SIGIL_ENDPOINT)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("Sigil client setup failed (%s); running without export", e)
            _sigil_client = None
    else:
        log.info(
            "Sigil disabled (SIGIL_* unset) - LLM works, but nothing reaches Grafana Cloud"
        )


def status() -> dict:
    return {"sigil_enabled": _sigil_client is not None, "otel_enabled": _tp is not None}


@contextmanager
def generation(start):
    """Record one LLM call as a Sigil generation. No-op recorder if unconfigured."""
    if _sigil_client is None:
        yield _NoOpRecorder()
        return
    with _sigil_client.start_generation(start) as rec:
        yield rec


def shutdown() -> None:
    """Flush + close on app shutdown. shutdown() is synchronous in the SDK."""
    try:
        if _sigil_client is not None:
            _sigil_client.shutdown()
    except Exception as e:  # pragma: no cover
        log.warning("Sigil shutdown error: %s", e)
    for provider in (_tp, _mp):
        try:
            if provider is not None:
                provider.shutdown()
        except Exception:  # pragma: no cover
            pass
