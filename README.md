# Hop Support - AI Customer Support System

## Phase 3: Intent Detection & Tool Use

Extends the RAG + CRM system with intelligent intent detection and tool-calling capabilities.

### New Files

```
hop-support/api/
├── intent_classifier.py    # Hybrid intent detection (keyword + LLM)
├── tools.py                # Tool definitions + executor (order, return, subscription)
├── mock_api.py             # Simulated internal systems (orders, subscriptions, billing)
├── main.py                 # Updated with /detect-intent, /execute-tool, /assist endpoints
```

### Architecture

```
User Query
    │
    ▼
┌─────────────────┐
│ Intent Detector  │  ← Hybrid: keyword matching + LLM fallback
│ (classify)       │
└────────┬────────┘
         │
    ┌────┴────┬─────────────┬──────────────┐
    ▼         ▼             ▼              ▼
Order Status  Return/Refund Subscription   FAQ/RAG
    │         │             │              │
    ▼         ▼             ▼              ▼
┌─────────────────────────────────────────┐
│ Tool Executor                            │
│ - get_order_details                      │
│ - initiate_return                        │
│ - update_subscription                   │
│ - search_technical_manuals              │
│ - get_invoice                           │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Mock Internal API                        │
│ - Order database (ORD-001 to ORD-004)   │
│ - Subscription service (SUB-001/002)    │
│ - Return/CRM proxy                      │
└─────────────────────────────────────────┘
```

### Intent Detection

Uses a **hybrid router** approach:
1. **Keyword matching** (fast): pre-built keyword → intent map
2. **Pattern matching** (mock LLM): regex-based patterns for refinement
3. **OpenAI LLM** (optional): full LLM-based classification when `OPENAI_API_KEY` is set

| Intent | Sample Query |
|--------|-------------|
| `order_status` | "Where is my order #ORD-001?" |
| `technical_troubleshooting` | "My Espresso Pro isn't heating up" |
| `return_refund` | "I want to return my grinder" |
| `product_inquiry` | "What's the difference between Pro and Classic?" |
| `subscription_management` | "Pause my coffee subscription" |
| `billing_invoice` | "Can I get a copy of my invoice?" |
| `human_escalation` | "I need to talk to a person" |
| `general_faq` | "What are your shipping times?" |

### Tools

| Tool | Description | Arguments |
|------|-------------|-----------|
| `get_order_details` | Fetch order status | `order_id` |
| `initiate_return` | Start a return | `order_id`, `reason`, `email` |
| `update_subscription` | Modify subscription | `subscription_id`, `action` (pause/resume/cancel), `months` |
| `search_technical_manuals` | Search technical docs | `query` |
| `get_invoice` | Get invoice details | `invoice_id` |

### Sample Data (Mock)

| Order | Customer | Status |
|-------|----------|--------|
| ORD-001 | alice@example.com | Shipped |
| ORD-002 | bob@example.com | Processing |
| ORD-003 | carol@example.com | Delivered |
| ORD-004 | alice@example.com | Cancelled |

### API Endpoints (Phase 3)

- `POST /detect-intent` - Classify query intent: `{"query": "Where is my order?"}` → `{"intent": "order_status", "confidence": 0.85}`
- `POST /execute-tool` - Execute a tool: `{"tool_name": "get_order_details", "arguments": {"order_id": "ORD-001"}}`
- `GET /tools` - List all available tools with JSON schemas
- `POST /assist` - Full pipeline: detect → execute → respond → escalate

### Environment Variables

- `LLM_PROVIDER`: `mock` (default) or `openai`
- `OPENAI_API_KEY`: For real LLM classification
- `CRM_PROVIDER`: `mock` (default), `zendesk`, or `salesforce`
