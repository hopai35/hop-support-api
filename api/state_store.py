"""
Hop Support - Multi-Channel State Store (Omni-Hub)

Maintains conversation context across different channels (Web, Voice, Social)
so a customer can start on one channel and continue on another seamlessly.

Supports two storage backends:
1. Redis (production) - fast, shared across instances
2. JSON-file (default/mock) - lightweight, no external dependency
"""

import json
import os
import uuid
import logging
import threading
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

STATE_STORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "state_store",
)

# Identity Resolver Schema (proposed for Redis)
IDENTITY_RESOLVER_SCHEMA = {
    "description": (
        "Links a customer's identities across channels to a single profile. "
        "Each identity (phone, email, social handle) maps to a canonical customer_id."
    ),
    "fields": {
        "customer_id": "UUID - primary key for the canonical customer",
        "identities": {
            "phone": "string - E.164 phone number format",
            "email": "string - verified email address",
            "vapi_session_id": "string - Vapi voice session ID",
            "web_session_id": "string - Web chat session ID",
            "social_handle": "string - Instagram/Twitter handle",
            "whatsapp_number": "string - WhatsApp number",
        },
        "last_interaction": "ISO8601 timestamp of last interaction",
        "total_interactions": "integer - lifetime total across all channels",
        "preferred_channel": "string - web, voice, whatsapp, instagram",
        "metadata": "dict - additional profile data",
    },
    "redis_key_pattern": "identity:{identifier_type}:{value} -> customer_id",
    "examples": [
        "SET identity:phone:+14155551234 -> cust_abc123",
        "SET identity:email:alice@example.com -> cust_abc123",
        "GET customer:cust_abc123 -> {full profile with all linked identities}",
    ],
}


