"""
Hop Support - Salesforce CRM Provider

Integrates with Salesforce REST API for case management.

Environment variables:
- SF_CLIENT_ID: Salesforce OAuth client ID (Consumer Key)
- SF_CLIENT_SECRET: Salesforce OAuth client secret (Consumer Secret)
- SF_USERNAME: Salesforce username
- SF_PASSWORD: Salesforce password
- SF_SECURITY_TOKEN: Salesforce security token (or concatenate with password)
- SF_LOGIN_URL: Salesforce login URL (default: https://login.salesforce.com)
"""

import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

import requests

from .base import BaseCRMProvider, Ticket

logger = logging.getLogger(__name__)


class SalesforceProvider(BaseCRMProvider):
    """
    Salesforce CRM integration.

    Manages cases (tickets) via the Salesforce REST API.
    Uses OAuth 2.0 Password Grant for authentication.
    Falls back to mock mode if API credentials are not configured.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        security_token: Optional[str] = None,
        login_url: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("SF_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SF_CLIENT_SECRET", "")
        self.username = username or os.getenv("SF_USERNAME", "")
        self.password = password or os.getenv("SF_PASSWORD", "")
        self.security_token = security_token or os.getenv("SF_SECURITY_TOKEN", "")
        self.login_url = (
            login_url or os.getenv("SF_LOGIN_URL", "https://login.salesforce.com")
        )

        self._configured = bool(
            self.client_id and self.client_secret and self.username and self.password
        )
        self._access_token: Optional[str] = None
        self._instance_url: Optional[str] = None

        if self._configured:
            logger.info("SalesforceProvider configured (credentials present)")
        else:
            logger.warning(
                "SalesforceProvider not configured. "
                "Set SF_CLIENT_ID, SF_CLIENT_SECRET, SF_USERNAME, "
                "and SF_PASSWORD env vars."
            )

    def get_name(self) -> str:
        return "salesforce"

    def _check_configured(self):
        if not self._configured:
            raise RuntimeError(
                "Salesforce is not configured. Set SF_CLIENT_ID, SF_CLIENT_SECRET, "
                "SF_USERNAME, and SF_PASSWORD environment variables."
            )

    def _authenticate(self):
        """Authenticate with Salesforce and get access token."""
        if self._access_token and self._instance_url:
            return

        pw = self.password
        if self.security_token:
            pw = f"{self.password}{self.security_token}"

        resp = requests.post(
            f"{self.login_url}/services/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": self.username,
                "password": pw,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._instance_url = data["instance_url"]
        logger.info("Salesforce authentication successful")

    def _headers(self) -> Dict[str, str]:
        """Get auth headers for Salesforce API calls."""
        self._authenticate()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _parse_case(self, case: dict) -> Ticket:
        """Convert a Salesforce Case object to our Ticket model."""
        ticket = Ticket(
            subject=case.get("Subject", ""),
            description=case.get("Description", ""),
            requester_email=case.get("SuppliedEmail", ""),
            requester_name=case.get("ContactName", ""),
            priority=(case.get("Priority", "Low") or "Low").lower(),
            status=(case.get("Status", "New") or "New").lower(),
            external_id=case.get("Id"),
        )
        ticket.id = case.get("Id", "")
        return ticket

    def create_ticket(self, ticket: Ticket) -> Ticket:
        self._check_configured()
        payload = {
            "Subject": ticket.subject,
            "Description": ticket.description,
            "SuppliedEmail": ticket.requester_email,
            "ContactName": ticket.requester_name,
            "Priority": ticket.priority.capitalize(),
            "Status": ticket.status.capitalize(),
            "Origin": "Web",
        }
        resp = requests.post(
            f"{self._instance_url}/services/data/v58.0/sobjects/Case",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        ticket.id = data.get("id", "")
        logger.info(f"Salesforce case created: {ticket.id}")
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        self._check_configured()
        try:
            resp = requests.get(
                f"{self._instance_url}/services/data/v58.0/sobjects/Case/{ticket_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_case(resp.json())
        except requests.HTTPError as e:
            if e.response and e.response.status_code == 404:
                logger.warning(f"Salesforce case not found: {ticket_id}")
                return None
            raise

    def update_ticket(
        self, ticket_id: str, updates: Dict[str, Any]
    ) -> Optional[Ticket]:
        self._check_configured()
        payload = {}
        field_map = {
            "subject": "Subject",
            "description": "Description",
            "priority": "Priority",
            "status": "Status",
        }
        for our_key, sf_key in field_map.items():
            if our_key in updates:
                value = updates[our_key]
                if our_key in ("priority", "status"):
                    value = value.capitalize()
                payload[sf_key] = value

        if not payload:
            return self.get_ticket(ticket_id)

        resp = requests.patch(
            f"{self._instance_url}/services/data/v58.0/sobjects/Case/{ticket_id}",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return self.get_ticket(ticket_id)

    def add_comment(
        self, ticket_id: str, comment: str, is_public: bool = True
    ) -> bool:
        self._check_configured()
        payload = {
            "ParentId": ticket_id,
            "Body": comment,
            "IsPublished": is_public,
        }
        resp = requests.post(
            f"{self._instance_url}/services/data/v58.0/sobjects/FeedItem",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        visibility = "public" if is_public else "private"
        logger.info(
            f"Salesforce {visibility} feed item added to case {ticket_id}"
        )
        return True

    def find_tickets_by_email(self, email: str) -> List[Ticket]:
        self._check_configured()
        query = f"SELECT Id, Subject, Description, Status, Priority, SuppliedEmail FROM Case WHERE SuppliedEmail = '{email}'"
        resp = requests.get(
            f"{self._instance_url}/services/data/v58.0/query",
            params={"q": query},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_case(r) for r in data.get("records", [])]

    def health_check(self) -> Dict[str, Any]:
        if not self._configured:
            return {
                "provider": self.get_name(),
                "status": "not_configured",
                "message": "Set SF_CLIENT_ID, SF_CLIENT_SECRET, SF_USERNAME, SF_PASSWORD",
            }
        try:
            self._authenticate()
            resp = requests.get(
                f"{self._instance_url}/services/data/v58.0/sobjects/Case/describe",
                headers=self._headers(),
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