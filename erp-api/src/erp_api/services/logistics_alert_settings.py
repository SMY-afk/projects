"""Tenant-scoped warning settings stored atomically on the persistent ERP volume."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AlertSettings(BaseModel):
    leadHours: float = Field(default=3, gt=0, lt=48, allow_inf_nan=False)
    updatedAt: datetime | None = None


class LogisticsAlertSettings:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("LOGISTICS_ALERT_SETTINGS_DIR", "/app/var/logistics-alert-settings"))

    def path(self, tenant):
        return self.root / (str(UUID(str(tenant))) + ".json")

    def read(self, tenant):
        path = self.path(tenant)
        if not path.exists():
            return AlertSettings()
        return AlertSettings.model_validate_json(path.read_bytes())

    def write(self, tenant, hours, actor):
        settings = AlertSettings(leadHours=hours, updatedAt=datetime.now(UTC))
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path(tenant)
        temporary = target.with_suffix("." + uuid4().hex + ".tmp")
        payload = {**settings.model_dump(mode="json"), "updatedBy": str(actor)}
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
            if os.name != "nt":
                directory = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return self.read(tenant)
