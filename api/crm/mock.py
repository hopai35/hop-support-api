"""
Hop Support - Mock CRM Provider

An in-memory CRM provider for testing and development.
Stores tickets in a local dict. No external API calls.
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
import uuid

from .base import BaseCRMProvider, Ticket

logger = logging.getLogger(__name__)


class MockCRMProvider(BaseCRMProvider):
    """In-memory CRM provider for testing/demo without real API credentials."""

    def __init__(self):
        self._tickets: Dict[str, Ticket] = {}
        self._comments: Dict[str, List[Dict]] = {}
        logger.info("MockCRMProvider initialized")

    def get_name(self) -> str:
        return "mock"

    def create_ticket(self, ticket: Ticket) -> Ticket:
        ticket.id = str(uuid.uuid4())
        ticket.created_at = datetime.utcnow()
        ticket.updated_at = ticket.created_at
        self._tickets[ticket.id] = ticket
        logger.info(f"Mock ticket created: {ticket.id} - '{ticket.subject}'")
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            logger.info(f"Mock ticket retrieved: {ticket_id}")
        else:
            logger.warning(f"Mock ticket not found: {ticket_id}")
        return ticket

    def update_ticket(
        self, ticket_id: str, updates: Dict[str, Any]
    ) -> Optional[Ticket]:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            logger.warning(f"Cannot update: ticket {ticket_id} not found")
            return None

        for key, value in updates.items():
            if hasattr(ticket, key) and key not in ("id", "created_at"):
                setattr(ticket, key, value)
        ticket.updated_at = datetime.utcnow()

        logger.info(f"Mock ticket updated: {ticket_id} -> {updates}")
        return ticket

    def add_comment(
        self, ticket_id: str, comment: str, is_public: bool = True
    ) -> bool:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            logger.warning(f"Cannot add comment: ticket {ticket_id} not found")
            return False

        if ticket_id not in self._comments:
            self._comments[ticket_id] = []

        self._comments[ticket_id].append({
            "body": comment,
            "is_public": is_public,
            "created_at": datetime.utcnow().isoformat(),
        })
        ticket.updated_at = datetime.utcnow()

        visibility = "public" if is_public else "internal"
        logger.info(
            f"Mock {visibility} comment added to ticket {ticket_id}"
        )
        return True

    def find_tickets_by_email(self, email: str) -> List[Ticket]:
        results = [
            t for t in self._tickets.values()
            if t.requester_email.lower() == email.lower()
        ]
        logger.info(
            f"Mock find by email '{email}': {len(results)} tickets found"
        )
        return results

    def find_customer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        # Mock customer database (in reality, this would query a Users/Contacts table)
        mock_customers = [
            {"id": "cust_001", "name": "Alice Smith", "email": "alice@example.com", "phone": "+19175550123"},
            {"id": "cust_002", "name": "Bob Jones", "email": "bob@example.com", "phone": "+447700900123"},
        ]
        for cust in mock_customers:
            if cust["phone"] == phone:
                logger.info(f"Mock find by phone '{phone}': found {cust['id']}")
                return cust
        logger.info(f"Mock find by phone '{phone}': not found")
        return None

    def get_comments(self, ticket_id: str) -> List[Dict]:
        """Get all comments for a ticket (mock-specific helper)."""
        return self._comments.get(ticket_id, [])

    def health_check(self) -> Dict[str, Any]:
        return {
            "provider": self.get_name(),
            "status": "ok",
            "ticket_count": len(self._tickets),
        }