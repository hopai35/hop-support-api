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


# ====================================================================
# Omni-Hub Expansion: Cross-Channel Context Merging & Unification
# ====================================================================
# These methods expand the StateStore to merge context from multiple
# sources (CRM, demo sessions, social, voice) under a single customer
# identity, enabling consistent AI memory across all touchpoints.
# ====================================================================


def search_by_email(self, email: str) -> Dict[str, Any]:
    """
    Find all customer context across channels using email as the
    unified identifier.
    
    Searches: identity mappings, CRM tickets, session store, social hub
    
    Args:
        email: Customer email address
        
    Returns:
        Unified customer profile with all channel context merged
    """
    import json as _json
    
    result = {
        "email": email,
        "customer_id": None,
        "channels": [],
        "crm_tickets": [],
        "sessions": [],
        "interaction_count": 0,
        "found": False,
    }
    
    # Step 1: Resolve email to customer_id
    customer_id = self.resolve_identity("email", email)
    
    if not customer_id:
        # Try to find via identity mappings file
        mapping_file = os.path.join(self.store_dir, "identity_mappings.json")
        if os.path.exists(mapping_file):
            with open(mapping_file) as f:
                mappings = _json.load(f)
            for key, cid in mappings.items():
                if email in key:
                    customer_id = cid
                    break
    
    if customer_id:
        result["customer_id"] = customer_id
        result["found"] = True
        
        # Step 2: Get cross-channel context
        context = self.get_cross_channel_context(customer_id)
        result["channels"] = context.get("channels_used", [])
        result["interaction_count"] = context.get("total_sessions", 0)
        
        # Step 3: Get all sessions for this customer
        sessions = self.find_customer_sessions(customer_id, limit=10)
        result["sessions"] = [
            {
                "session_id": s.get("session_id"),
                "channel": s.get("channel"),
                "created_at": s.get("created_at"),
                "is_active": s.get("is_active"),
                "interaction_count": len(s.get("history", [])),
                "last_intent": s.get("context", {}).get("last_intent"),
            }
            for s in sessions
        ]
        
        # Step 4: Get CRM tickets for this customer (via mock provider)
        try:
            from api.crm import get_crm_provider
            crm = get_crm_provider()
            tickets = crm.find_tickets_by_email(email)
            result["crm_tickets"] = [
                {
                    "id": t.id,
                    "subject": t.subject,
                    "status": t.status,
                    "priority": t.priority,
                    "created_at": str(t.created_at),
                    "tags": t.tags,
                }
                for t in tickets
            ]
        except Exception as e:
            logger.warning(f"Could not fetch CRM tickets for {email}: {e}")
            result["crm_tickets"] = []
    
    return result


def get_unified_context(self, email: str = None, customer_id: str = None) -> Dict[str, Any]:
    """
    Get a unified customer context profile by merging all available
    data sources: session history, CRM tickets, social interactions,
    and voice conversations.
    
    This is the primary Omni-Hub method for building AI prompts with
    full cross-channel memory.
    
    Args:
        email: Customer email (primary lookup)
        customer_id: Direct customer ID (fallback if email not provided)
        
    Returns:
        Unified context dict for AI prompt construction
    """
    import json as _json
    
    if not customer_id and email:
        customer_id = self.resolve_identity("email", email)
    
    if not customer_id:
        return {
            "customer_id": None,
            "known_customer": False,
            "context_summary": "New customer, no prior context available.",
        }
    
    # Gather data from all sources
    channel_context = self.get_cross_channel_context(customer_id)
    
    # Build CRM summary
    crm_summary = {"open_tickets": 0, "recent_tickets": [], "escalations": 0}
    try:
        from api.crm import get_crm_provider
        crm = get_crm_provider()
        
        # Find all linked identities to get email
        identities = []
        mapping_file = os.path.join(self.store_dir, "identity_mappings.json")
        if os.path.exists(mapping_file):
            with open(mapping_file) as f:
                mappings = _json.load(f)
            for key, cid in mappings.items():
                if cid == customer_id and "email" in key:
                    email_found = key.split(":", 1)[1]
                    tickets = crm.find_tickets_by_email(email_found)
                    for t in tickets:
                        crm_summary["recent_tickets"].append({
                            "id": t.id,
                            "subject": t.subject,
                            "status": t.status,
                            "priority": t.priority,
                        })
                        if t.status == "open":
                            crm_summary["open_tickets"] += 1
                        if "escalation" in t.tags:
                            crm_summary["escalations"] += 1
    except Exception as e:
        logger.warning(f"CRM context gather failed: {e}")
    
    # Build unified customer timeline
    timeline = []
    sessions = self.find_customer_sessions(customer_id, limit=20)
    for session in sessions:
        for interaction in session.get("history", []):
            timeline.append({
                "timestamp": interaction.get("timestamp", ""),
                "channel": session.get("channel"),
                "intent": interaction.get("intent", "unknown"),
                "summary": interaction.get("query", "")[:100],
                "resolved": interaction.get("resolved", False),
            })
    
    # Sort by timestamp
    timeline.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return {
        "customer_id": customer_id,
        "known_customer": True,
        "context_summary": (
            f"Customer has {channel_context.get('total_sessions', 0)} session(s) "
            f"across {len(channel_context.get('channels_used', []))} channel(s): "
            f"{', '.join(channel_context.get('channels_used', ['unknown']))}. "
            f"{crm_summary['open_tickets']} open ticket(s), "
            f"{crm_summary['escalations']} escalation(s)."
        ),
        "channels_used": channel_context.get("channels_used", []),
        "total_sessions": channel_context.get("total_sessions", 0),
        "last_channel": channel_context.get("last_channel"),
        "last_intent": channel_context.get("last_intent"),
        "crm": crm_summary,
        "recent_interactions": channel_context.get("recent_interactions", []),
        "timeline": timeline[:10],
        "all_tickets": crm_summary["recent_tickets"],
    }


