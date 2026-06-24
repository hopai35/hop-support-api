"""
Hop Support - PII/PHI Redaction Layer ("Guardian Layer")

Three-layer PII redaction pipeline for HIPAA compliance:
Layer 1: Input Redaction (pre-processing)
Layer 2: Processing isolation (in-memory only)
Layer 3: Output Redaction (post-processing)
"""

import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# PHI/PII detection patterns: (regex, replacement_label)
PHI_PATTERNS = [
    (r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b', '[REDACTED_SSN]'),
    (r'\b[\w.+-]+@[\w-]+\.[\w.]+\b', '[REDACTED_EMAIL]'),
    (r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.]?\d{4}\b', '[REDACTED_PHONE]'),
    (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', '[REDACTED_DOB]'),
    (r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[REDACTED_CC]'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]'),
]

MEDICAL_PATTERNS = [
    (r'\b(depression|anxiety|bipolar|PTSD|OCD|ADHD)\b', '[REDACTED_CONDITION]'),
    (r'\b(diabetes|hypertension|asthma|COPD|arthritis|cancer|epilepsy)\b', '[REDACTED_CONDITION]'),
    (r'\b(erectile\s*dysfunction|low\s*testosterone|hair\s*loss|alopecia)\b', '[REDACTED_CONDITION]'),
]

MEDICATION_PATTERNS = [
    (r'\b(sildenafil|tadalafil|finasteride|minoxidil|dutasteride)\b', '[REDACTED_MEDICATION]'),
    (r'\b(sertraline|fluoxetine|escitalopram|bupropion)\b', '[REDACTED_MEDICATION]'),
]


class PIIRedactor:
    """Three-layer PHI redaction pipeline."""

    @staticmethod
    def redact_input(text: str) -> str:
        """Layer 1: Redact PHI from incoming text before logging/AI processing."""
        if not text:
            return text
        for pattern, replacement in PHI_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        for pattern, replacement in MEDICAL_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        for pattern, replacement in MEDICATION_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def redact_output(text: str) -> str:
        """Layer 3: Redact PHI from AI responses before logging."""
        if not text:
            return text
        for pattern, replacement in PHI_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def verify(original: str, redacted: str) -> Dict[str, Any]:
        """Verify redaction by counting what was found and replaced."""
        total_found = 0
        categories = []
        for pattern, label in PHI_PATTERNS + MEDICAL_PATTERNS + MEDICATION_PATTERNS:
            matches = re.findall(pattern, original, flags=re.IGNORECASE)
            if matches:
                total_found += len(matches)
                categories.append(label)
        tags_applied = len(re.findall(r'\[REDACTED_\w+\]', redacted))
        return {
            "phi_found": total_found > 0,
            "phi_count": total_found,
            "categories": list(set(categories)),
            "tags_applied": tags_applied,
            "redaction_ok": tags_applied >= total_found if total_found > 0 else True,
        }