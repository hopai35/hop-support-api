"""
Hop Support - Multi-Brand Demo Manager

Allows switching between 5 brand personas for product demos:
Framework, Ledger, Sonos, Warby Parker, Allbirds.

Each brand has its own ChromaDB collection, knowledge base, and voice persona.
"""

import json
import os
import logging
from typing import Optional, Dict, Any

from rag_engine import RAGEngine
from intent_classifier import IntentClassifier
from tools import ToolExecutor
from vapi_handler import VapiHandler
from pii_redactor import PIIRedactor
from skyflow_interceptor import SkyflowInterceptor, RedactionMode

logger = logging.getLogger(__name__)

DEMO_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demo_data",
    "demo_config.json",
)

DEFAULT_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "chroma",
)


class DemoManager:
    """
    Manages multi-brand demo environments.
    Each brand has an isolated ChromaDB collection and KB directory.
    """

    def __init__(self, config_path: str = DEMO_CONFIG_PATH):
        self.config_path = config_path
        self.config = self._load_config()
        self._engines: Dict[str, RAGEngine] = {}
        self._classifiers: Dict[str, IntentClassifier] = {}
        self._handlers: Dict[str, VapiHandler] = {}
        logger.info(f"DemoManager initialized with {len(self.brands)} brands")

    @property
    def brands(self) -> list:
        """Get list of brand keys."""
        return list(self.config.get("brands", {}).keys())

    @property
    def default_brand(self) -> str:
        """Get the default brand."""
        return self.config.get("default_brand", "framework")

    def _load_config(self) -> Dict[str, Any]:
        """Load the demo configuration JSON."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Demo config not found at {self.config_path}")
            return {"default_brand": "framework", "brands": {}}
        with open(self.config_path, "r") as f:
            return json.load(f)

    def get_brand_info(self, brand: str) -> Dict[str, Any]:
        """Get configuration info for a specific brand."""
        return self.config.get("brands", {}).get(brand, {})

    def get_kb_dir(self, brand: str) -> str:
        """Get the KB directory for a brand."""
        info = self.get_brand_info(brand)
        rel_path = info.get("kb_directory", f"kb/{brand}")
        return os.path.join(
            os.path.dirname(self.config_path), rel_path
        )

    def get_rag_engine(self, brand: str) -> RAGEngine:
        """Get (or create) the RAG engine for a brand's collection."""
        brand_config = self.get_brand_info(brand)
        collection_name = brand_config.get("collection_name", f"demo_{brand}")

        if brand not in self._engines:
            engine = RAGEngine(
                persist_dir=DEFAULT_PERSIST_DIR,
                collection_name=collection_name,
                llm_provider="mock",
            )
            # Auto-ingest brand KB if not empty
            kb_dir = self.get_kb_dir(brand)
            if os.path.isdir(kb_dir) and os.listdir(kb_dir):
                engine.ingest_documents(kb_dir)
                logger.info(f"Ingested KB for {brand}: {kb_dir}")
            self._engines[brand] = engine

        return self._engines[brand]

    def get_vapi_handler(self, brand: str) -> VapiHandler:
        """Get (or create) the Vapi handler for a brand's voice persona."""
        if brand not in self._handlers:
            engine = self.get_rag_engine(brand)
            classifier = IntentClassifier(llm_provider="mock")
            executor = ToolExecutor(rag_engine=engine)

            handler = VapiHandler(
                rag_engine=engine,
                intent_classifier=classifier,
                tool_executor=executor,
            )
            self._handlers[brand] = handler

        return self._handlers[brand]

    def process_voice_query(self, text: str, brand: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a voice query for a specific brand persona.
        
        Args:
            text: The user's spoken query text
            brand: Brand key (framework, ledger, sonos, warby_parker, allbirds).
                   Falls back to env var BRAND, then default.
                   
        Returns:
            Response dict with intent, response text, and brand info
        """
        brand = brand or os.getenv("BRAND", self.default_brand)

        if brand not in self.brands:
            return {
                "error": f"Unknown brand '{brand}'. Choose from: {', '.join(self.brands)}",
                "intent": "unknown",
                "response": f"I'm sorry, I don't recognize that brand. Available demos: {', '.join(self.brands)}.",
            }

        brand_info = self.get_brand_info(brand)
        handler = self.get_vapi_handler(brand)
        result = handler.process_voice_query(text)

        # Add brand context
        result["brand"] = brand
        result["brand_name"] = brand_info.get("display_name", brand)
        result["persona"] = brand_info.get("voice_persona", "")
        result["pitch"] = brand_info.get("pitch", "")

        logger.info(f"Voice query for {brand}: intent={result.get('intent')}")
        return result

    # --- Skyflow Tier-Based Redaction ---

    def is_healthcare_brand(self, brand: str) -> bool:
        """Check if a brand requires Healthcare-tier Skyflow redaction."""
        info = self.get_brand_info(brand)
        return info.get("healthcare", False)

    def get_redaction_mode(self, brand: str) -> RedactionMode:
        """Get the redaction mode for a brand based on config."""
        info = self.get_brand_info(brand)
        mode_str = info.get("redaction_mode", "regex_only")
        return RedactionMode(mode_str)

    def redact_query(self, text: str, brand: str) -> tuple:
        """
        Redact PII from a query based on the brand's tier.
        
        For Healthcare brands: Use Skyflow (or fallback to regex if unavailable)
        For others: Use regex-only
        
        Returns:
            Tuple of (redacted_text, token_map, used_skyflow, session_id)
        """
        if not text:
            return text, {}, False, None

        mode = self.get_redaction_mode(brand)
        
        if mode == RedactionMode.REGEX_ONLY:
            # Quick regex-only path for non-healthcare brands
            redacted = PIIRedactor.redact_input(text)
            return redacted, {}, False, None

        # Healthcare tier: try Skyflow, fall back to regex if unavailable
        # Use skyflow_fallback to gracefully degrade when credentials are missing
        actual_mode = RedactionMode.SKYFLOW_FALLBACK
        skyflow = SkyflowInterceptor(mode=actual_mode)
        
        if not skyflow.is_available:
            logger.warning(
                f"Skyflow unavailable for healthcare brand '{brand}'. "
                f"Falling back to regex redaction."
            )
            redacted = PIIRedactor.redact_input(text)
            return redacted, {}, False, None
        
        redacted, token_map, used_skyflow = skyflow.deidentify(text)
        
        # Store token map for later re-identification
        session_id = f"session_{brand}_{abs(hash(text)) % 100000}"
        if token_map:
            from api.state_store import state_store
            state_store.store_token_map(session_id, token_map)
        
        return redacted, token_map, used_skyflow, session_id

    def reidentify_response(self, response_text: str, session_id: str) -> str:
        """Re-identify a response using stored token map (for healthcare brands)."""
        if not session_id:
            return response_text
        
        from api.state_store import state_store
        token_map = state_store.get_token_map(session_id)
        if not token_map:
            return response_text
        
        # Re-identify using the token map
        restored = response_text
        for token, original_value in token_map.items():
            if original_value is not None:
                restored = restored.replace(token, str(original_value))
        
        return restored

    def process_query_with_redaction(self, query: str, brand: str) -> Dict[str, Any]:
        """
        Process a query with tier-appropriate redaction.
        
        1. De-identify input (Skyflow for Healthcare, regex for others)
        2. Run RAG query on safe text
        3. Re-identify response (only for Healthcare brands)
        """
        # Step 1: Redact PII from input
        redacted_query, token_map, used_skyflow, session_id = self.redact_query(query, brand)
        
        # Step 2: Run RAG on the safe(redacted) query
        engine = self.get_rag_engine(brand)
        
        if engine.collection.count() == 0:
            result = {
                "brand": brand,
                "query": query,
                "answer": f"The {brand} knowledge base is empty.",
                "sources": [],
            }
        else:
            rag_result = engine.query(redacted_query, top_k=3)
            result = {
                "brand": brand,
                "query": query,
                "answer": rag_result["answer"],
                "sources": rag_result["sources"],
            }
        
        # Step 3: Re-identify response for healthcare brands
        if used_skyflow and session_id:
            result["answer"] = self.reidentify_response(result["answer"], session_id)
        
        # Add redaction metadata
        result["phi_redacted"] = used_skyflow or (redacted_query != query)
        result["token_count"] = len(token_map)
        
        return result

    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics for all brands."""
        metrics = {}
        for brand in self.brands:
            engine = self.get_rag_engine(brand)
            metrics[brand] = {
                "collection_size": engine.collection.count(),
                "kb_dir": self.get_kb_dir(brand),
            }
        return metrics