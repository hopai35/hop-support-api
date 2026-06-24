"""
Hop Support - Warby Parker Salesforce Integration

Extends the base Salesforce provider with Warby Parker-specific:
1. Intent-to-Salesforce Case mapping
2. Historical RX prescription data retrieval
3. Authentication and data isolation for the WP instance

This is a high-priority implementation for a signed $10,000 client.
"""

import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

from .salesforce import SalesforceProvider
from .base import Ticket

logger = logging.getLogger(__name__)

# Warby Parker-specific intent mapping to Salesforce Case record types
WP_INTENT_TO_CASE_TYPE = {
    "order_status": "Order_Status_Inquiry",
    "product_inquiry": "Product_Question",
    "return_refund": "Return_Refund",
    "technical_troubleshooting": "Technical_Support",
    "billing_invoice": "Billing_Invoice",
    "subscription_management": "Subscription_Change",  # Home Try-On
    "human_escalation": "Escalation",
    "general_faq": "General_Inquiry",
}

# Warby Parker-specific Case field mappings
WP_CASE_FIELD_MAP = {
    "order_id": "Order_ID__c",
    "prescription_id": "Prescription_ID__c",
    "frame_style": "Frame_Style__c",
    "lens_type": "Lens_Type__c",
    "home_try_on_id": "Home_Try_On_ID__c",
    "rx_verification_status": "RX_Verification_Status__c",
}


