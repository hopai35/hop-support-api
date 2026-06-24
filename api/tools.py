"""
Hop Support - Tool Definitions & Execution

Implements the function-calling tools that the AI can use to interact
with Hop's internal systems. Tools follow JSON Schema standard format.

Tools:
- get_order_details: Fetch order status and tracking
- initiate_return: Create a return request
- update_subscription: Modify coffee subscription
- search_technical_manuals: Advanced technical document search
- get_invoice: Retrieve invoice details
"""

import logging
import json
from typing import Dict, List, Any, Optional, Callable

from mock_api import MockInternalAPI
from rag_engine import RAGEngine

logger = logging.getLogger(__name__)


# --- Tool Schema Definitions (JSON Schema format) ---

TOOL_DEFINITIONS = [
    {
        "name": "get_order_details",
        "description": "Fetch the status, tracking number, and items of a customer order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID (e.g., ORD-001 or just the number)",
                }
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "initiate_return",
        "description": "Start a return or refund process for an order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "The order ID to return",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the return",
                },
                "email": {
                    "type": "string",
                    "description": "Customer email for verification",
                },
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
                "subscription_id": {
                    "type": "string",
                    "description": "Subscription ID (e.g., SUB-001)",
                },
                "action": {
                    "type": "string",
                    "enum": ["pause", "resume", "cancel"],
                    "description": "Action to perform on the subscription",
                },
                "months": {
                    "type": "integer",
                    "description": "Number of months to pause (default: 1)",
                    "default": 1,
                },
            },
            "required": ["subscription_id", "action"],
        },
    },
    {
        "name": "search_technical_manuals",
        "description": "Search technical documentation and manuals for troubleshooting help.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The technical issue or question",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_invoice",
        "description": "Retrieve an invoice or receipt for billing inquiries.",
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_id": {
                    "type": "string",
                    "description": "Invoice ID (e.g., INV-001)",
                }
            },
            "required": ["invoice_id"],
        },
    },
]


class ToolExecutor:
    """
    Executes tool calls against Hop's internal systems.
    Routes tool names to their handler functions.
    """

    def __init__(self, rag_engine: Optional[RAGEngine] = None):
        self.api = MockInternalAPI()
        self.rag_engine = rag_engine

        self._handlers: Dict[str, Callable] = {
            "get_order_details": self._handle_get_order,
            "initiate_return": self._handle_initiate_return,
            "update_subscription": self._handle_update_subscription,
            "search_technical_manuals": self._handle_search_manuals,
            "get_invoice": self._handle_get_invoice,
        }
        logger.info(f"ToolExecutor initialized with {len(TOOL_DEFINITIONS)} tools")

    @staticmethod
    def get_tool_definitions() -> List[Dict]:
        """Return all tool definitions in JSON Schema format."""
        return TOOL_DEFINITIONS

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name with given arguments.
        
        Args:
            tool_name: Name of the tool to execute.
            arguments: Dict of argument names to values.
            
        Returns:
            Dict with 'success', 'result', and optional 'error' keys.
        """
        handler = self._handlers.get(tool_name)
        if not handler:
            logger.error(f"Unknown tool: {tool_name}")
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}. Available: {list(self._handlers.keys())}",
            }

        try:
            result = handler(**arguments)
            logger.info(f"Tool '{tool_name}' executed successfully")
            return {"success": True, "result": result}
        except TypeError as e:
            logger.error(f"Tool '{tool_name}' argument error: {e}")
            return {"success": False, "error": f"Invalid arguments: {str(e)}"}
        except Exception as e:
            logger.error(f"Tool '{tool_name}' execution error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_get_order(self, order_id: str) -> Dict:
        """Handle order lookup."""
        # First try exact match
        order = self.api.get_order_details(order_id)
        if order:
            return {
                "found": True,
                "order": order,
            }

        # Try with ORD- prefix if not provided
        if not order_id.upper().startswith("ORD"):
            order = self.api.get_order_details(f"ORD-{order_id}")
            if order:
                return {"found": True, "order": order}

        return {"found": False, "message": f"Order '{order_id}' not found."}

    def _handle_initiate_return(
        self, order_id: str, reason: str, email: str
    ) -> Dict:
        """Handle return initiation."""
        # Verify order exists first
        order = self.api.get_order_details(order_id)
        if not order:
            if not order_id.upper().startswith("ORD"):
                order = self.api.get_order_details(f"ORD-{order_id}")
            if not order:
                return {"success": False, "message": f"Order '{order_id}' not found."}

        # Check email matches
        if order["customer_email"].lower() != email.lower():
            return {
                "success": False,
                "message": "Email does not match the order. Please use the email associated with the order.",
            }

        result = self.api.initiate_return(order_id, reason, email)
        if result:
            return {"success": True, "return": result}
        return {"success": False, "message": "Could not initiate return."}

    def _handle_update_subscription(
        self, subscription_id: str, action: str, months: int = 1
    ) -> Dict:
        """Handle subscription modification."""
        result = self.api.update_subscription(subscription_id, action, months)
        if result:
            return {"success": True, "subscription": result}
        return {
            "success": False,
            "message": f"Subscription '{subscription_id}' not found.",
        }

    def _handle_search_manuals(self, query: str) -> Dict:
        """Handle technical manual search via RAG."""
        results = []
        if self.rag_engine:
            retrieved = self.rag_engine.retrieve(query, top_k=3)
            results = [
                {"title": r["title"], "content": r["content"], "source": r["source"]}
                for r in retrieved
            ]

        return {
            "found": len(results) > 0,
            "results": results,
            "message": f"Found {len(results)} relevant documents."
            if results
            else "No relevant technical documents found.",
        }

    def _handle_get_invoice(self, invoice_id: str) -> Dict:
        """Handle invoice retrieval."""
        invoice = self.api.get_invoice(invoice_id)
        if invoice:
            return {"found": True, "invoice": invoice}
        return {"found": False, "message": f"Invoice '{invoice_id}' not found."}