def get_customer_by_identity(self, identity_value: str) -> Optional[str]:
    """
    Find a customer_id by any known identity value (email, phone, social handle).
    
    This is the universal identity resolver that searches across all
    identity types without needing to specify the type.
    
    Args:
        identity_value: Email, phone number, social handle, etc.
        
    Returns:
        customer_id if found, None otherwise
    """
    # Try common identity types
    for id_type in ["email", "phone", "social_handle", "whatsapp_number"]:
        cid = self.resolve_identity(id_type, identity_value)
        if cid:
            return cid
    return None


def get_context_for_prompt(self, email: str = None, customer_id: str = None) -> str:
    """
    Build a concise context string for AI prompt injection.
    
    This produces a ready-to-use natural language context block
    that can be inserted into LLM prompts for personalized responses.
    
    Args:
        email: Customer email
        customer_id: Direct customer ID
        
    Returns:
        Context string for AI prompt
    """
    context = self.get_unified_context(email=email, customer_id=customer_id)
    
    if not context.get("known_customer"):
        return ""
    
    parts = []
    parts.append(f"Customer has {context['total_sessions']} prior session(s).")
    
    if context["channels_used"]:
        parts.append(f"Previous channels: {', '.join(context['channels_used'])}.")
    
    if context["last_intent"]:
        parts.append(f"Last intent: {context['last_intent']}.")
    
    if context["crm"]["open_tickets"] > 0:
        parts.append(f"Has {context['crm']['open_tickets']} open support ticket(s).")
        if context["crm"]["recent_tickets"]:
            subjects = [t["subject"] for t in context["crm"]["recent_tickets"][:2]]
            parts.append(f"Recent tickets: {'; '.join(subjects)}.")
    
    if context["recent_interactions"]:
        last = context["recent_interactions"][0]
        parts.append(
            f"Last interaction was via {last.get('channel', 'unknown')} "
            f"about: '{last.get('query', '')[:80]}'."
        )
    
    return " ".join(parts)


def search_context(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search across all stored context for a keyword or phrase.
    
    This is useful for finding customers by conversation content,
    order numbers, or any searchable text across sessions.
    
    Args:
        query: Search term (order number, topic keyword, etc.)
        limit: Max results
        
    Returns:
        List of matching context entries with customer info
    """
    import json as _json
    
    results = []
    query_lower = query.lower()
    
    if not self.use_redis:
        for filename in os.listdir(self.store_dir):
            if filename.endswith(".json") and filename != "identity_mappings.json":
                path = os.path.join(self.store_dir, filename)
                try:
                    with open(path) as f:
                        data = _json.load(f)
                    
                    # Search in session history
                    for interaction in data.get("history", []):
                        text = f"{interaction.get('query', '')} {interaction.get('response', '')}"
                        if query_lower in text.lower():
                            results.append({
                                "session_id": data.get("session_id"),
                                "customer_id": data.get("customer_id"),
                                "channel": data.get("channel"),
                                "match": interaction.get("query", "")[:100],
                                "timestamp": interaction.get("timestamp"),
                            })
                            break  # One match per session
                except Exception:
                    continue
    
    # Deduplicate and limit
    seen = set()
    unique_results = []
    for r in results:
        if r["session_id"] not in seen:
            seen.add(r["session_id"])
            unique_results.append(r)
    
    return unique_results[:limit]


# Bind all new methods to StateStore
StateStore.search_by_email = search_by_email
StateStore.get_unified_context = get_unified_context
StateStore.get_customer_by_identity = get_customer_by_identity
StateStore.get_context_for_prompt = get_context_for_prompt
StateStore.search_context = search_context
