"""
Hop Support - FastAPI Web Application

Provides a REST API for the RAG-based AI customer support system
with CRM integration (Phase 2), Intent Detection + Tool Use (Phase 3),
and Feedback Loop + Tuning (Phase 4).

Endpoints:
- GET  /health                    - Health check
- POST /query                     - Ask a question to the RAG bot
- POST /ingest                    - Re-ingest all knowledge base documents
- POST /crm/tickets               - Create a support ticket
- GET  /crm/tickets/{id}          - Get ticket details
- PUT  /crm/tickets/{id}          - Update a ticket
- POST /crm/tickets/{id}/comment  - Add comment to a ticket
- GET  /crm/tickets               - Find tickets by email
- POST /crm/smart-ticket          - AI-powered: query + auto-create ticket
- POST /detect-intent             - Classify a customer query into an intent
- POST /execute-tool              - Execute a tool with given arguments
- POST /assist                    - Full AI pipeline: detect intent + execute tools + respond
- POST /feedback/response         - Record thumbs up/down feedback
- POST /feedback/session          - Record session star rating
- POST /feedback/escalation       - Record escalation reason
- GET  /admin/metrics             - Get aggregate feedback metrics
- GET  /admin/failures/summary    - Get failure analysis summary
- POST /admin/failures/analyze    - Run failure analysis
- POST /admin/evaluation/run      - Run golden dataset evaluation
- GET  /admin/evaluation/history  - Get evaluation history
- GET  /admin/dashboard           - Admin HTML dashboard
- GET  /demo/brands               - List all brand demo environments
- POST /demo/query/{brand}        - Query a specific brand's KB with voice persona
- POST /demo/voice/{brand}        - Voice query for a specific brand
- POST /demo/seed/{brand}         - Seed a brand's ChromaDB collection
"""

import os
import sys
import logging
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rag_engine import RAGEngine
from crm import get_crm_provider
from crm.base import Ticket
from intent_classifier import IntentClassifier
from tools import ToolExecutor
from feedback_store import FeedbackStore
from failure_analysis import FailureAnalyzer
from evaluator import GoldenDatasetEvaluator
from vapi_handler import VapiHandler
from demo_manager import DemoManager
from state_store import state_store
from pii_redactor import PIIRedactor
from social_handler import router as social_router
import social_handler as social_hub

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
DEFAULT_KB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb"
)
DEFAULT_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "chroma",
)

# Initialize RAG Engine
rag_engine = RAGEngine(
    persist_dir=os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR),
    llm_provider=os.getenv("LLM_PROVIDER", "mock"),
    llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
    openai_api_key=os.getenv("OPENAI_API_KEY"),
)

# Initialize CRM Provider
crm_provider = get_crm_provider()

# Initialize Intent Classifier
intent_classifier = IntentClassifier(llm_provider=os.getenv("LLM_PROVIDER", "mock"))

# Initialize Tool Executor
tool_executor = ToolExecutor(rag_engine=rag_engine)

# Initialize Phase 4: Feedback & Evaluation
feedback_store = FeedbackStore()
failure_analyzer = FailureAnalyzer(feedback_store)
golden_evaluator = GoldenDatasetEvaluator()

# Initialize Phase 7: Vapi Voice Integration
vapi_handler = VapiHandler(
    rag_engine=rag_engine,
    intent_classifier=intent_classifier,
    tool_executor=tool_executor,
    crm_provider=crm_provider,
)

# Inject engines into Social Hub (Meta/Instagram/WhatsApp handler)
social_hub.set_engines(rag_engine=rag_engine, intent_classifier=intent_classifier)

# Initialize Demo Manager (Multi-Brand)
demo_manager = DemoManager()

# Initialize Omni-Hub State Store (Multi-Channel) - uses module-level singleton from state_store.py
# state_store is imported at the top of this file

