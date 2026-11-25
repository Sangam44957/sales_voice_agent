"""CRM adapter interface plus the MVP implementation (local table + optional webhook)."""
import logging
from typing import Protocol

import httpx

from app import config

log = logging.getLogger(__name__)


class CRMAdapter(Protocol):
    """Anything that can push a lead somewhere and return an external id."""

    def upsert_lead(self, lead: dict) -> str: ...


class LocalCRM:
    """Leads already live in SQLite; optionally POST them to CRM_WEBHOOK_URL (best effort)."""

    def upsert_lead(self, lead: dict) -> str:
        if config.CRM_WEBHOOK_URL:
            try:
                httpx.post(config.CRM_WEBHOOK_URL, json=lead, timeout=3)
            except httpx.HTTPError as e:  # CRM down must never break the call
                log.warning("CRM webhook failed: %s", type(e).__name__)
        return f"local-{lead['id']}"


crm: CRMAdapter = LocalCRM()
