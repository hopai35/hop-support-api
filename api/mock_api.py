"""
Hop Support - Mock Internal API

Simulates Hop Support's internal systems (order management, subscription
service, CRM proxy) for Phase 3 testing without real backend integration.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


# --- Sample Data ---

SAMPLE_ORDERS = {
    "ORD-001": {
        "order_id": "ORD-001",
        "customer_email": "alice@example.com",
        "customer_name": "Alice Johnson",
        "items": [
            {"name": "Hop Espresso Pro", "quantity": 1, "price": 599.00},
            {"name": "Coffee Beans - Dark Roast (1kg)", "quantity": 2, "price": 24.99},
        ],
        "total": 648.98,
        "status": "shipped",
        "tracking_number": "TRACK-98765-001",
        "carrier": "FedEx",
        "estimated_delivery": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d"),
        "shipping_address": "123 Main St, Portland, OR 97201",
        "order_date": (datetime.utcnow() - timedelta(days=5)).isoformat(),
    },
    "ORD-002": {
        "order_id": "ORD-002",
        "customer_email": "bob@example.com",
        "customer_name": "Bob Smith",
        "items": [
            {"name": "Hop Coffee Grinder - Classic", "quantity": 1, "price": 149.00},
        ],
        "total": 149.00,
        "status": "processing",
        "tracking_number": None,
        "carrier": None,
        "estimated_delivery": (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d"),
        "shipping_address": "456 Oak Ave, Seattle, WA 98101",
        "order_date": (datetime.utcnow() - timedelta(days=2)).isoformat(),
    },
    "ORD-003": {
        "order_id": "ORD-003",
        "customer_email": "carol@example.com",
        "customer_name": "Carol Davis",
        "items": [
            {"name": "Hop Espresso Pro", "quantity": 1, "price": 599.00},
            {"name": "Maintenance Kit", "quantity": 1, "price": 39.99},
            {"name": "Coffee Beans - Sampler Pack", "quantity": 1, "price": 34.99},
        ],
        "total": 673.98,
        "status": "delivered",
        "tracking_number": "TRACK-12345-003",
        "carrier": "UPS",
        "estimated_delivery": "2026-05-15",
        "shipping_address": "789 Pine Rd, San Francisco, CA 94102",
        "order_date": (datetime.utcnow() - timedelta(days=14)).isoformat(),
    },
    "ORD-004": {
        "order_id": "ORD-004",
        "customer_email": "alice@example.com",
        "customer_name": "Alice Johnson",
        "items": [
            {"name": "Coffee Beans - Medium Roast (1kg)", "quantity": 3, "price": 22.99},
        ],
        "total": 68.97,
        "status": "cancelled",
        "tracking_number": None,
        "carrier": None,
        "estimated_delivery": None,
        "shipping_address": "123 Main St, Portland, OR 97201",
        "order_date": (datetime.utcnow() - timedelta(days=10)).isoformat(),
    },
}

SAMPLE_SUBSCRIPTIONS = {
    "SUB-001": {
        "subscription_id": "SUB-001",
        "customer_email": "alice@example.com",
        "plan": "Dark Roast Monthly",
        "frequency": "every 4 weeks",
        "quantity_per_delivery": 2,
        "next_delivery": (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"),
        "status": "active",
        "price_per_delivery": 49.98,
    },
    "SUB-002": {
        "subscription_id": "SUB-002",
        "customer_email": "bob@example.com",
        "plan": "Sampler Pack Bi-Weekly",
        "frequency": "every 2 weeks",
        "quantity_per_delivery": 1,
        "next_delivery": (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d"),
        "status": "active",
        "price_per_delivery": 34.99,
    },
}


class MockInternalAPI:
    """
    Simulates Hop Support's internal backend services.
    In production, these would connect to real databases/APIs.
    """

    def __init__(self):
        self._orders = {k: dict(v) for k, v in SAMPLE_ORDERS.items()}
        self._subscriptions = {k: dict(v) for k, v in SAMPLE_SUBSCRIPTIONS.items()}
        self._returns = {}
        logger.info("MockInternalAPI initialized with sample data")

    # --- Order Management ---

    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch order details by order ID."""
        order = self._orders.get(order_id.upper())
        if order:
            logger.info(f"Order found: {order_id}")
            return dict(order)  # Return a copy
        logger.warning(f"Order not found: {order_id}")
        return None

    def get_orders_by_email(self, email: str) -> List[Dict[str, Any]]:
        """Find all orders for a given customer email."""
        results = [
            dict(o) for o in self._orders.values()
            if o["customer_email"].lower() == email.lower()
        ]
        logger.info(f"Found {len(results)} orders for {email}")
        return results

    # --- Returns ---

    def initiate_return(
        self, order_id: str, reason: str, email: str
    ) -> Optional[Dict[str, Any]]:
        """Create a return request for an order."""
        order = self._orders.get(order_id.upper())
        if not order:
            logger.warning(f"Cannot return: order {order_id} not found")
            return None

        return_id = f"RET-{uuid.uuid4().hex[:8].upper()}"
        return_record = {
            "return_id": return_id,
            "order_id": order_id.upper(),
            "customer_email": email,
            "reason": reason,
            "status": "pending_approval",
            "created_at": datetime.utcnow().isoformat(),
        }
        self._returns[return_id] = return_record
        logger.info(f"Return initiated: {return_id} for order {order_id}")
        return dict(return_record)

    def get_return_status(self, return_id: str) -> Optional[Dict[str, Any]]:
        """Check the status of a return request."""
        ret = self._returns.get(return_id.upper())
        if ret:
            return dict(ret)
        logger.warning(f"Return not found: {return_id}")
        return None

    # --- Subscription Management ---

    def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Fetch subscription details."""
        sub = self._subscriptions.get(subscription_id.upper())
        if sub:
            logger.info(f"Subscription found: {subscription_id}")
            return dict(sub)
        logger.warning(f"Subscription not found: {subscription_id}")
        return None

    def get_subscriptions_by_email(self, email: str) -> List[Dict[str, Any]]:
        """Find all subscriptions for a customer."""
        results = [
            dict(s) for s in self._subscriptions.values()
            if s["customer_email"].lower() == email.lower()
        ]
        logger.info(f"Found {len(results)} subscriptions for {email}")
        return results

    def update_subscription(
        self, subscription_id: str, action: str, months: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        Modify a subscription (pause/resume/cancel).
        
        Args:
            subscription_id: The subscription ID.
            action: 'pause', 'resume', or 'cancel'.
            months: For pause, how many months to pause.
        """
        sub = self._subscriptions.get(subscription_id.upper())
        if not sub:
            logger.warning(f"Subscription not found: {subscription_id}")
            return None

        action = action.lower()
        if action == "pause":
            sub["status"] = "paused"
            sub["paused_months"] = months
            sub["resume_date"] = (
                datetime.utcnow() + timedelta(days=30 * months)
            ).strftime("%Y-%m-%d")
            logger.info(f"Subscription {subscription_id} paused for {months} months")
        elif action == "resume":
            sub["status"] = "active"
            sub.pop("paused_months", None)
            sub.pop("resume_date", None)
            logger.info(f"Subscription {subscription_id} resumed")
        elif action == "cancel":
            sub["status"] = "cancelled"
            logger.info(f"Subscription {subscription_id} cancelled")
        else:
            logger.warning(f"Unknown subscription action: {action}")
            return None

        return dict(sub)

    # --- Billing ---

    def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """Get invoice details (simplified)."""
        invoices = {
            "INV-001": {
                "invoice_id": "INV-001",
                "customer_email": "alice@example.com",
                "amount": 648.98,
                "date": "2026-05-16",
                "status": "paid",
                "items": ["Hop Espresso Pro", "Coffee Beans - Dark Roast (1kg) x2"],
            },
            "INV-002": {
                "invoice_id": "INV-002",
                "customer_email": "bob@example.com",
                "amount": 149.00,
                "date": "2026-05-19",
                "status": "pending",
                "items": ["Hop Coffee Grinder - Classic"],
            },
        }
        inv = invoices.get(invoice_id.upper())
        if inv:
            return dict(inv)
        logger.warning(f"Invoice not found: {invoice_id}")
        return None