# Auto-ingest on startup
kb_dir = os.getenv("KB_DIR", DEFAULT_KB_DIR)
if os.path.isdir(kb_dir):
    num_chunks = rag_engine.ingest_documents(kb_dir)
    logger.info(f"Auto-ingested {num_chunks} chunks from {kb_dir}")

# FastAPI app
app = FastAPI(
    title="Hop Support AI API",
    description="AI-powered customer support with RAG + CRM + Intent Detection + Tool Use + Social Hub",
    version="3.1.0",
)

# Register Social Hub router (Meta Graph: Instagram & WhatsApp webhooks)
app.include_router(social_router, prefix="/social")


# --- Request/Response Models ---

class QueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 3

class QueryResponse(BaseModel):
    answer: str
    sources: list
    query: str

class IngestRequest(BaseModel):
    directory: Optional[str] = None

class IngestResponse(BaseModel):
    status: str
    chunks_ingested: int
    directory: str

class HealthResponse(BaseModel):
    status: str
    collection_size: int
    llm_provider: str
    crm_provider: str
    tools_available: int

class TicketCreateRequest(BaseModel):
    subject: str
    description: str
    requester_email: str
    requester_name: Optional[str] = None
    priority: Optional[str] = "normal"

class TicketUpdateRequest(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None

class CommentRequest(BaseModel):
    comment: str
    is_public: Optional[bool] = True

class SmartTicketRequest(BaseModel):
    query: str
    requester_email: str
    requester_name: Optional[str] = None
    auto_create_if_unanswered: Optional[bool] = True
    top_k: Optional[int] = 3

class SmartTicketResponse(BaseModel):
    answer: str
    sources: list
    ticket_created: bool
    ticket: Optional[dict] = None

class IntentDetectionRequest(BaseModel):
    query: str

class IntentDetectionResponse(BaseModel):
    intent: str
    confidence: float
    method: str

class ToolExecuteRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]

class ToolExecuteResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None

class AssistRequest(BaseModel):
    query: str
    requester_email: Optional[str] = None

class AssistResponse(BaseModel):
    query: str
    intent: IntentDetectionResponse
    tool_calls: List[ToolExecuteResponse] = []
    final_response: str
    ticket_created: bool = False
    ticket: Optional[dict] = None


# --- API Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        collection_size=rag_engine.collection.count(),
        llm_provider=rag_engine.llm_provider,
        crm_provider=crm_provider.get_name(),
        tools_available=len(ToolExecutor.get_tool_definitions()),
    )


@app.post("/query", response_model=QueryResponse)
async def query(query_req: QueryRequest):
    if not query_req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if rag_engine.collection.count() == 0:
        raise HTTPException(status_code=400, detail="Knowledge base is empty.")
    try:
        result = rag_engine.query(query_req.query, top_k=query_req.top_k)
        return QueryResponse(**result)
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest = None):
    directory = request.directory if request and request.directory else kb_dir
    if not os.path.isdir(directory):
        raise HTTPException(status_code=400, detail=f"Directory not found: {directory}")
    try:
        rag_engine.reset_collection()
        num_chunks = rag_engine.ingest_documents(directory)
        return IngestResponse(status="success", chunks_ingested=num_chunks, directory=directory)
    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- CRM Endpoints ---

@app.post("/crm/tickets")
async def create_ticket(ticket_req: TicketCreateRequest):
    try:
        ticket = Ticket(
            subject=ticket_req.subject,
            description=ticket_req.description,
            requester_email=ticket_req.requester_email,
            requester_name=ticket_req.requester_name,
            priority=ticket_req.priority,
        )
        result = crm_provider.create_ticket(ticket)
        return {"status": "success", "ticket": result.to_dict()}
    except Exception as e:
        logger.error(f"Ticket creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/crm/tickets/{ticket_id}")
