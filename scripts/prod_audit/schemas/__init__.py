"""JSON Schema 资源子包。"""

from pathlib import Path

AUDIT_REPORT_SCHEMA_PATH: Path = Path(__file__).parent / "audit_report.schema.json"

__all__ = ["AUDIT_REPORT_SCHEMA_PATH"]
