import json
import logging
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from aiokafka import AIOKafkaProducer

from ..Config import app_config

log = logging.getLogger(__name__)


class Topic(StrEnum):
    JOB_EVENTS = "job.events"
    FETCH_EVENTS = "fetch.events"
    FETCH_FAILURES = "fetch.failures"
    PARSE_ERRORS = "parse.errors"


class EventLog:
    def __init__(self, fallback_path: Path = Path("logs/events-fallback.jsonl")) -> None:
        self._producer: Optional[AIOKafkaProducer] = None
        self.fallback_path = fallback_path

    async def start(self) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=app_config.kafka_bootstrap,
            key_serializer=lambda k: k.encode(),
            value_serializer=lambda v: json.dumps(v, default=str).encode(),
        )
        try:
            await producer.start()
            self._producer = producer
        except Exception as error:
            log.warning("Kafka unavailable, events go to %s: %s", self.fallback_path, error)
            await producer.stop()

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def emit(self, topic: Topic, key: str, event: dict[str, Any]) -> None:
        event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
        if self._producer:
            try:
                await self._producer.send_and_wait(topic, event, key=key)
                return
            except Exception as error:
                log.warning("Kafka send failed, writing event to fallback file: %s", error)
        self._write_fallback(topic, key, event)

    def _write_fallback(self, topic: Topic, key: str, event: dict[str, Any]) -> None:
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with self.fallback_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"topic": topic, "key": key, "event": event}, default=str) + "\n")


events = EventLog()