async def get_ticket(ticket_id: str):
    try:
        ticket = crm_provider.get_ticket(ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return {"status": "success", "ticket": ticket.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/crm/tickets/{ticket_id}")
async def update_ticket(ticket_id: str, updates: TicketUpdateRequest):
    try:
        update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}
        if not update_dict:
            raise HTTPException(status_code=400, detail="No fields to update")
        ticket = crm_provider.update_ticket(ticket_id, update_dict)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return {"status": "success", "ticket": ticket.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/crm/tickets/{ticket_id}/comment")
async def add_comment(ticket_id: str, comment_req: CommentRequest):
    try:
        success = crm_provider.add_comment(ticket_id, comment_req.comment, comment_req.is_public)
        if not success:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return {"status": "success", "message": "Comment added"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/crm/tickets")
async def find_tickets(email: str = Query(..., description="Requester email")):
    try:
        tickets = crm_provider.find_tickets_by_email(email)
        return {"status": "success", "tickets": [t.to_dict() for t in tickets], "count": len(tickets)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/crm/smart-ticket", response_model=SmartTicketResponse)
async def smart_ticket(request: SmartTicketRequest):
    if rag_engine.collection.count() == 0:
        raise HTTPException(status_code=400, detail="Knowledge base is empty.")
    try:
        result = rag_engine.query(request.query, top_k=request.top_k)
        ticket_created = False
        ticket = None
        if request.auto_create_if_unanswered:
            should_escalate = (
                "couldn't find any relevant information" in result["answer"]
                or "contact a human agent" in result["answer"]
                or "contact support" in result["answer"].lower()
            )
            if should_escalate:
                crm_ticket = Ticket(
                    subject=f"AI Escalation: {request.query[:100]}",
                    description=f"Automatically created from AI query.\n\nCustomer query: {request.query}\n\nAI response: {result['answer']}\n\nReason: Query could not be fully resolved by AI.",
                    requester_email=request.requester_email,
                    requester_name=request.requester_name or request.requester_email.split("@")[0],
                    priority="normal",
                    tags=["ai-escalation"],
                )
                created = crm_provider.create_ticket(crm_ticket)
                ticket_created = True
                ticket = created.to_dict()
        return SmartTicketResponse(answer=result["answer"], sources=result["sources"], ticket_created=ticket_created, ticket=ticket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Phase 3: Intent Detection & Tool Use Endpoints ---

@app.post("/detect-intent", response_model=IntentDetectionResponse)
async def detect_intent(request: IntentDetectionRequest):
    """
    Classify a customer query into one of the supported intents.
    
    Uses hybrid approach: fast keyword matching first, then LLM fallback.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        result = intent_classifier.classify(request.query)
        return IntentDetectionResponse(**result)
    except Exception as e:
        logger.error(f"Intent detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/execute-tool", response_model=ToolExecuteResponse)
async def execute_tool(request: ToolExecuteRequest):
    """
    Execute a tool with the given arguments.
    
    Available tools:
    - get_order_details: Fetch order status
    - initiate_return: Start a return
    - update_subscription: Modify subscription
    - search_technical_manuals: Search technical docs
    - get_invoice: Retrieve invoice
    """
    try:
        result = tool_executor.execute_tool(request.tool_name, request.arguments)
        return ToolExecuteResponse(**result)
    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tools")
async def list_tools():
    """List all available tools and their JSON schemas."""
    return {
        "tools": ToolExecutor.get_tool_definitions(),
        "count": len(ToolExecutor.get_tool_definitions()),
    }


@app.post("/assist", response_model=AssistResponse)
async def assist(request: AssistRequest):
    """
    Full AI pipeline:
    1. Detect intent from user query
    2. If intent requires a tool, execute it
    3. Generate response using RAG + tool results
    4. Optionally create a CRM ticket for escalations
    
    This is the main "smart assistant" endpoint that ties everything together.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query = request.query

        # Step 1: Detect intent
        intent_result = intent_classifier.classify(query)
        intent = intent_result["intent"]
        logger.info(f"Assist: detected intent={intent} for query='{query[:50]}...'")

        # Step 2: Determine which tools to call based on intent
        tool_results = []
        final_response = ""
        ticket_created = False
        ticket = None

        if intent == "order_status":
            # Try to extract order ID from query
            import re
            order_match = re.search(r'(ORD[-_]?\d+|\b\d{3}\b)', query, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(1)
                tool_result = tool_executor.execute_tool("get_order_details", {"order_id": order_id})
                tool_results.append(ToolExecuteResponse(**tool_result))
                if tool_result["success"] and tool_result["result"].get("found"):
                    order = tool_result["result"]["order"]
                    final_response = (
                        f"Your order {order['order_id']} is **{order['status']}**.\n\n"
                        f"Items: {', '.join(i['name'] for i in order['items'])}\n"
                        f"Total: ${order['total']:.2f}\n"
                    )
                    if order.get("tracking_number"):
                        final_response += (
                            f"Tracking: {order['tracking_number']} ({order.get('carrier', 'N/A')})\n"
                            f"Estimated delivery: {order.get('estimated_delivery', 'N/A')}"
                        )
                    else:
                        final_response += "Tracking information will be available once shipped."
                else:
                    # Fall back to RAG
                    rag_result = rag_engine.query(query)
                    final_response = rag_result["answer"]
            else:
                rag_result = rag_engine.query(query)
                final_response = rag_result["answer"]

        elif intent == "return_refund":
            import re
            order_match = re.search(r'(ORD[-_]?\d+|\b\d{3}\b)', query, re.IGNORECASE)
            if order_match and request.requester_email:
                order_id = order_match.group(1)
                tool_result = tool_executor.execute_tool(
                    "initiate_return",
                    {"order_id": order_id, "reason": query, "email": request.requester_email}
                )
                tool_results.append(ToolExecuteResponse(**tool_result))
                if tool_result["success"] and tool_result["result"].get("success"):
                    ret = tool_result["result"]["return"]
                    final_response = (
                        f"Return initiated successfully! Your return ID is **{ret['return_id']}**.\n"
                        f"Status: {ret['status']}\n"
                        f"We'll review your request and get back to you soon."
                    )
                elif tool_result["success"] and not tool_result["result"].get("success"):
                    final_response = tool_result["result"].get("message", "Could not process return.")
                else:
                    rag_result = rag_engine.query(query)
                    final_response = rag_result["answer"]
            else:
                rag_result = rag_engine.query(query)
                final_response = rag_result["answer"]

        elif intent == "subscription_management":
            import re
            sub_match = re.search(r'(SUB[-_]?\d+)', query, re.IGNORECASE)
            action = "pause"
            if any(w in query.lower() for w in ["resume", "reactivate", "start"]):
                action = "resume"
            elif any(w in query.lower() for w in ["cancel", "stop", "end"]):
                action = "cancel"

            if sub_match:
                sub_id = sub_match.group(1)
                tool_result = tool_executor.execute_tool(
                    "update_subscription", {"subscription_id": sub_id, "action": action}
                )
                tool_results.append(ToolExecuteResponse(**tool_result))
                if tool_result["success"] and tool_result["result"].get("success"):
                    sub = tool_result["result"]["subscription"]
                    final_response = (
                        f"Subscription **{sub['subscription_id']}** has been **{action}ed**.\n"
                        f"Current status: {sub['status']}"
                    )
                else:
                    final_response = tool_result["result"].get("message", f"Could not {action} subscription.")
            else:
                final_response = "I'd be happy to help with your subscription! Could you provide your subscription ID (e.g., SUB-001)?"

        elif intent == "billing_invoice":
            import re
            inv_match = re.search(r'(INV[-_]?\d+)', query, re.IGNORECASE)
            if inv_match:
                inv_id = inv_match.group(1)
                tool_result = tool_executor.execute_tool("get_invoice", {"invoice_id": inv_id})
                tool_results.append(ToolExecuteResponse(**tool_result))
                if tool_result["success"] and tool_result["result"].get("found"):
                    inv = tool_result["result"]["invoice"]
                    final_response = (
                        f"Invoice **{inv['invoice_id']}**\n"
                        f"Amount: ${inv['amount']:.2f}\n"
                        f"Date: {inv['date']}\n"
                        f"Status: {inv['status']}\n"
                        f"Items: {', '.join(inv['items'])}"
                    )
                else:
                    final_response = "I couldn't find that invoice. Please double-check the invoice ID."
            else:
                final_response = "Please provide your invoice ID (e.g., INV-001) and I'll look it up for you."

        elif intent == "technical_troubleshooting":
            tool_result = tool_executor.execute_tool("search_technical_manuals", {"query": query})
            tool_results.append(ToolExecuteResponse(**tool_result))
            if tool_result["success"] and tool_result["result"].get("found"):
                docs = tool_result["result"]["results"]
                final_response = "Based on our technical documentation:\n\n"
                for i, doc in enumerate(docs[:2], 1):
                    final_response += f"{doc['content'][:500]}\n\n"
            else:
                rag_result = rag_engine.query(query)
                final_response = rag_result["answer"]

        elif intent == "human_escalation":
            if request.requester_email:
                crm_ticket = Ticket(
                    subject=f"Escalation Request: {query[:100]}",
                    description=f"Customer requested human agent.\n\nQuery: {query}",
                    requester_email=request.requester_email,
                    priority="high",
                    tags=["escalation"],
                )
                created = crm_provider.create_ticket(crm_ticket)
                ticket_created = True
                ticket = created.to_dict()
                final_response = (
                    f"I've created an escalation ticket **{created.id}** for you. "
                    f"A human agent will get back to you shortly at {request.requester_email}."
                )
            else:
                final_response = (
                    "I understand you'd like to speak with a human agent. "
                    "Please provide your email so I can create an escalation ticket."
                )

        else:  # general_faq, product_inquiry, unknown
            rag_result = rag_engine.query(query)
            final_response = rag_result["answer"]

        # Step 4: Create escalation ticket if needed (for unanswered queries)
        if not ticket_created and request.requester_email and intent not in ("order_status", "subscription_management", "human_escalation"):
            should_escalate = (
                "couldn't find any relevant information" in final_response
                or "contact a human agent" in final_response
                or "contact support" in final_response.lower()
            )
            if should_escalate:
                crm_ticket = Ticket(
                    subject=f"AI Escalation: {query[:100]}",
                    description=f"AI could not resolve query.\n\nQuery: {query}\n\nIntent: {intent}\n\nResponse: {final_response}",
                    requester_email=request.requester_email,
                    priority="normal",
                    tags=["ai-escalation"],
                )
                created = crm_provider.create_ticket(crm_ticket)
                ticket_created = True
                ticket = created.to_dict()

        return AssistResponse(
            query=query,
            intent=IntentDetectionResponse(**intent_result),
            tool_calls=tool_results,
            final_response=final_response,
            ticket_created=ticket_created,
            ticket=ticket,
        )

    except Exception as e:
        logger.error(f"Assist pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Phase 4: Feedback Loop & Evaluation Endpoints ---

@app.post("/feedback/response")
async def record_response_feedback(
    interaction_id: str = Query(...),
    rating: int = Query(..., description="1 for thumbs up, -1 for thumbs down"),
    query: str = Query(""),
    response: str = Query(""),
    intent: str = Query("unknown"),
    confidence: float = Query(0.0),
):
    """Record thumbs up/down feedback on an AI response."""
    try:
        record = feedback_store.record_response_feedback(
            interaction_id=interaction_id,
            rating=rating,
            query=query,
            response=response,
            intent=intent,
            confidence=confidence,
        )
        return {"status": "success", "feedback": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback/session")
async def record_session_survey(
    interaction_id: str = Query(...),
    rating: int = Query(..., ge=1, le=5),
    comment: Optional[str] = Query(""),
):
    """Record a session-level 1-5 star rating."""
    try:
        record = feedback_store.record_session_survey(
            interaction_id=interaction_id,
            rating=rating,
            comment=comment,
        )
        return {"status": "success", "feedback": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback/escalation")
async def record_escalation_reason(
    interaction_id: str = Query(...),
    reason: str = Query(...),
    query: str = Query(""),
    intent: str = Query("unknown"),
):
    """Record why a user requested human escalation."""
    try:
        record = feedback_store.record_escalation_reason(
            interaction_id=interaction_id,
            reason=reason,
            query=query,
            intent=intent,
        )
        return {"status": "success", "feedback": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/metrics")
async def get_metrics():
    """Get aggregate feedback metrics for the admin dashboard."""
    try:
        metrics = feedback_store.get_metrics()
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/failures/summary")
async def get_failure_summary():
    """Get failure analysis summary with category breakdown."""
    try:
        summary = failure_analyzer.get_analysis_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/failures/analyze")
async def run_failure_analysis():
    """Run failure analysis on all un-analyzed interaction failures."""
    try:
        results = failure_analyzer.analyze_all_failures()
        return {"status": "success", "analyzed": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/evaluation/run")
async def run_evaluation():
    """Run golden dataset evaluation to measure intent accuracy."""
    try:
        result = golden_evaluator.evaluate(
            rag_engine=rag_engine,
            intent_classifier=intent_classifier,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/evaluation/history")
async def get_evaluation_history():
    """Get historical evaluation results."""
    try:
        history = golden_evaluator.get_evaluation_history()
        return {"history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/dashboard")
async def get_admin_dashboard():
    """Serve the admin HTML dashboard."""
    from fastapi.responses import HTMLResponse
    dashboard_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "admin_dashboard.html"
    )
    if not os.path.exists(dashboard_path):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    with open(dashboard_path, "r") as f:
        return HTMLResponse(content=f.read(), media_type="text/html")


@app.get("/admin/feedback")
async def get_feedback_data(
    date: Optional[str] = None,
    failures_only: bool = False,
):
    """Get raw feedback data for a specific date."""
    try:
        if date:
            records = feedback_store.get_feedback_by_date(date, failures_only)
        else:
            records = feedback_store.get_all_failures() if failures_only else []
        return {"records": records, "count": len(records)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Phase 7: Vapi Voice Integration Endpoints ---

class VapiWebhookRequest(BaseModel):
    """Vapi webhook payload (simplified)."""
    type: Optional[str] = "assistant-request"
    call: Optional[Dict] = None
    function: Optional[Dict] = None
    status: Optional[str] = None
    transcript: Optional[str] = None
    cost: Optional[float] = None
    endedReason: Optional[str] = None


class VoiceQueryRequest(BaseModel):
    text: str


@app.post("/redact")
async def redact_phi(
    text: str = Query(..., description="Text to redact PHI from"),
):
    """
    Test the PHI redaction Guardian Layer.
    
    Applies regex-based PII/PHI redaction to the input text and returns
    both the redacted result and verification statistics.
    
    Used by the Sales Specialist to verify HIPAA compliance for Hims & Hers demo.
    """
    redacted = PIIRedactor.redact_input(text)
    verification = PIIRedactor.verify(text, redacted)
    return {
        "original": text,
        "redacted": redacted,
        "phi_found": verification["phi_found"],
        "phi_count": verification["phi_count"],
        "categories": verification["categories"],
        "redaction_ok": verification["redaction_ok"],
    }


class DemoRedactRequest(BaseModel):
    text: str
    brand: Optional[str] = "hims_hers"


@app.post("/demo/verify-redaction")
async def demo_verify_redaction(request: DemoRedactRequest):
    """
    Demo endpoint for Hims & Hers PHI redaction verification.
    
    Accepts a text string (simulating a customer message) and returns:
    - original: The input text
    - redacted: The text with all PHI/PII redacted
    - phi_found: Whether any PHI was detected
    - phi_count: Number of PHI items redacted
    - categories: Which categories were detected
    - redaction_ok: Whether redaction was complete
    
    This is the primary endpoint for the Monday Hims & Hers demo
    with Andrew Dudum to verify HIPAA compliance.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    redacted = PIIRedactor.redact_input(request.text)
    verification = PIIRedactor.verify(request.text, redacted)

    return {
        "brand": request.brand,
        "original": request.text,
        "redacted": redacted,
        "phi_found": verification["phi_found"],
        "phi_count": verification["phi_count"],
        "categories": verification["categories"],
        "redaction_ok": verification["redaction_ok"],
        "note": "This demonstrates the Guardian Layer PHI redaction for HIPAA compliance.",
    }


@app.post("/voice/vapi/webhook")
async def vapi_webhook(request: VapiWebhookRequest):
    """
    Handle Vapi.ai server webhooks for real-time voice support.
    
    Vapi sends different message types during a phone call:
    - assistant-request: Configure the AI assistant at call start
    - function-call: Execute a tool (order lookup, subscription update)
    - status-update: Call status notification
    - end-of-call-report: Call summary when call ends
    """
    try:
        payload = request.model_dump(exclude_none=True)
        result = vapi_handler.handle_webhook(payload)
        return result
    except Exception as e:
        logger.error(f"Vapi webhook failed: {e}")
        return {"error": str(e)}


@app.post("/voice/vapi/query")
async def voice_query(request: VoiceQueryRequest):
    """
    Simulate a voice query transcription through the AI pipeline.
    
    This endpoint allows testing the voice logic without a real Vapi connection.
    Accepts text as if it came from speech-to-text and returns a spoken response.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Query text cannot be empty")
    
    try:
        result = vapi_handler.process_voice_query(request.text)
        return result
    except Exception as e:
        logger.error(f"Voice query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Multi-Brand Demo Endpoints ---

@app.get("/demo/brands")
async def list_brands():
    """List all available brand demo environments."""
    brands = []
    for brand_key in demo_manager.brands:
        info = demo_manager.get_brand_info(brand_key)
        brands.append({
            "key": brand_key,
            "name": info.get("display_name", brand_key),
            "pitch": info.get("pitch", ""),
        })
    
    metrics = demo_manager.get_metrics()
    for b in brands:
        key = b["key"]
        if key in metrics:
            b["kb_documents"] = metrics[key]["collection_size"]

    return {
        "default_brand": demo_manager.default_brand,
        "brands": brands,
        "count": len(brands),
    }


class DemoQueryRequest(BaseModel):
    query: str
    brand: Optional[str] = None


@app.post("/demo/query/{brand}")
async def demo_query(brand: str, request: DemoQueryRequest):
    """
    Query a specific brand's knowledge base.
    
    The brand KB is looked up from its ChromaDB collection,
    and responses are tailored to that brand's domain.
    """
    if brand not in demo_manager.brands:
        available = ", ".join(demo_manager.brands)
        raise HTTPException(status_code=404, detail=f"Brand '{brand}' not found. Available: {available}")

    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        # Use tier-based redaction pipeline (Healthcare → Skyflow, others → regex)
        result = demo_manager.process_query_with_redaction(
            query=request.query, brand=brand
        )
        return result
    except Exception as e:
        logger.error(f"Demo query failed for {brand}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DemoVoiceRequest(BaseModel):
    text: str
    brand: Optional[str] = None


@app.post("/demo/voice/{brand}")
async def demo_voice(brand: str, request: DemoVoiceRequest):
    """
    Voice query for a specific brand demo.
    
    Processes through the brand's Vapi handler with its specific
    voice persona and domain knowledge.
    """
    if brand not in demo_manager.brands:
        available = ", ".join(demo_manager.brands)
        raise HTTPException(status_code=404, detail=f"Brand '{brand}' not found. Available: {available}")

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Query text cannot be empty")

    try:
        result = demo_manager.process_voice_query(request.text, brand=brand)
        return result
    except Exception as e:
        logger.error(f"Demo voice failed for {brand}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/demo/seed/{brand}")
async def demo_seed(brand: str):
    """
    Seed a brand's ChromaDB collection by ingesting its KB articles.
    """
    if brand not in demo_manager.brands:
        available = ", ".join(demo_manager.brands)
        raise HTTPException(status_code=404, detail=f"Brand '{brand}' not found. Available: {available}")

    try:
        engine = demo_manager.get_rag_engine(brand)
        kb_dir = demo_manager.get_kb_dir(brand)
        
        # Reset and re-ingest
        engine.reset_collection()
        num_chunks = engine.ingest_documents(kb_dir)
        
        brand_info = demo_manager.get_brand_info(brand)
        return {
            "brand": brand,
            "brand_name": brand_info.get("display_name", brand),
            "status": "success",
            "chunks_ingested": num_chunks,
            "kb_directory": kb_dir,
        }
    except Exception as e:
        logger.error(f"Demo seed failed for {brand}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Warby Parker Salesforce Integration ---

@app.post("/wp/case")
async def wp_create_case(
    subject: str = Query(...),
    description: str = Query(...),
    requester_email: str = Query(...),
    intent: str = Query("general_faq"),
    confidence: float = Query(0.5),
):
    """
    Create a Warby Parker Salesforce Case mapped from AI intent.
    
    Maps Hop Support intents to Warby Parker Case record types:
    - order_status → Order_Status_Inquiry
    - return_refund → Return_Refund
    - technical_troubleshooting → Technical_Support
    - billing_invoice → Billing_Invoice
    - subscription_management → Subscription_Change
    - human_escalation → Escalation
    """
    from crm import get_crm_provider
    from crm.base import Ticket
    
    wp_provider = get_crm_provider("warby_parker")
    
    ticket = Ticket(
        subject=subject,
        description=description,
        requester_email=requester_email,
    )
    
    try:
        result = wp_provider.create_case_from_intent(ticket, intent, confidence)
        return {"status": "success", "case": result.to_dict()}
    except Exception as e:
        logger.error(f"WP case creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/wp/rx/{prescription_id}")
async def wp_get_rx(prescription_id: str):
    """
    Retrieve a Warby Parker prescription from Salesforce.
    Returns right eye (OD), left eye (OS), PD, and verification status.
    """
    from crm import get_crm_provider
    
    wp_provider = get_crm_provider("warby_parker")
    
    try:
        rx = wp_provider.get_rx_prescription(prescription_id)
        if not rx:
            raise HTTPException(status_code=404, detail=f"Prescription {prescription_id} not found")
        return {"status": "success", "prescription": rx}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RX lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/wp/orders")
async def wp_get_orders(email: str = Query(...)):
    """
    Get Warby Parker order history for a customer.
    Returns orders with frame style, lens type, and status.
    """
    from crm import get_crm_provider
    
    wp_provider = get_crm_provider("warby_parker")
    
    try:
        orders = wp_provider.get_customer_orders(email)
        return {"status": "success", "orders": orders, "count": len(orders)}
    except Exception as e:
        logger.error(f"Order lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/wp/tryon/{try_on_id}")
async def wp_get_tryon(try_on_id: str):
    """
    Check the status of a Warby Parker Home Try-On.
    """
    from crm import get_crm_provider
    
    wp_provider = get_crm_provider("warby_parker")
    
    try:
        status = wp_provider.get_home_try_on_status(try_on_id)
        if not status:
            raise HTTPException(status_code=404, detail=f"Home Try-On {try_on_id} not found")
        return {"status": "success", "try_on": status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Try-On lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Intent-to-Salesforce Case mapping endpoint ---

@app.get("/wp/intent-map")
async def wp_intent_map():
    """
    Get the Warby Parker intent-to-Salesforce Case type mapping.
    Used for configuration and debugging.
    """
    from crm.warby_parker import WP_INTENT_TO_CASE_TYPE
    return {
        "mapping": WP_INTENT_TO_CASE_TYPE,
        "count": len(WP_INTENT_TO_CASE_TYPE),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)