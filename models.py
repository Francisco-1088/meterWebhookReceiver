from pydantic import BaseModel, ConfigDict
from typing import Any


class MeterMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    alert_name: str
    network_name: str = "Unknown"
    timestamp: str = ""


class MeterWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    metadata: MeterMetadata
    data: dict[str, Any] = {}
