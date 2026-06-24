"""
Hop Support - Skyflow LLM Privacy Vault Integration Design

Design for transitioning from regex-based PIIRedactor (Guardian Layer)
to Skyflow Vault-based zero-trust architecture for Enterprise Healthcare tier.

Status: Design / Prototype
Target: Monday kickoff cycle
"""

import os
import json
import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class RedactionMode(Enum):
    """Operational modes for the Skyflow interceptor."""
    REGEX_ONLY = "regex_only"          # Fallback: use existing PIIRedactor (no Skyflow)
    SKYFLOW_FALLBACK = "skyflow_fallback"  # Try Skyflow, fallback to regex
    SKYFLOW_REQUIRED = "skyflow_required"  # Must use Skyflow, error if unavailable


class DetectedEntity:
    """Represents a detected PII/PHI entity for vault-based tokenization."""
    def __init__(self, text: str, entity_type: str, start: int, end: int):
        self.text = text
        self.entity_type = entity_type  # e.g., SSN, EMAIL, PHONE, DOB, CC, CONDITION
        self.start = start
        self.end = end
        self.token = None  # Assigned by Skyflow

    def __repr__(self):
        return f"DetectedEntity({self.entity_type}: '{self.text}' @ pos {self.start})"


class SkyflowInterceptor:
    """
    Prototype interceptor that wraps Skyflow LLM Privacy Vault API calls.
    
    Three-tier architecture:
    1. Detection: Regex + optional Skyflow ML-based detection
    2. De-identification: Replace PII with vault tokens via Skyflow API
    3. Re-identification: Restore original values in LLM responses
    
    Falls back to regex-only PIIRedactor when Skyflow is unavailable.
    """

    # Entity type mapping from our regex patterns to Skyflow entity types
    ENTITY_TYPE_MAP = {
        'SSN': ['ssn', 'us_ssn'],
        'EMAIL': ['email'],
        'PHONE': ['phone_number', 'us_phone'],
        'DOB': ['date_of_birth'],
        'CC': ['credit_card', 'payment_card'],
        'IP': ['ip_address'],
        'CONDITION': ['medical_condition'],
        'MEDICATION': ['medication'],
    }

    # Reverse mapping for re-identification
    SKYFLOW_TO_INTERNAL = {
        'ssn': 'SSN', 'us_ssn': 'SSN',
        'email': 'EMAIL',
        'phone_number': 'PHONE', 'us_phone': 'PHONE',
        'date_of_birth': 'DOB',
        'credit_card': 'CC', 'payment_card': 'CC',
        'ip_address': 'IP',
        'medical_condition': 'CONDITION',
        'medication': 'MEDICATION',
    }

    def __init__(
        self,
        vault_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mode: RedactionMode = RedactionMode.SKYFLOW_FALLBACK,
    ):
        """
        Initialize the Skyflow interceptor.
        
        Args:
            vault_id: Skyflow Vault ID (from environment or config)
            api_key: Skyflow API key / Bearer token
            base_url: Skyflow API base URL (e.g., 'https://api.skyflow.com')
            mode: Operational mode for fallback behavior
        """
        self.vault_id = vault_id or os.getenv("SKYFLOW_VAULT_ID")
        self.api_key = api_key or os.getenv("SKYFLOW_API_KEY")
        self.base_url = base_url or os.getenv(
            "SKYFLOW_BASE_URL", "https://api.skyflow.com"
        )
        self.mode = mode
        self._available = self._check_available()
        
        if not self._available and mode == RedactionMode.SKYFLOW_REQUIRED:
            raise RuntimeError(
                "Skyflow Vault configured as required but credentials missing. "
                "Set SKYFLOW_VAULT_ID and SKYFLOW_API_KEY environment variables."
            )
        
        logger.info(
            f"SkyflowInterceptor initialized: "
            f"mode={mode.value}, available={self._available}"
        )

    @property
    def is_available(self) -> bool:
        """Check if Skyflow vault credentials are configured."""
        return self._available

    def _check_available(self) -> bool:
        """Check if Skyflow credentials are configured."""
        return bool(self.vault_id and self.api_key)

    # --- Entity Detection ---

    def detect_entities(self, text: str) -> List[DetectedEntity]:
        """
        Detect PII/PHI entities using our regex patterns.
        
        In production, this would also call Skyflow's ML-based detection
        API for higher recall on complex entities.
        
        Returns list of DetectedEntity objects sorted by position.
        """
        entities = []
        
        # Import existing patterns from PIIRedactor
        from api.pii_redactor import PHI_PATTERNS, MEDICAL_PATTERNS, MEDICATION_PATTERNS
        
        entity_labels = {
            '[REDACTED_SSN]': 'SSN',
            '[REDACTED_EMAIL]': 'EMAIL',
            '[REDACTED_PHONE]': 'PHONE',
            '[REDACTED_DOB]': 'DOB',
            '[REDACTED_CC]': 'CC',
            '[REDACTED_IP]': 'IP',
            '[REDACTED_CONDITION]': 'CONDITION',
            '[REDACTED_MEDICATION]': 'MEDICATION',
        }
        
        all_patterns = (
            [(p, entity_labels[r]) for p, r in PHI_PATTERNS] +
            [(p, entity_labels[r]) for p, r in MEDICAL_PATTERNS] +
            [(p, entity_labels[r]) for p, r in MEDICATION_PATTERNS]
        )
        
        for pattern, entity_type in all_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                entities.append(DetectedEntity(
                    text=match.group(),
                    entity_type=entity_type,
                    start=match.start(),
                    end=match.end(),
                ))
        
        # Deduplicate overlapping entities (keep longest match)
        entities.sort(key=lambda e: e.start)
        deduplicated = []
        for entity in entities:
            if deduplicated and entity.start < deduplicated[-1].end:
                # Overlapping - keep the longer one
                if (entity.end - entity.start) > (deduplicated[-1].end - deduplicated[-1].start):
                    deduplicated[-1] = entity
            else:
                deduplicated.append(entity)
        
        return deduplicated

    # --- Skyflow API Integration ---

    def deidentify_via_skyflow(self, text: str, entities: List[DetectedEntity]) -> Tuple[str, Dict[str, str]]:
        """
        Send detected entities to Skyflow for vault-based tokenization.
        
        Calls Skyflow's de-identify API endpoint:
            POST /v1/vaults/{vaultID}/deidentify
            
        Request body:
        {
            "text": "original text...",
            "entities": [
                {"type": "ssn", "value": "123-45-6789"},
                {"type": "email", "value": "user@example.com"}
            ]
        }
        
        Response:
        {
            "deidentified_text": "text with [TOKEN_1] placeholders",
            "tokens": {
                "[TOKEN_1]": {"value": "123-45-6789", "type": "ssn"},
                "[TOKEN_2]": {"value": "user@example.com", "type": "email"}
            }
        }
        
        Returns:
            Tuple of (deidentified_text, token_map)
            token_map: {token_label -> original_value}
        """
        import urllib.request
        import ssl
        
        if not self._available:
            raise RuntimeError("Skyflow not configured")
        
        # Map our entity types to Skyflow entity types
        skyflow_entities = []
        for entity in entities:
            skyflow_types = self.ENTITY_TYPE_MAP.get(entity.entity_type, [])
            for st in skyflow_types:
                skyflow_entities.append({
                    "type": st,
                    "value": entity.text,
                })
        
        # Build request payload
        payload = json.dumps({
            "text": text,
            "entities": skyflow_entities,
        }).encode()
        
        # Call Skyflow API
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            f"{self.base_url}/v1/vaults/{self.vault_id}/deidentify",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=10)
            result = json.loads(resp.read().decode())
            
            deidentified_text = result.get("deidentified_text", text)
            tokens = result.get("tokens", {})
            
            # Build simplified token map
            token_map = {}
            for token_key, token_info in tokens.items():
                if isinstance(token_info, dict):
                    token_map[token_key] = token_info.get("value", "")
                else:
                    token_map[token_key] = str(token_info)
            
            return deidentified_text, token_map
            
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if hasattr(e, 'read') else str(e)
            logger.error(f"Skyflow de-identify API error: {e.code} - {error_body}")
            raise
        except Exception as e:
            logger.error(f"Skyflow de-identify connection error: {e}")
            raise

    def reidentify_via_skyflow(self, deidentified_text: str, token_map: Dict[str, str]) -> str:
        """
        Re-identify de-identified text using the token map from Skyflow.
        
        This can use either:
        a) Local token map (cached from de-identify response) - FASTER
        b) Skyflow re-identify API call - MORE SECURE
        
        Args:
            deidentified_text: Text with token placeholders
            token_map: {token_label -> original_value} from de-identify step
            
        Returns:
            Re-identified text with original values restored
        """
        restored = deidentified_text
        for token, original_value in token_map.items():
            restored = restored.replace(token, original_value)
        return restored

    def deidentify_via_regex(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Fallback de-identification using regex-based redaction.
        
        Returns:
            Tuple of (redacted_text, token_map)
            token_map: {redaction_label -> None} (irreversible without vault)
        """
        from api.pii_redactor import PIIRedactor
        
        redacted = PIIRedactor.redact_input(text)
        
        # Build a simple token map (irreversible - just labels)
        token_map = {}
        for label in ['[REDACTED_SSN]', '[REDACTED_EMAIL]', '[REDACTED_PHONE]',
                       '[REDACTED_DOB]', '[REDACTED_CC]', '[REDACTED_IP]',
                       '[REDACTED_CONDITION]', '[REDACTED_MEDICATION]']:
            if label in redacted:
                token_map[label] = None  # Cannot reverse regex redaction
        
        return redacted, token_map

    # --- Public Interface ---

    def deidentify(self, text: str) -> Tuple[str, Dict[str, str], bool]:
        """
        De-identify text using Skyflow Vault (or fallback to regex).
        
        Args:
            text: Original text containing potential PII/PHI
            
        Returns:
            Tuple of (processed_text, token_map, used_skyflow)
            - processed_text: Text with PII replaced by tokens/redactions
            - token_map: {token -> original_value} for re-identification
            - used_skyflow: True if Skyflow vault was used
        """
        if not text:
            return text, {}, False

        # Step 1: Detect entities using regex
        entities = self.detect_entities(text)
        
        if not entities:
            return text, {}, False

        # Step 2: Try Skyflow de-identification
        if self.mode in (RedactionMode.SKYFLOW_FALLBACK, RedactionMode.SKYFLOW_REQUIRED):
            try:
                deidentified, token_map = self.deidentify_via_skyflow(text, entities)
                logger.info(
                    f"Skyflow de-identified {len(entities)} entities: "
                    f"{[e.entity_type for e in entities]}"
                )
                return deidentified, token_map, True
            except Exception as e:
                logger.warning(f"Skyflow de-identify failed, falling back: {e}")
                if self.mode == RedactionMode.SKYFLOW_REQUIRED:
                    raise  # In required mode, propagate the error

        # Step 3: Fallback to regex
        redacted, token_map = self.deidentify_via_regex(text)
        logger.info(
            f"Regex de-identified {len(entities)} entities (fallback mode)"
        )
        return redacted, token_map, False

    def reidentify(self, processed_text: str, token_map: Dict[str, str], used_skyflow: bool) -> str:
        """
        Re-identify processed text, restoring original values.
        
        Args:
            processed_text: Text with tokens/redactions
            token_map: Token mapping from de-identify step
            used_skyflow: Whether Skyflow was used (vs regex)
            
        Returns:
            Text with original values restored
        """
        if not token_map:
            return processed_text

        if used_skyflow:
            # Skyflow tokens are deterministic and reversible
            return self.reidentify_via_skyflow(processed_text, token_map)
        else:
            # Regex redaction is irreversible - return as-is
            logger.warning("Cannot re-identify regex-redacted text (irreversible)")
            return processed_text


# --- Environment Variables Reference ---

ENV_VARS = {
    "SKYFLOW_VAULT_ID": {
        "description": "Skyflow Vault ID for the target vault",
        "required": True,
        "example": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    },
    "SKYFLOW_API_KEY": {
        "description": "Skyflow API key (Bearer token) for authentication",
        "required": True,
        "sensitive": True,
        "example": "sk_prod_abc123def456...",
    },
    "SKYFLOW_BASE_URL": {
        "description": "Skyflow API base URL",
        "required": False,
        "default": "https://api.skyflow.com",
        "example": "https://api.skyflow.com",
    },
    "SKYFLOW_REDACTION_MODE": {
        "description": "Redaction mode: regex_only, skyflow_fallback, skyflow_required",
        "required": False,
        "default": "skyflow_fallback",
        "example": "skyflow_required",
    },
}


# --- Integration Plan for main.py ---

INTEGRATION_NOTES = """
Integration Steps for main.py:

1. Add environment variables to .env or deployment config:
   - SKYFLOW_VAULT_ID
   - SKYFLOW_API_KEY
   - SKYFLOW_BASE_URL (optional, defaults to https://api.skyflow.com)
   - SKYFLOW_REDACTION_MODE (optional, defaults to skyflow_fallback)

2. Initialize SkyflowInterceptor alongside PIIRedactor:
   
   from api.skyflow_interceptor import SkyflowInterceptor, RedactionMode
   
   skyflow_mode = os.getenv("SKYFLOW_REDACTION_MODE", "skyflow_fallback")
   skyflow = SkyflowInterceptor(
       mode=RedactionMode(skyflow_mode),
   )

3. Update /redact and /demo/verify-redaction endpoints to use Skyflow:
   
   @app.post("/redact")
   async def redact_phi(text: str = Query(...)):
       if skyflow.is_available():
           processed, token_map, used_skyflow = skyflow.deidentify(text)
           # In production: store token_map in session for later re-identification
           return {
               "original": text,
               "redacted": processed,
               "used_skyflow": used_skyflow,
               "entity_count": len(skyflow.detect_entities(text)),
           }
       else:
           # Fallback to existing PIIRedactor
           ...

4. Update /demo/query/{brand} for reversible tokenization:
   
   @app.post("/demo/query/{brand}")
   async def demo_query(brand: str, request: ...):
       # De-identify input before RAG
       safe_query, token_map, used_skyflow = skyflow.deidentify(request.query)
       
       # Run RAG on de-identified query
       result = rag_engine.query(safe_query)
       
       # Re-identify response
       response_text = skyflow.reidentify(
           result['answer'], token_map, used_skyflow
       )
       
       return {"answer": response_text, ...}

5. For HIPAA audit trails:
   - Log all de-identify/re-identify operations with timestamps
   - Store token maps in encrypted session state (not plaintext logs)  
   - Set zero-retention TTL on Skyflow tokens after session expiry

"""

# --- Migration Assessment ---

MIGRATION_ASSESSMENT = """
Migration Assessment: PIIRedactor -> SkyflowInterceptor

Current State (PIIRedactor):
- ✅ Simple, zero-dependency regex-based redaction
- ✅ Works offline, no external API calls
- ❌ Irreversible (cannot re-identify for customer support context)
- ❌ No audit trail for HIPAA compliance
- ❌ Pattern-based only (misses novel PII formats)
- ❌ No vault-based tokenization

Target State (SkyflowInterceptor):
- ✅ Reversible tokenization for re-identification
- ✅ Vault-based storage for HIPAA compliance
- ✅ ML-based entity detection (in addition to regex)
- ✅ Audit trail for all redaction operations
- ✅ Zero-trust architecture
- ❌ Requires internet access to Skyflow API
- ❌ Higher latency (~100-200ms per API call)
- ❌ Additional cost per API call

Hybrid Approach (Recommended):
- Use Skyflow for initial de-identification (generate tokens)
- Cache token mappings in memory/Redis for fast re-identification
- Fall back to regex when Skyflow is unavailable
- Use regex-only mode for non-sensitive brands (reduced cost)
- Use Skyflow-required mode for Healthcare tier

Cost Estimate:
- Skyflow API pricing: ~$0.001 per de-identify call
- Average: 300 entities per 1000 messages = ~$0.30 per 1000 messages
- For Hims & Hers 100-user pilot: ~50 messages/user/day = 5000 msg/day
- Estimated cost: ~$1.50/day or ~$45/month
"""


# --- Quick Test Function ---

def test_skyflow_interceptor():
    """Test the interceptor in regex-only mode (no Skyflow credentials needed)."""
    interceptor = SkyflowInterceptor(
        vault_id=None,  # No credentials - will use regex fallback
        api_key=None,
        mode=RedactionMode.REGEX_ONLY,
    )
    
    test_cases = [
        "My SSN is 123-45-6789",
        "Email me at patient@example.com",
        "Call 555-123-4567 for refills",
        "My DOB is 01/15/1990",
        "My credit card is 4111-1111-1111-1111",
        "I have depression and take finasteride",
        "Combined: SSN 123-45-6789, email test@example.com, DOB 01/15/1990",
    ]
    
    print("=== SkyflowInterceptor Test (Regex Mode) ===\n")
    for test in test_cases:
        processed, token_map, used_skyflow = interceptor.deidentify(test)
        entities = interceptor.detect_entities(test)
        entity_types = [e.entity_type for e in entities]
        print(f"Input:    {test}")
        print(f"Entities: {entity_types}")
        print(f"Output:   {processed}")
        print(f"Skyflow:  {used_skyflow}")
        print()


if __name__ == "__main__":
    test_skyflow_interceptor()