"""
Hop Support - Omni-Hub State Store (Mock Prototype)

Handles cross-channel conversation state and identity resolution.
Maps channel-specific IDs (Phone, Social Handles) to a unified customer identity.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class StateStore:
    """
    Prototypes identity resolution and cross-channel context management.
    """

    def __init__(self):
        # Mock database
        self.identities = {
            "phone:+19175550123": "cust_001",
            "instagram:alice_coffee": "cust_001",
            "email:alice@example.com": "cust_001",
        }
        self.customers = {
            "cust_001": {
                "name": "Alice Smith",
                "email": "alice@example.com",
                "phone": "+19175550123",
                "social_handles": {"instagram": "alice_coffee"}
            }
        }
        self.sessions = {}  # session_id -> session_data
        self.interactions = {}  # customer_id -> list of interactions
        
        logger.info("Mock StateStore initialized")

    def resolve_identity(self, platform: str, identifier: str) -> Optional[str]:
        """
        Map a platform-specific ID (e.g. whatsapp phone, igsid) to a canonical customer_id.
        """
        key = f"{platform}:{identifier}"
        customer_id = self.identities.get(key)
        if customer_id:
            logger.info(f"Identity resolved: {key} -> {customer_id}")
        else:
            logger.info(f"New identity detected: {key}")
        return customer_id

    def create_session(self, channel: str, customer_id: str, platform_id: str) -> str:
        """Create a new session for an interaction."""
        session_id = f"sess_{channel}_{datetime.now().timestamp()}"
        self.sessions[session_id] = {
            "channel": channel,
            "customer_id": customer_id,
            "platform_id": platform_id,
            "created_at": datetime.now().isoformat(),
            "status": "active"
        }
        return session_id

    def add_interaction(self, customer_id: str, channel: str, query: str, response: str, intent: str = "unknown"):
        """Record an interaction for cross-channel history."""
        if customer_id not in self.interactions:
            self.interactions[customer_id] = []
        
        self.interactions[customer_id].append({
            "timestamp": datetime.now().isoformat(),
            "channel": channel,
            "query": query,
            "response": response,
            "intent": intent
        })
        # Keep last 10
        self.interactions[customer_id] = self.interactions[customer_id][-10:]
        logger.info(f"Interaction recorded for {customer_id} via {channel}")

    def get_cross_channel_context(self, customer_id: str) -> Dict[str, Any]:
        """Retrieve recent interactions across all channels for a customer."""
        history = self.interactions.get(customer_id, [])
        channels = list(set(i["channel"] for i in history))
        
        return {
            "customer_id": customer_id,
            "customer_info": self.customers.get(customer_id, {}),
            "channels_used": channels,
            "recent_interactions": history,
            "last_intent": history[-1]["intent"] if history else None
        }

# Global instance for the prototype
state_store = StateStore()