class StateStore:
    """
    Cross-channel conversation state store.
    
    Maintains conversation context, identity mapping, and session state
    so interactions can flow seamlessly between Web, Voice, and Social channels.
    """

    def __init__(self, store_dir: str = STATE_STORE_DIR, use_redis: bool = False):
        self.store_dir = store_dir
        self.use_redis = use_redis
        self._lock = threading.Lock()
        
        if use_redis:
            self._init_redis()
        else:
            os.makedirs(store_dir, exist_ok=True)
        
        logger.info(
            f"StateStore initialized (backend={'redis' if use_redis else 'json'})"
        )

    def _init_redis(self):
        """Initialize Redis connection (production)."""
        try:
            import redis
            self.redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                decode_responses=True,
            )
            self.redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis unavailable, falling back to JSON: {e}")
            self.use_redis = False
            os.makedirs(self.store_dir, exist_ok=True)

    def _get_state_path(self, session_id: str) -> str:
        """Get file path for a session state."""
        return os.path.join(self.store_dir, f"session_{session_id}.json")

    # --- Session Management ---

    def create_session(
        self,
        channel: str,
        customer_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Create a new session for any channel.
        
        Args:
            channel: 'web', 'voice', 'whatsapp', 'instagram', 'email'
            customer_id: Known customer ID, or None for anonymous
            metadata: Channel-specific metadata
            
        Returns:
            Session dict with session_id, created_at, etc.
        """
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "customer_id": customer_id,
            "channel": channel,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "is_active": True,
            "history": [],
            "context": {
                "last_intent": None,
                "last_tool_calls": [],
                "pending_escalation": False,
                "metadata": metadata or {},
            },
        }

        if self.use_redis:
            self.redis_client.setex(
                f"session:{session_id}",
                timedelta(hours=24),
                json.dumps(session, default=str),
            )
        else:
            with self._lock:
                with open(self._get_state_path(session_id), "w") as f:
                    json.dump(session, f, indent=2, default=str)

        logger.info(f"Session created: {session_id[:8]}... via {channel}")
        return session

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session by ID."""
        if self.use_redis:
            data = self.redis_client.get(f"session:{session_id}")
            if data:
                return json.loads(data)
        else:
            path = self._get_state_path(session_id)
            if os.path.exists(path):
                with open(path, "r") as f:
                    return json.load(f)
        return None

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a session's context or state."""
        session = self.get_session(session_id)
        if not session:
            return None

        session["updated_at"] = datetime.utcnow().isoformat()

        # Handle nested context updates
        if "context" in updates:
            session["context"].update(updates.pop("context"))
        
        # Handle top-level updates
        for key, value in updates.items():
            if key in ("is_active", "customer_id"):
                session[key] = value

        session["history"] = session.get("history", [])
        if "history_entry" in updates:
            session["history"].append(updates.pop("history_entry"))
            # Keep last 20 entries
            session["history"] = session["history"][-20:]

        self._save_session(session)
        return session

    def _save_session(self, session: Dict[str, Any]):
        """Save session to backend."""
        session_id = session["session_id"]
        if self.use_redis:
            self.redis_client.setex(
                f"session:{session_id}",
                timedelta(hours=24),
                json.dumps(session, default=str),
            )
        else:
            with self._lock:
                with open(self._get_state_path(session_id), "w") as f:
                    json.dump(session, f, indent=2, default=str)

    def add_interaction(
        self,
        session_id: str,
        query: str,
        response: str,
        intent: str,
        tool_calls: Optional[List[Dict]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Record an AI interaction in the session history.
        
        This enables cross-channel context resumption.
        """
        interaction = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "response": response,
            "intent": intent,
            "tool_calls": tool_calls or [],
        }
        return self.update_session(session_id, {"history_entry": interaction})

    def close_session(self, session_id: str) -> bool:
        """Mark a session as inactive (resolved/closed)."""
        result = self.update_session(session_id, {"is_active": False})
        return result is not None

    # --- Identity Resolution ---

    def resolve_identity(self, identifier_type: str, value: str) -> Optional[str]:
        """
        Resolve a channel-specific identifier to a canonical customer_id.
        
        Args:
            identifier_type: 'phone', 'email', 'vapi_session_id', 'web_session_id', 'social_handle'
            value: The identifier value
            
        Returns:
            customer_id if found, None otherwise
        """
        if self.use_redis:
            customer_id = self.redis_client.get(
                f"identity:{identifier_type}:{value}"
            )
            return customer_id

        # JSON fallback: scan identity mappings
        mapping_file = os.path.join(self.store_dir, "identity_mappings.json")
        if os.path.exists(mapping_file):
            with open(mapping_file, "r") as f:
                mappings = json.load(f)
            return mappings.get(f"{identifier_type}:{value}")
        return None

    def link_identity(
        self,
        customer_id: str,
        identifier_type: str,
        value: str,
    ):
        """
        Link a channel identifier to a canonical customer profile.
        
        Args:
            customer_id: The canonical customer ID
            identifier_type: 'phone', 'email', 'vapi_session_id', etc.
            value: The identifier value
        """
        key = f"{identifier_type}:{value}"
        
        if self.use_redis:
            self.redis_client.set(f"identity:{key}", customer_id)
        else:
            mapping_file = os.path.join(self.store_dir, "identity_mappings.json")
            mappings = {}
            if os.path.exists(mapping_file):
                with open(mapping_file, "r") as f:
                    mappings = json.load(f)
            mappings[key] = customer_id
            with open(mapping_file, "w") as f:
                json.dump(mappings, f, indent=2)

        logger.info(f"Identity linked: {key} -> {customer_id[:8]}...")

    def find_customer_sessions(
        self, customer_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Find the most recent sessions for a customer across all channels."""
        sessions = []
        if not self.use_redis:
            for filename in os.listdir(self.store_dir):
                if filename.startswith("session_") and filename.endswith(".json"):
                    path = os.path.join(self.store_dir, filename)
                    with open(path, "r") as f:
                        session = json.load(f)
                    if session.get("customer_id") == customer_id:
                        sessions.append(session)
        
        # Sort by most recent and limit
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def get_cross_channel_context(
        self, customer_id: str
    ) -> Dict[str, Any]:
        """
        Get a summary of the customer's recent interactions across all channels.
        
        This is the key method for the Omni-Hub: it returns the last 5 interactions
        regardless of channel, enabling seamless cross-channel context resumption.
        """
        sessions = self.find_customer_sessions(customer_id)
        
        all_interactions = []
        channels_used = set()
        
        for session in sessions:
            channels_used.add(session.get("channel", "unknown"))
            for interaction in session.get("history", []):
                all_interactions.append({
                    **interaction,
                    "channel": session.get("channel"),
                })
        
        # Sort all interactions by timestamp, most recent first
        all_interactions.sort(
            key=lambda i: i.get("timestamp", ""), reverse=True
        )
        
        return {
            "customer_id": customer_id,
            "channels_used": list(channels_used),
            "total_sessions": len(sessions),
            "recent_interactions": all_interactions[:5],
            "last_intent": sessions[0].get("context", {}).get("last_intent")
            if sessions else None,
            "last_channel": sessions[0].get("channel") if sessions else None,
        }


# Module-level singleton for import by social_handler and other modules
# main.py should use this same instance rather than creating a new one
state_store = StateStore()

# --- Token Cache for Skyflow Reversible Redaction ---

def store_token_map(self, session_id: str, token_map: dict, ttl: int = 3600):
    """
    Store a Skyflow token map for later re-identification.
    Tokens expire after TTL seconds (default 1 hour).
    """
    import json as _json
    record = {
        "token_map": token_map,
        "created_at": __import__('datetime').datetime.utcnow().isoformat(),
        "ttl": ttl,
    }
    if self.use_redis and hasattr(self, 'redis_client'):
        key = f"token_map:{session_id}"
        self.redis_client.setex(key, ttl, _json.dumps(record))
    else:
        path = os.path.join(self.store_dir, f"tokens_{session_id}.json")
        with open(path, "w") as f:
            _json.dump(record, f, indent=2)

def get_token_map(self, session_id: str) -> dict:
    """
    Retrieve a stored token map for a session.
    Returns empty dict if not found or expired.
    """
    import json as _json
    if self.use_redis and hasattr(self, 'redis_client'):
        key = f"token_map:{session_id}"
        data = self.redis_client.get(key)
        if data:
            record = _json.loads(data)
            return record.get("token_map", {})
    else:
        path = os.path.join(self.store_dir, f"tokens_{session_id}.json")
        if os.path.exists(path):
            with open(path) as f:
                record = _json.load(f)
            return record.get("token_map", {})
    return {}

# Bind methods to StateStore
StateStore.store_token_map = store_token_map
StateStore.get_token_map = get_token_map
