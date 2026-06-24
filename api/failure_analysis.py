"""
Hop Support - Failure Analysis

Automated analysis of failed AI interactions to categorize root causes.
Updated to use the team database (team-db).
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

FAILURE_CATEGORIES = {
    "knowledge_gap": {
        "label": "Knowledge Gap",
        "description": "The information is missing from the Knowledge Base.",
        "keywords": ["couldn't find", "not found", "don't have", "no information",
                      "unable to find", "cannot answer", "don't know"],
    },
    "retrieval_error": {
        "label": "Retrieval Error",
        "description": "The information exists in the KB but the system failed to retrieve it.",
        "keywords": ["retrieval", "search failed", "sorry", "try rephrasing"],
    },
    "reasoning_error": {
        "label": "Reasoning Error",
        "description": "The system found the info but misinterpreted it.",
        "keywords": ["incorrect", "wrong", "not what I asked", "misunderstood"],
    },
    "tone_safety": {
        "label": "Tone / Safety",
        "description": "The response was accurate but inappropriate or violated guardrails.",
        "keywords": ["rude", "inappropriate", "offensive", "unsafe"],
    },
}


class FailureAnalyzer:
    """
    Analyzes failed interactions and categorizes the root cause.
    Uses keyword matching on the AI response and feedback context.
    """

    def __init__(self, feedback_store: FeedbackStore):
        self.store = feedback_store
        logger.info("FailureAnalyzer initialized")

    def _categorize_by_keywords(self, record: Dict) -> str:
        """
        Categorize a failure based on keyword matching against the AI response.
        """
        response_text = record.get("response", "").lower() if record.get("response") else ""
        query_text = record.get("query", "").lower() if record.get("query") else ""
        combined = f"{response_text} {query_text}"

        # Check knowledge gap first (most common)
        if any(kw in combined for kw in FAILURE_CATEGORIES["knowledge_gap"]["keywords"]):
            return "knowledge_gap"

        # Check for retrieval errors
        if any(kw in combined for kw in FAILURE_CATEGORIES["retrieval_error"]["keywords"]):
            return "retrieval_error"

        # Check for reasoning errors
        if any(kw in combined for kw in FAILURE_CATEGORIES["reasoning_error"]["keywords"]):
            return "reasoning_error"

        # Check for tone/safety issues
        if any(kw in combined for kw in FAILURE_CATEGORIES["tone_safety"]["keywords"]):
            return "tone_safety"

        # Default: knowledge gap (safest assumption)
        return "knowledge_gap"

    def analyze_failure(self, record: Dict) -> Dict:
        """
        Analyze a single failure record and assign a root cause category.
        """
        category = self._categorize_by_keywords(record)
        category_info = FAILURE_CATEGORIES.get(category, {})

        # Update the database
        feedback_id = record.get("id")
        if feedback_id:
            self.store.update_feedback_analysis(
                feedback_id=feedback_id,
                category=category,
                label=category_info.get("label", "Unknown")
            )

        analysis = {
            "feedback_id": feedback_id,
            "interaction_id": record.get("interaction_id"),
            "category": category,
            "category_label": category_info.get("label", "Unknown"),
            "category_description": category_info.get("description", ""),
            "intent": record.get("intent", "unknown"),
            "query": record.get("query", ""),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Failure analyzed: {feedback_id} -> {category}")
        return analysis

    def analyze_all_failures(self) -> List[Dict]:
        """Analyze all un-analyzed failures in the feedback store."""
        failures = self.store.get_all_failures()
        results = []

        for record in failures:
            # Skip already analyzed records (database has category column)
            if record.get("category"):
                continue
            analysis = self.analyze_failure(record)
            results.append(analysis)

        logger.info(f"Analyzed {len(results)} failures")
        return results

    def get_analysis_summary(self) -> Dict[str, Any]:
        """Get a summary of failure categories from the database."""
        # First, ensure all current failures are analyzed
        self.analyze_all_failures()

        # Get metrics from DB
        metrics = self.store.get_analysis_metrics()
        
        category_counts = {m["category"]: m["count"] for m in metrics}
        
        # Total analyzed
        total_analyzed = sum(category_counts.values())

        return {
            "total_analyzed": total_analyzed,
            "by_category": category_counts,
            "category_details": {
                k: {"label": v["label"], "description": v["description"], "count": category_counts.get(k, 0)}
                for k, v in FAILURE_CATEGORIES.items()
            },
        }
