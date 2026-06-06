"""
OpenTelemetry 可观测性配置

提供分布式追踪能力，与 Prometheus + Grafana 形成完整的可观测性三角。
启用条件：设置环境变量 OTEL_ENABLED=true
"""

import logging
import os

logger = logging.getLogger(__name__)

_tracer = None
_meter = None


def setup_telemetry(app=None):
    """初始化 OpenTelemetry

    生产环境默认启用，开发环境默认关闭。
    可通过 OTEL_ENABLED=true/false 显式覆盖。
    """
    global _tracer, _meter

    env = os.getenv("APP_ENV", "development")
    default_enabled = "true" if env == "production" else "false"
    if os.getenv("OTEL_ENABLED", default_enabled).lower() != "true":
        logger.info("OpenTelemetry 未启用（设置 OTEL_ENABLED=true 启用）")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", "binfa-erp")
        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv("APP_VERSION", "2.0.0"),
        })

        # Tracer
        trace.set_tracer_provider(TracerProvider(resource=resource))
        _tracer = trace.get_tracer(service_name)

        # Exporter: OTLP (生产默认) 或 Console
        default_exporter = "otlp" if env == "production" else "console"
        exporter_type = os.getenv("OTEL_EXPORTER_TYPE", default_exporter)
        if exporter_type == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            exporter = OTLPSpanExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
                insecure=True,
            )
        else:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            exporter = ConsoleSpanExporter()

        trace.get_tracer_provider().add_span_processor(
            BatchSpanProcessor(exporter)
        )

        # FastAPI Instrumentation
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)

        # SQLAlchemy Instrumentation
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            SQLAlchemyInstrumentor().instrument()
        except ImportError:
            pass

        # Redis Instrumentation
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor
            RedisInstrumentor().instrument()
        except ImportError:
            pass

        # Requests Instrumentation (outgoing HTTP)
        try:
            from opentelemetry.instrumentation.requests import RequestsInstrumentor
            RequestsInstrumentor().instrument()
        except ImportError:
            pass

        logger.info("OpenTelemetry 已启用: service=%s, exporter=%s", service_name, exporter_type)

    except ImportError:
        logger.warning(
            "OpenTelemetry 依赖未安装。请运行: "
            "pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-instrumentation-fastapi "
            "opentelemetry-exporter-otlp-proto-grpc"
        )
    except (ValueError, OSError) as e:
        logger.warning("OpenTelemetry 初始化失败: %s", e)


def get_tracer():
    return _tracer


def shutdown_telemetry():
    """关闭 OpenTelemetry，刷新所有待发送的 span"""
    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'shutdown'):
            provider.shutdown()
    except (ImportError, ValueError, OSError) as e:
        logger.debug("OpenTelemetry 关闭异常（可忽略）: %s", e)
