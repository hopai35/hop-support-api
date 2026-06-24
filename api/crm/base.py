"""
Hop Support - CRM Integration Base Module

Abstract base class for CRM integrations (Zendesk, Salesforce, etc.).
All CRM providers should inherit from BaseCRMProvider.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Ticket:
    """Represents a support ticket across any CRM."""

    def __init__(
        self,
        subject: str,
        description: str,
        requester_email: str,
        requester_name: Optional[str] = None,
        priority: str = "normal",
        status: str = "new",
        tags: Optional[List[str]] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
        external_id: Optional[str] = None,
    ):
        self.subject = subject
        self.description = description
        self.requester_email = requester_email
        self.requester_name = requester_name or requester_email.split("@")[0]
        self.priority = priority  # low, normal, high, urgent
        self.status = status  # new, open, pending, solved, closed
        self.tags = tags or []
        self.custom_fields = custom_fields or {}
        self.external_id = external_id
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
        self.id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "requester_email": self.requester_email,
            "requester_name": self.requester_name,
            "priority": self.priority,
            "status": self.status,
            "tags": self.tags,
            "custom_fields": self.custom_fields,
            "external_id": self.external_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class BaseCRMProvider(ABC):
    """Abstract base class for CRM integrations."""

    @abstractmethod
    def create_ticket(self, ticket: Ticket) -> Ticket:
        """Create a new support ticket."""
        pass

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Get a ticket by ID."""
        pass

    @abstractmethod
    def update_ticket(
        self, ticket_id: str, updates: Dict[str, Any]
    ) -> Optional[Ticket]:
        """Update an existing ticket."""
        pass

    @abstractmethod
    def add_comment(
        self, ticket_id: str, comment: str, is_public: bool = True
    ) -> bool:
        """Add a comment/note to a ticket."""
        pass

    @abstractmethod
    def find_tickets_by_email(self, email: str) -> List[Ticket]:
        """Find all tickets for a given requester email."""
        pass

    @abstractmethod
    def find_customer_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Find a customer profile by phone number."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Return the name of this CRM provider."""
        pass

    def health_check(self) -> Dict[str, Any]:
        """Check if the CRM connection is healthy."""
        return {"provider": self.get_name(), "status": "unknown"}