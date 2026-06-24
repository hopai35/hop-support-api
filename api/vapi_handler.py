"""
Hop Support - Vapi.ai Voice Integration

Handles Vapi server webhooks for AI-powered voice support.
Integrates with the existing RAG engine, intent classifier, and tools.

Vapi Workflow:
1. User speaks → Vapi transcribes audio → sends transcript to our webhook
2. Our endpoint processes the query via RAG + intent detection
3. Returns response text → Vapi speaks it back to the user
4. For tool calls (order status, etc.), Vapi calls our function webhook
"""

import logging
import json
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class VapiMessageType(str, Enum):
    """Vapi webhook message types."""
    ASSISTANT_REQUEST = "assistant-request"
    FUNCTION_CALL = "function-call"
    STATUS_UPDATE = "status-update"
    END_OF_CALL_REPORT = "end-of-call-report"


class VapiHandler:
    """
    Handles Vapi.ai webhook requests for real-time voice support.
    
    This implements Vapi's "Server URL" / "Server Webhook" pattern:
    - Vapi sends POST requests with conversation events
    - Our handler returns assistant config, function results, or messages
    """

    def __init__(self, rag_engine, intent_classifier, tool_executor, crm_provider=None):
        self.rag_engine = rag_engine
        self.intent_classifier = intent_classifier
        self.tool_executor = tool_executor
        self.crm_provider = crm_provider
        logger.info("VapiHandler initialized")

    def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main webhook handler. Routes to the appropriate handler based on message type.
        
        Vapi sends different message types:
        - assistant-request: Vapi wants to know how to configure the AI assistant
        - function-call: Vapi wants to execute a function/tool
        - status-update: Call status changed
        - end-of-call-report: Call ended with stats
        """
        message_type = payload.get("type", "")
        logger.info(f"Vapi webhook received: type={message_type}")

        handler_map = {
            VapiMessageType.ASSISTANT_REQUEST: self._handle_assistant_request,
            VapiMessageType.FUNCTION_CALL: self._handle_function_call,
            VapiMessageType.STATUS_UPDATE: self._handle_status_update,
            VapiMessageType.END_OF_CALL_REPORT: self._handle_end_of_call,
        }

        handler = handler_map.get(message_type)
        if handler:
            return handler(payload)
        
        logger.warning(f"Unknown Vapi message type: {message_type}")
        return {"error": f"Unknown message type: {message_type}"}

    def _handle_assistant_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle assistant-request from Vapi.
        
        Vapi sends this at the start of a call to get assistant configuration.
        We return the assistant's system prompt, voice, and function definitions.
        """
        # Build tools for Vapi in Vapi's format
        tools = self._build_vapi_tools()

        # Build the assistant configuration
        return {
            "assistant": {
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "systemPrompt": self._build_system_prompt(),
                    "functions": tools,
                },
                "voice": {
                    "provider": "11labs",
                    "voiceId": "21m00Tcm4TlvDq8ikWAM",  # Rachel voice
                },
                "firstMessage": "Hello! Welcome to Hop Support. How can I help you with your coffee equipment today?",
            }
        }

    def _handle_function_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle function-call from Vapi.
        
        When the AI decides to call a tool during the conversation,
        Vapi sends a function-call webhook with the function name and arguments.
        We execute the tool and return the result.
        """
        function_name = payload.get("function", {}).get("name", "")
        arguments = payload.get("function", {}).get("parameters", {})

        logger.info(f"Vapi function call: {function_name}({arguments})")

        if not function_name:
            return {"error": "No function name provided"}

        result = self.tool_executor.execute_tool(function_name, arguments)
        
        return {
            "result": json.dumps(result.get("result", result)),
        }

    def _handle_status_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle status-update from Vapi (e.g., call started, ended)."""
        status = payload.get("status", "")
        logger.info(f"Vapi call status: {status}")
        return {"status": "ok"}

    def _handle_end_of_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle end-of-call-report from Vapi.
        
        Vapi sends this when a call ends with a summary, transcript, and stats.
        We can log this for analytics and CRM recording.
        """
        call_summary = {
            "call_id": payload.get("call", {}).get("id", ""),
            "duration_seconds": payload.get("call", {}).get("duration", 0),
            "transcript": payload.get("transcript", ""),
            "cost": payload.get("cost", 0),
            "ended_reason": payload.get("endedReason", ""),
        }
        logger.info(f"Vapi call ended: {json.dumps(call_summary, default=str)}")
        return {"status": "ok"}

    def process_voice_query(self, text: str) -> Dict[str, Any]:
        """
        Process a voice-transcribed text query through the full AI pipeline.
        
        This is used when Vapi sends a transcript chunk and we need to respond.
        Returns a response suitable for Vapi to speak back.
        """
        if not text.strip():
            return {"response": "I didn't catch that. Could you please repeat?"}

        # Detect intent
        intent_result = self.intent_classifier.classify(text)
        intent = intent_result.get("intent", "general_faq")

        result = {
            "intent": intent,
            "confidence": intent_result.get("confidence", 0),
        }

        # Determine response based on intent
        if intent == "human_escalation":
            result["response"] = (
                "I understand you'd like to speak with a human agent. "
                "I'll transfer you to our support team right away. "
                "Please hold for a moment."
            )
            result["transfer_to_human"] = True

        elif intent == "order_status":
            # Extract order ID and look up
            import re
            order_match = re.search(r'(ORD[-_]?\d+|\b\d{3,}\b)', text, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(1)
                tool_result = self.tool_executor.execute_tool("get_order_details", {"order_id": order_id})
                if tool_result.get("success") and tool_result["result"].get("found"):
                    order = tool_result["result"]["order"]
                    status = order.get("status", "unknown")
                    tracking = order.get("tracking_number")
                    items = ", ".join(i["name"] for i in order.get("items", []))
                    
                    response = f"Your order containing {items} is currently {status}. "
                    if tracking:
                        response += f"Your tracking number is {tracking}."
                    else:
                        response += "It will be shipped soon and you'll receive tracking information via email."
                    result["response"] = response
                else:
                    result["response"] = f"I'm sorry, I couldn't find an order with ID {order_id}. Please check your order number and try again."
            else:
                result["response"] = "I'd be happy to check your order status. Could you please provide your order number?"

        elif intent == "return_refund":
            result["response"] = (
                "I can help you with a return! You can return items within 30 days of delivery. "
                "Please visit our returns portal at returns.hopcoffee.example.com with your order number and email. "
                "Or I can start the process for you if you have your order number ready."
            )

        elif intent == "subscription_management":
            result["response"] = (
                "I can help with your coffee subscription! You can pause, skip a delivery, or update your plan. "
                "Could you tell me what you'd like to do with your subscription?"
            )

        elif intent == "billing_invoice":
            result["response"] = (
                "I can help with billing questions. If you need a copy of your invoice, "
                "please provide your invoice ID and I'll look it up for you."
            )

        else:
            # Use RAG for general queries, troubleshooting, and product inquiries
            rag_result = self.rag_engine.query(text, top_k=3)
            response = rag_result.get("answer", "")
            
            # Clean up the response for voice (remove markdown, keep it conversational)
            clean_response = self._clean_for_voice(response)
            
            if "couldn't find any relevant information" in response.lower():
                clean_response = (
                    "I'm sorry, I don't have enough information to answer that question. "
                    "Let me transfer you to our support team who can help further."
                )
                result["transfer_to_human"] = True
            
            result["response"] = clean_response

        logger.info(f"Voice query processed: intent={intent}")
        return result

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the voice assistant."""
        return (
            "You are a friendly and professional voice assistant for Hop Coffee Equipment. "
            "Your job is to help customers with their coffee machines, orders, and subscriptions "
            "using the knowledge base. Keep responses concise and conversational since you're speaking. "
            "If you need to look up an order or update a subscription, use the available functions. "
            "If the customer asks to speak to a human, transfer them immediately. "
            "Be warm and helpful - you're talking to real people who love coffee!"
        )

    def _build_vapi_tools(self) -> List[Dict[str, Any]]:
        """Build tool definitions in Vapi's format."""
        return [
            {
                "name": "get_order_details",
                "description": "Fetch the status and tracking information of a customer's order.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The order ID to look up (e.g., ORD-001)",
                        }
                    },
                    "required": ["order_id"],
                },
            },
            {
                "name": "initiate_return",
                "description": "Start a return process for a customer order.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "The order ID to return"},
                        "reason": {"type": "string", "description": "Why the customer is returning"},
                        "email": {"type": "string", "description": "Customer email for verification"},
                    },
                    "required": ["order_id", "reason", "email"],
                },
            },
            {
                "name": "update_subscription",
                "description": "Pause, resume, or cancel a coffee subscription.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subscription_id": {"type": "string", "description": "Subscription ID"},
                        "action": {"type": "string", "enum": ["pause", "resume", "cancel"]},
                        "months": {"type": "integer", "description": "Months to pause", "default": 1},
                    },
                    "required": ["subscription_id", "action"],
                },
            },
        ]

    def _clean_for_voice(self, text: str) -> str:
        """Clean up text for voice output (remove markdown, shorten)."""
        import re
        # Remove markdown headers
        text = re.sub(r'#{1,6}\s+', '', text)
        # Remove bold/italic markers
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'\*', '', text)
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # Limit length for voice
        if len(text) > 500:
            text = text[:497] + "..."
        return text