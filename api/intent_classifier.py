"""
Hop Support - Intent Detection & Classification

Implements a hybrid intent detection system:
1. Vector-based semantic similarity against gold-standard utterances
2. LLM-based classifier fallback for ambiguous queries
3. Intent taxonomy for Hop Support's customer support scenarios
"""

import logging
import re
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Primary customer support intents for Hop Support."""
    ORDER_STATUS = "order_status"
    TECHNICAL_TROUBLESHOOTING = "technical_troubleshooting"
    RETURN_REFUND = "return_refund"
    PRODUCT_INQUIRY = "product_inquiry"
    SUBSCRIPTION_MANAGEMENT = "subscription_management"
    BILLING_INVOICE = "billing_invoice"
    HUMAN_ESCALATION = "human_escalation"
    GENERAL_FAQ = "general_faq"
    UNKNOWN = "unknown"


# Gold-standard utterances for each intent (used for semantic matching)
INTENT_UTTERANCES: Dict[Intent, List[str]] = {
    Intent.ORDER_STATUS: [
        "Where is my order",
        "What is the status of my order",
        "Has my order shipped",
        "Track my order",
        "When will my order arrive",
        "Order delivery status",
        "Where's my package",
        "Tracking number",
        "Check my order",
    ],
    Intent.TECHNICAL_TROUBLESHOOTING: [
        "My machine is not working",
        "How do I fix",
        "Troubleshooting",
        "Not heating up",
        "Error code",
        "Machine won't turn on",
        "Leaking water",
        "Not brewing properly",
        "Technical issue",
        "It's broken",
    ],
    Intent.RETURN_REFUND: [
        "I want to return",
        "Start a return",
        "Request a refund",
        "Return policy",
        "How do I send this back",
        "Return my order",
        "I want a refund",
        "Cancel and refund",
        "Return my purchase",
    ],
    Intent.PRODUCT_INQUIRY: [
        "What is the difference between",
        "Tell me about",
        "Product specifications",
        "Which model should I buy",
        "What features does",
        "Compare products",
        "Product recommendations",
        "Is this compatible with",
    ],
    Intent.SUBSCRIPTION_MANAGEMENT: [
        "Pause my subscription",
        "Cancel my subscription",
        "Resume my subscription",
        "Change my coffee plan",
        "Subscription delivery",
        "Skip next delivery",
        "Update subscription",
        "Modify my plan",
    ],
    Intent.BILLING_INVOICE: [
        "Copy of my invoice",
        "Billing question",
        "Payment issue",
        "Receipt",
        "Invoice for order",
        "Charge on my card",
        "When was I charged",
        "Billing address",
    ],
    Intent.HUMAN_ESCALATION: [
        "Talk to a person",
        "Speak to an agent",
        "Human support",
        "Real person",
        "Customer service representative",
        "Escalate this",
        "I need a human",
        "Agent please",
    ],
    Intent.GENERAL_FAQ: [
        "How does this work",
        "What is your policy on",
        "Shipping information",
        "Warranty",
        "How long does",
        "Do you offer",
        "Can you tell me more about",
    ],
}


class IntentClassifier:
    """
    Hybrid intent classifier combining keyword/semantic matching
    with LLM-based classification fallback.
    """

    def __init__(self, llm_provider: str = "mock"):
        self.llm_provider = llm_provider
        # Build a keyword index for fast matching
        self._keyword_map = self._build_keyword_map()
        logger.info(f"IntentClassifier initialized (provider={llm_provider})")

    def _build_keyword_map(self) -> Dict[str, Intent]:
        """Build a keyword-to-intent lookup map for fast matching."""
        keyword_map = {}
        for intent, utterances in INTENT_UTTERANCES.items():
            for utterance in utterances:
                # Extract significant keywords (words > 3 chars, skipping common words)
                words = re.findall(r'\b[a-z]{3,}\b', utterance.lower())
                skip_words = {
                    "the", "and", "for", "are", "not", "but", "has", "was",
                    "can", "you", "how", "what", "why", "when", "where",
                    "will", "with", "from", "this", "that", "your", "have",
                    "been", "would", "could", "should", "about", "into",
                    "over", "than", "then", "also", "just", "more",
                }
                for word in words:
                    if word not in skip_words:
                        keyword_map[word] = intent
        return keyword_map

    def classify_keyword(self, query: str) -> Tuple[Optional[Intent], float]:
        """
        Fast keyword-based intent classification.
        
        Returns:
            Tuple of (intent, confidence_score)
        """
        query_lower = query.lower()
        words = re.findall(r'\b[a-z]{2,}\b', query_lower)
        
        intent_scores: Dict[Intent, int] = {}
        for word in words:
            if word in self._keyword_map:
                intent = self._keyword_map[word]
                intent_scores[intent] = intent_scores.get(intent, 0) + 1

        if not intent_scores:
            return None, 0.0

        best_intent = max(intent_scores, key=intent_scores.get)
        max_score = intent_scores[best_intent]
        total_matches = sum(intent_scores.values())
        
        # Confidence: proportion of matched keywords belonging to the top intent
        confidence = max_score / total_matches if total_matches > 0 else 0.0
        
        return best_intent, confidence

    def classify_llm(self, query: str) -> Tuple[Intent, float]:
        """
        LLM-based intent classification for complex/ambiguous queries.
        Falls back to mock if LLM not configured.
        """
        if self.llm_provider == "openai":
            return self._classify_openai(query)
        else:
            return self._classify_mock(query)

    def _classify_mock(self, query: str) -> Tuple[Intent, float]:
        """
        Mock LLM classifier - uses enhanced keyword + pattern matching
        instead of a real LLM.
        """
        query_lower = query.lower()

        # Check for order-specific patterns (order ID references)
        if re.search(r'\b(ORD[-_]?\d+|order\s*#?\s*\d+)\b', query_lower, re.IGNORECASE):
            if any(w in query_lower for w in ["where", "status", "track", "ship", "deliver", "arrive"]):
                return Intent.ORDER_STATUS, 0.85

        # Check for subscription-specific phrases
        if re.search(r'\b(pause|resume|cancel|skip|change|modify)\b.*\b(subscription|plan|delivery|coffee)\b', query_lower):
            return Intent.SUBSCRIPTION_MANAGEMENT, 0.80
        if re.search(r'\b(subscription|plan|delivery)\b.*\b(pause|resume|cancel)\b', query_lower):
            return Intent.SUBSCRIPTION_MANAGEMENT, 0.80

        # Check for return/refund patterns
        if re.search(r'\b(return|refund|send\s*back|money\s*back)\b', query_lower):
            return Intent.RETURN_REFUND, 0.85

        # Check for technical troubleshooting
        if re.search(r'\b(not\s*working|broken|issue|problem|error|fix|repair|leak|won\'?t\s*turn)\b', query_lower):
            return Intent.TECHNICAL_TROUBLESHOOTING, 0.80

        # Check for product inquiry
        if re.search(r'\b(difference|compare|recommend|feature|spec|compatible|which\s+(one|model|should))\b', query_lower):
            return Intent.PRODUCT_INQUIRY, 0.75

        # Check for billing
        if re.search(r'\b(invoice|bill|receipt|charge|payment)\b', query_lower):
            return Intent.BILLING_INVOICE, 0.80

        # Check for human escalation
        if re.search(r'\b(talk\s*to|speak\s*to|human|person|agent|representative|escalate)\b', query_lower):
            return Intent.HUMAN_ESCALATION, 0.85

        # Default to general FAQ
        return Intent.GENERAL_FAQ, 0.50

    def _classify_openai(self, query: str) -> Tuple[Intent, float]:
        """Use OpenAI to classify intent."""
        try:
            from openai import OpenAI
            import os

            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            
            intent_descriptions = "\n".join([
                f"- {intent.value}: {intent.name.replace('_', ' ').title()}"
                for intent in Intent
                if intent != Intent.UNKNOWN
            ])

            prompt = (
                f"Classify the following customer support query into one of these intents:\n"
                f"{intent_descriptions}\n\n"
                f"Query: \"{query}\"\n\n"
                f"Respond with ONLY the intent name (e.g., 'order_status') and confidence "
                f"score (0.0-1.0) in format: intent|confidence"
            )

            response = client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.1,
            )

            result = response.choices[0].message.content.strip()
            intent_str, confidence_str = result.split("|")
            
            try:
                intent = Intent(intent_str.strip().lower())
                confidence = float(confidence_str.strip())
                return intent, min(confidence, 1.0)
            except (ValueError, IndexError):
                return Intent.UNKNOWN, 0.0

        except Exception as e:
            logger.error(f"OpenAI classification failed: {e}")
            return self._classify_mock(query)

    def classify(self, query: str) -> Dict[str, Any]:
        """
        Full hybrid classification pipeline.
        
        1. Try fast keyword matching
        2. If confidence is low, use LLM classifier
        3. Return final intent with confidence
        
        Returns:
            Dict with 'intent', 'confidence', and 'method' keys.
        """
        # Step 1: Fast keyword matching
        intent, confidence = self.classify_keyword(query)
        
        if intent and confidence >= 0.6:
            logger.info(
                f"Keyword classification: {intent.value} "
                f"(confidence={confidence:.2f})"
            )
            return {
                "intent": intent.value,
                "confidence": round(confidence, 2),
                "method": "keyword",
            }

        # Step 2: LLM-based fallback
        intent, confidence = self.classify_llm(query)
        logger.info(
            f"LLM classification: {intent.value} "
            f"(confidence={confidence:.2f})"
        )
        return {
            "intent": intent.value,
            "confidence": round(confidence, 2),
            "method": "llm",
        }