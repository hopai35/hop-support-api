"""
Hop Support - Zendesk CRM Provider

Integrates with Zendesk API for ticket management.
Uses the Zendesk API v2.

Environment variables:
- ZENDESK_SUBDOMAIN: Your Zendesk subdomain (e.g., "mycompany")
- ZENDESK_EMAIL: Admin email for API authentication
- ZENDESK_API_TOKEN: API token for authentication
"""

import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

import requests

from .base import BaseCRMProvider, Ticket

logger = logging.getLogger(__name__)


class ZendeskProvider(BaseCRMProvider):
    """
    Zendesk CRM integration.

    Supports creating, reading, updating tickets, and adding comments/notes.
    Falls back to mock mode if API credentials are not configured.
    """

    def __init__(
        self,
        subdomain: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.subdomain = subdomain or os.getenv("ZENDESK_SUBDOMAIN", "")
        self.email = email or os.getenv("ZENDESK_EMAIL", "")
        self.api_token = api_token or os.getenv("ZENDESK_API_TOKEN", "")

        self._configured = bool(self.subdomain and self.email and self.api_token)
        if self._configured:
            self.base_url = f"https://{self.subdomain}.zendesk.com/api/v2"
            self.auth = (f"{self.email}/token", self.api_token)
            logger.info(f"ZendeskProvider configured for {self.subdomain}.zendesk.com")
        else:
            logger.warning(
                "ZendeskProvider not configured (missing ZENDESK_SUBDOMAIN, "
                "ZENDESK_EMAIL, or ZENDESK_API_TOKEN). "
                "Set env vars to enable real Zendesk integration."
            )

    def get_name(self) -> str:
        return "zendesk"

    def _check_configured(self):
        """Raise if not configured."""
        if not self._configured:
            raise RuntimeError(
                "Zendesk is not configured. Set ZENDESK_SUBDOMAIN, "
                "ZENDESK_EMAIL, and ZENDESK_API_TOKEN environment variables."
            )

    def _parse_ticket(self, zd_ticket: dict) -> Ticket:
        """Convert a Zendesk API ticket dict to our Ticket model."""
        ticket = Ticket(
            subject=zd_ticket.get("subject", ""),
            description=zd_ticket.get("description", ""),
            requester_email="",
            requester_name=zd_ticket.get("requester_id", ""),
            priority=zd_ticket.get("priority", "normal"),
            status=zd_ticket.get("status", "new"),
            tags=zd_ticket.get("tags", []),
            custom_fields={
                cf["id"]: cf["value"]
                for cf in zd_ticket.get("custom_fields", [])
            },
            external_id=zd_ticket.get("external_id"),
        )
        ticket.id = str(zd_ticket.get("id", ""))
        return ticket

    def create_ticket(self, ticket: Ticket) -> Ticket:
        self._check_configured()
        payload = {
            "ticket": {
                "subject": ticket.subject,
                "description": ticket.description,
                "priority": ticket.priority,
                "tags": ticket.tags,
                "external_id": ticket.external_id,
                "requester": {
                    "name": ticket.requester_name,
                    "email": ticket.requester_email,
                },
            }
        }

        resp = requests.post(
            f"{self.base_url}/tickets.json",
            json=payload,
            auth=self.auth,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        created = self._parse_ticket(data["ticket"])
        logger.info(f"Zendesk ticket created: {created.id}")
        return created

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        self._check_configured()
        try:
            resp = requests.get(
                f"{self.base_url}/tickets/{ticket_id}.json",
                auth=self.auth,
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_ticket(resp.json()["ticket"])
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 404:
                logger.warning(f"Zendesk ticket not found: {ticket_id}")
                return None
            raise

    def update_ticket(
        self, ticket_id: str, updates: Dict[str, Any]
    ) -> Optional[Ticket]:
        self._check_configured()
        payload = {"ticket": {}}
        for key in ("subject", "description", "priority", "status", "tags"):
            if key in updates:
                payload["ticket"][key] = updates[key]

        if not payload["ticket"]:
            return self.get_ticket(ticket_id)

        resp = requests.put(
            f"{self.base_url}/tickets/{ticket_id}.json",
            json=payload,
            auth=self.auth,
            timeout=30,
        )
        resp.raise_for_status()
        return self._parse_ticket(resp.json()["ticket"])

    def add_comment(
        self, ticket_id: str, comment: str, is_public: bool = True
    ) -> bool:
        self._check_configured()
        payload = {
            "ticket": {
                "comment": {
                    "body": comment,
                    "public": is_public,
                }
            }
        }
        resp = requests.put(
            f"{self.base_url}/tickets/{ticket_id}.json",
            json=payload,
            auth=self.auth,
            timeout=30,
        )
        resp.raise_for_status()
        visibility = "public" if is_public else "private"
        logger.info(f"Zendesk {visibility} comment added to ticket {ticket_id}")
        return True

    def find_tickets_by_email(self, email: str) -> List[Ticket]:
        self._check_configured()
        resp = requests.get(
            f"{self.base_url}/search.json",
            params={"query": f"type:ticket requester:{email}"},
            auth=self.auth,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_ticket(t) for t in data.get("results", [])]

    def health_check(self) -> Dict[str, Any]:
        if not self._configured:
            return {
                "provider": self.get_name(),
                "status": "not_configured",
                "message": "Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN",
            }
        try:
            resp = requests.get(
                f"{self.base_url}/account.json",
                auth=self.auth,
                timeout=10,
            )
            if resp.status_code == 200:
                return {"provider": self.get_name(), "status": "ok"}
            return {
                "provider": self.get_name(),
                "status": "error",
                "code": resp.status_code,
            }
        except Exception as e:
            return {"provider": self.get_name(), "status": "error", "message": str(e)}