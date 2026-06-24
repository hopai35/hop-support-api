"""
Test Script for Social Hub Prototype

Simulates a cross-channel user journey:
1. User starts on Web.
2. User follows up via WhatsApp.
3. System resolves identity and retrieves context.
"""

import json
import logging
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import our prototype components
from api.social_handler import router
from api.state_store import state_store

# Setup logging
logging.basicConfig(level=logging.INFO)

# Setup a test FastAPI app
app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_whatsapp_context_resumption():
    print("\n--- Starting Cross-Channel Context Test ---")
    
    # 1. Setup: Known customer with a previous Web interaction
    customer_id = "cust_001"
    platform_id = "+19175550123" # WhatsApp phone
    
    print(f"PRE-CONDITION: Adding a 'web' interaction for {customer_id}...")
    state_store.add_interaction(
        customer_id=customer_id,
        channel="web",
        query="My espresso machine is leaking.",
        response="I'm sorry to hear that. Have you checked the gasket?",
        intent="technical_troubleshooting"
    )

    # 2. Simulate WhatsApp Webhook Payload
    whatsapp_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "12345", "phone_number_id": "67890"},
                            "contacts": [{"profile": {"name": "Alice Smith"}, "wa_id": platform_id}],
                            "messages": [
                                {
                                    "from": platform_id,
                                    "id": "wamid.HBgL...",
                                    "timestamp": "1602111111",
                                    "text": {"body": "The gasket looks fine. What else should I check?"},
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    print(f"STEP 2: Sending WhatsApp webhook for {platform_id}...")
    
    # 3. Call the webhook endpoint
    # We skip signature validation for the prototype test by using 'mock_secret_key'
    response = client.post(
        "/webhooks/meta",
        json=whatsapp_payload,
        headers={"X-Hub-Signature-256": "sha256=invalid"} # Prototype handler skips if secret is mock
    )

    # 4. Verify results
    assert response.status_code == 200
    result = response.json()
    print(f"RESPONSE STATUS: {result['status']}")
    print(f"RESOLVED CUSTOMER: {result['customer_id']}")
    
    assert result["customer_id"] == customer_id
    
    # Check if context was updated in state store
    context = state_store.get_cross_channel_context(customer_id)
    interactions = context["recent_interactions"]
    
    print(f"\nINTERACTION HISTORY FOR {customer_id}:")
    for i in interactions:
        print(f"  [{i['channel']}] Q: {i['query']}")
        print(f"  [{i['channel']}] A: {i['response']}")

    assert len(interactions) >= 2
    assert interactions[0]["channel"] == "web"
    assert interactions[1]["channel"] == "phone"
    
    print("\n--- Context Resumption Test Passed! ---")

if __name__ == "__main__":
    test_whatsapp_context_resumption()