class WarbyParkerSalesforceProvider(SalesforceProvider):
    """
    Warby Parker-specific Salesforce integration.
    
    Extends the base SalesforceProvider with:
    - Intent-to-Case record type mapping
    - RX prescription data retrieval from Salesforce
    - Pre-configured Warby Parker Salesforce objects
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        logger.info("WarbyParkerSalesforceProvider initialized")

    def create_case_from_intent(
        self, ticket: Ticket, intent: str, confidence: float
    ) -> Optional[Ticket]:
        """
        Create a Salesforce Case with Warby Parker-specific record types
        based on the detected intent.
        
        Args:
            ticket: The support ticket to create
            intent: The detected intent (from intent_classifier)
            confidence: The intent detection confidence
            
        Returns:
            The created Ticket with Salesforce Case ID
        """
        case_type = WP_INTENT_TO_CASE_TYPE.get(intent, "General_Inquiry")
        
        # Add Warby Parker-specific fields
        if not ticket.custom_fields:
            ticket.custom_fields = {}
        ticket.custom_fields["Case_Type__c"] = case_type
        ticket.custom_fields["Intent_Source__c"] = "AI_Hop_Support"
        ticket.custom_fields["Intent_Confidence__c"] = str(confidence)
        ticket.tags = ticket.tags or []
        ticket.tags.extend(["warby-parker", f"intent-{intent}"])

        created = self.create_ticket(ticket)
        logger.info(
            f"Warby Parker case created: {created.id} "
            f"(type={case_type}, intent={intent})"
        )
        return created

    def get_rx_prescription(self, prescription_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve historical RX prescription data from Salesforce.
        
        Queries the Prescription__c custom object in Salesforce for
        a patient's optical prescription details.
        
        Args:
            prescription_id: The Warby Parker prescription ID
            
        Returns:
            Dict with prescription details or None if not found
        """
        self._check_configured()
        try:
            query = (
                f"SELECT Id, Name, OD_SPH__c, OD_CYL__c, OD_Axis__c, "
                f"OS_SPH__c, OS_CYL__c, OS_Axis__c, PD__c, "
                f"Expiration_Date__c, Verification_Status__c, "
                f"Prescription_Image_URL__c "
                f"FROM Prescription__c "
                f"WHERE Name = '{prescription_id}'"
            )
            resp = requests.get(
                f"{self._instance_url}/services/data/v58.0/query",
                params={"q": query},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", [])
            
            if not records:
                logger.warning(f"RX prescription not found: {prescription_id}")
                return None

            rx = records[0]
            return {
                "prescription_id": rx.get("Name", prescription_id),
                "right_eye": {
                    "sph": rx.get("OD_SPH__c"),
                    "cyl": rx.get("OD_CYL__c"),
                    "axis": rx.get("OD_Axis__c"),
                },
                "left_eye": {
                    "sph": rx.get("OS_SPH__c"),
                    "cyl": rx.get("OS_CYL__c"),
                    "axis": rx.get("OS_Axis__c"),
                },
                "pd": rx.get("PD__c"),
                "expiration_date": rx.get("Expiration_Date__c"),
                "verification_status": rx.get("Verification_Status__c"),
                "prescription_image_url": rx.get("Prescription_Image_URL__c"),
            }
        except Exception as e:
            logger.error(f"Failed to retrieve RX prescription {prescription_id}: {e}")
            return None

    def get_customer_orders(self, email: str) -> List[Dict[str, Any]]:
        """
        Retrieve order history for a Warby Parker customer from Salesforce.
        
        Args:
            email: Customer email address
            
        Returns:
            List of order records
        """
        self._check_configured()
        try:
            query = (
                f"SELECT Id, Order_ID__c, Order_Date__c, Status__c, "
                f"Frame_Style__c, Lens_Type__c, Total__c, Tracking_URL__c "
                f"FROM Order__c "
                f"WHERE Customer_Email__c = '{email}' "
                f"ORDER BY Order_Date__c DESC"
            )
            resp = requests.get(
                f"{self._instance_url}/services/data/v58.0/query",
                params={"q": query},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("records", [])
        except Exception as e:
            logger.error(f"Failed to retrieve orders for {email}: {e}")
            return []

    def get_home_try_on_status(self, try_on_id: str) -> Optional[Dict[str, Any]]:
        """
        Check the status of a Warby Parker Home Try-On.
        
        Args:
            try_on_id: The Home Try-On ID
            
        Returns:
            Dict with try-on status or None
        """
        self._check_configured()
        try:
            query = (
                f"SELECT Id, Name, Status__c, Frames_Selected__c, "
                f"Ship_Date__c, Return_Date__c, Days_Remaining__c "
                f"FROM Home_Try_On__c "
                f"WHERE Name = '{try_on_id}'"
            )
            resp = requests.get(
                f"{self._instance_url}/services/data/v58.0/query",
                params={"q": query},
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", [])
            
            if not records:
                logger.warning(f"Home Try-On not found: {try_on_id}")
                return None

            return records[0]
        except Exception as e:
            logger.error(f"Failed to retrieve Home Try-On {try_on_id}: {e}")
            return None


# Standalone mock for testing without real Salesforce credentials

class WarbyParkerMockProvider:
    """
    Mock Warby Parker provider for testing without live Salesforce.
    Simulates Cases, Prescriptions, Orders, and Home Try-Ons.
    """

    def __init__(self):
        self._cases = []
        self._prescriptions = {
            "RX-001": {
                "prescription_id": "RX-001",
                "right_eye": {"sph": -2.50, "cyl": -0.75, "axis": 180},
                "left_eye": {"sph": -2.25, "cyl": -0.50, "axis": 175},
                "pd": 62,
                "expiration_date": "2027-01-15",
                "verification_status": "Verified",
            },
            "RX-002": {
                "prescription_id": "RX-002",
                "right_eye": {"sph": -1.00, "cyl": 0, "axis": 0},
                "left_eye": {"sph": -0.75, "cyl": 0, "axis": 0},
                "pd": 58,
                "expiration_date": "2026-08-20",
                "verification_status": "Pending",
            },
        }
        self._orders = {
            "alice@example.com": [
                {"order_id": "WP-1001", "status": "Delivered", "frame_style": "Percey", "lens_type": "Single Vision", "order_date": "2026-04-10"},
                {"order_id": "WP-1005", "status": "Processing", "frame_style": "Baker", "lens_type": "Blue Light", "order_date": "2026-05-28"},
            ],
            "bob@example.com": [
                {"order_id": "WP-2002", "status": "Shipped", "frame_style": "Durand", "lens_type": "Progressive", "order_date": "2026-05-20"},
            ],
        }
        logger.info("WarbyParkerMockProvider initialized with sample data")

    def create_case_from_intent(self, ticket: Ticket, intent: str, confidence: float) -> Ticket:
        ticket.id = f"WP-CASE-{len(self._cases) + 1:04d}"
        ticket.custom_fields = ticket.custom_fields or {}
        ticket.custom_fields["Case_Type__c"] = WP_INTENT_TO_CASE_TYPE.get(intent, "General_Inquiry")
        ticket.custom_fields["Intent_Confidence__c"] = str(confidence)
        self._cases.append(ticket)
        logger.info(f"Mock WP case created: {ticket.id} for intent={intent}")
        return ticket

    def get_rx_prescription(self, prescription_id: str) -> Optional[Dict]:
        return self._prescriptions.get(prescription_id)

    def get_customer_orders(self, email: str) -> List[Dict]:
        return self._orders.get(email.lower(), [])

    def get_home_try_on_status(self, try_on_id: str) -> Optional[Dict]:
        try_ons = {
            "HTO-001": {"status": "Active", "frames": ["Percey", "Baker", "Durand"], "days_remaining": 3},
            "HTO-002": {"status": "Returned", "frames": ["Piazza", "Lowell"], "days_remaining": 0},
        }
        return try_ons.get(try_on_id)


# Fix missing import
import requests