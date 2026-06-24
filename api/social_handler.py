"""
Hop Support - Social Hub Webhook Handler

Handles incoming messages from Meta Graph API (Instagram & WhatsApp).
Performs signature validation, identity resolution, and routes to AI response engine.
"""

import hmac
import hashlib
import json
import logging
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Query, Header

from api.state_store import state_store

logger = logging.getLogger(__name__)

# Router for main.py integration
router = APIRouter()

# Configuration (In production, these would be env vars)
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "hop_support_token_2026")
APP_SECRET = os.getenv("META_APP_SECRET", "mock_secret_key")

# Lazy engine references — populated by main.py on startup via set_engines()
_rag_engine = None
_intent_classifier = None


def set_engines(rag_engine, intent_classifier):
    """Called by main.py after initialization to inject engine references."""
    global _rag_engine, _intent_classifier
    _rag_engine = rag_engine
    _intent_classifier = intent_classifier
    logger.info("Social handler engines initialized")


def validate_signature(payload: bytes, signature: str) -> bool:
    """Validate X-Hub-Signature-256 header."""
    if not signature:
        return False
    
    # Signature format is 'sha256=hash'
    if not signature.startswith("sha256="):
        return False
    
    expected_signature = hmac.new(
        APP_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature[7:], expected_signature)


@router.get("/webhooks/meta")
async def meta_handshake(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")
):
    """Meta Webhook Verification (Handshake)."""
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return int(challenge)
    
    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhooks/meta")
async def handle_meta_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None)
):
    """Handle incoming message payloads from Instagram and WhatsApp."""
    payload_bytes = await request.body()
    
    # 1. Validate Signature
    if not validate_signature(payload_bytes, x_hub_signature_256):
        logger.error("Invalid signature detected")
        # In mock mode for testing, we might skip this if the secret isn't set
        if APP_SECRET != "mock_secret_key":
             raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(payload_bytes)
    logger.info(f"Received Meta webhook: {json.dumps(payload, indent=2)}")

    # 2. Extract Message Info
    platform, platform_id, message_text = parse_meta_payload(payload)
    
    if not platform_id or not message_text:
        return {"status": "ignored", "reason": "No message content"}

    # 3. Identity Resolution (Omni-Hub)
    customer_id = state_store.resolve_identity(platform, platform_id)
    if not customer_id:
        # For prototype, auto-create a customer ID if new
        customer_id = f"new_cust_{platform_id[-4:]}"
        logger.info(f"Auto-generated customer_id: {customer_id}")

    # 4. Context Retrieval
    context = state_store.get_cross_channel_context(customer_id)
    
    # 5. Generate AI Response (using RAG + cross-channel context)
    response_text = generate_ai_response(message_text, context)

    # 6. Record Interaction
    intent = "general_faq"  # Would come from intent_classifier in production
    state_store.add_interaction(customer_id, platform, message_text, response_text, intent)

    # 7. Mock Outgoing Message
    send_mock_reply(platform, platform_id, response_text)

    return {"status": "success", "customer_id": customer_id}


def parse_meta_payload(payload: Dict[str, Any]):
    """Parse payload for Instagram or WhatsApp structures."""
    obj = payload.get("object")
    
    if obj == "instagram":
        # Simplified extraction
        entry = payload.get("entry", [{}])[0]
        messaging = entry.get("messaging", [{}])[0]
        sender_id = messaging.get("sender", {}).get("id")
        text = messaging.get("message", {}).get("text")
        return "instagram", sender_id, text
    
    elif obj == "whatsapp_business_account":
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [{}])
        if messages:
            phone = messages[0].get("from")
            text = messages[0].get("text", {}).get("body")
            return "phone", phone, text
            
    return None, None, None


def generate_ai_response(query: str, context: Dict[str, Any]) -> str:
    """Generate AI response using RAG engine + cross-channel context."""
    customer_info = context.get("customer_info", {})
    customer_name = customer_info.get("name", "Customer")
    history = context.get("recent_interactions", [])
    
    # Build context prefix from cross-channel history
    context_prefix = ""
    if history:
        last_channel = history[-1]["channel"]
        context_prefix = f"Hi {customer_name}! I see you previously contacted us via {last_channel}. "
    
    # Use RAG engine if available
    if _rag_engine:
        try:
            result = _rag_engine.query(query)
            return f"{context_prefix}{result['answer']}"
        except Exception as e:
            logger.error(f"RAG query failed in social handler: {e}")
    
    # Fallback to mock response
    if history:
        return f"{context_prefix}Regarding your query: '{query}', I'm happy to help..."
    else:
        return f"Hello! Welcome to Hop Support. How can I help you with your query: '{query}'?"


def send_mock_reply(platform: str, platform_id: str, text: str):
    """Mocks the POST request back to Meta Graph API."""
    logger.info(f"MOCK SEND to {platform} ({platform_id}): {text}")
    # In production: requests.post(f"https://graph.facebook.com/v20.0/{ID}/messages", ...)