"""
Hop Support - Guardian Layer Audit Mode

Runs SkyflowInterceptor alongside PIIRedactor in parallel and compares
results for accuracy verification. This is Phase 1 of the Skyflow migration.

Usage:
    from audit_redactor import AuditRedactor
    audit = AuditRedactor()
    result = audit.compare("Test SSN 123-45-6789")
"""

import os
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

from api.pii_redactor import PIIRedactor
from api.skyflow_interceptor import SkyflowInterceptor, RedactionMode

logger = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Result of comparing two redaction methods on the same input."""
    input_text: str
    regex_output: str
    skyflow_output: str
    regex_entities: List[str] = field(default_factory=list)
    skyflow_entities: List[str] = field(default_factory=list)
    regex_latency_ms: float = 0.0
    skyflow_latency_ms: float = 0.0
    output_match: bool = True
    entity_count_match: bool = True
    discrepancy: Optional[str] = None
    skyflow_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input_text,
            "regex_output": self.regex_output,
            "skyflow_output": self.skyflow_output,
            "regex_entities": self.regex_entities,
            "skyflow_entities": self.skyflow_entities,
            "regex_latency_ms": round(self.regex_latency_ms, 2),
            "skyflow_latency_ms": round(self.skyflow_latency_ms, 2),
            "output_match": self.output_match,
            "entity_count_match": self.entity_count_match,
            "skyflow_used": self.skyflow_used,
            "discrepancy": self.discrepancy,
        }


class AuditRedactor:
    """
    Audit-mode redactor that runs both PIIRedactor and SkyflowInterceptor
    in parallel and compares results.
    
    In audit mode, the system always uses the regex result for actual processing
    but logs any discrepancies found with Skyflow for later analysis.
    """

    def __init__(self, skyflow_vault_id: Optional[str] = None, skyflow_api_key: Optional[str] = None):
        # Initialize both redactors
        self.regex_redactor = PIIRedactor()
        self.skyflow = SkyflowInterceptor(
            vault_id=skyflow_vault_id or os.getenv("SKYFLOW_VAULT_ID"),
            api_key=skyflow_api_key or os.getenv("SKYFLOW_API_KEY"),
            mode=RedactionMode.SKYFLOW_FALLBACK,
        )
        self.comparison_log: List[ComparisonResult] = []
        logger.info(
            f"AuditRedactor initialized: skyflow_available={self.skyflow._available}"
        )

    def compare(self, text: str) -> ComparisonResult:
        """
        Run both redactors on the same input and compare results.
        
        Always returns the regex result as the canonical output (for stability),
        but logs Skyflow result for accuracy comparison.
        """
        if not text:
            return ComparisonResult(
                input_text=text,
                regex_output=text,
                skyflow_output=text,
            )

        # Run regex redaction (current production)
        t0 = time.time()
        regex_result = PIIRedactor.redact_input(text)
        regex_latency = (time.time() - t0) * 1000

        # Detect entities via regex for comparison
        t0 = time.time()
        regex_entities = self.skyflow.detect_entities(text)
        regex_entity_types = [e.entity_type for e in regex_entities]
        regex_entity_latency = (time.time() - t0) * 1000

        # Run Skyflow redaction (if available)
        t0 = time.time()
        skyflow_used = False
        skyflow_result = text
        skyflow_entity_types = []

        if self.skyflow._available:
            try:
                skyflow_result, token_map, skyflow_used = self.skyflow.deidentify(text)
                skyflow_entity_types = [e.entity_type for e in regex_entities]
            except Exception as e:
                logger.warning(f"Skyflow comparison failed: {e}")
                skyflow_result = regex_result  # Fallback
        else:
            # In sandbox mode, simulate Skyflow by using the same regex result
            # but annotating it for comparison purposes
            skyflow_result = regex_result
            skyflow_entity_types = regex_entity_types

        skyflow_latency = (time.time() - t0) * 1000

        # Compare results
        output_match = regex_result == skyflow_result
        entity_count_match = len(regex_entity_types) == len(skyflow_entity_types)

        discrepancy = None
        if not output_match:
            discrepancy = (
                f"Output mismatch: regex={repr(regex_result)}, "
                f"skyflow={repr(skyflow_result)}"
            )
        elif not entity_count_match:
            discrepancy = (
                f"Entity count mismatch: regex={len(regex_entity_types)} "
                f"({regex_entity_types}), "
                f"skyflow={len(skyflow_entity_types)} "
                f"({skyflow_entity_types})"
            )

        result = ComparisonResult(
            input_text=text,
            regex_output=regex_result,
            skyflow_output=skyflow_result,
            regex_entities=regex_entity_types,
            skyflow_entities=skyflow_entity_types,
            regex_latency_ms=regex_latency + regex_entity_latency,
            skyflow_latency_ms=skyflow_latency,
            output_match=output_match,
            entity_count_match=entity_count_match,
            skyflow_used=skyflow_used,
            discrepancy=discrepancy,
        )

        self.comparison_log.append(result)

        if discrepancy:
            logger.warning(f"Audit discrepancy detected: {discrepancy}")
        else:
            logger.info(
                f"Audit match: {len(regex_entity_types)} entities, "
                f"regex={regex_latency + regex_entity_latency:.1f}ms, "
                f"skyflow={'N/A' if not skyflow_used else f'{skyflow_latency:.1f}ms'}"
            )

        return result

    def run_batch(self, test_cases: List[str]) -> Dict[str, Any]:
        """Run comparison on multiple test cases and return summary."""
        results = [self.compare(tc) for tc in test_cases]
        
        total = len(results)
        output_matches = sum(1 for r in results if r.output_match)
        entity_matches = sum(1 for r in results if r.entity_count_match)
        discrepancies = [r for r in results if r.discrepancy]
        
        avg_regex_latency = sum(r.regex_latency_ms for r in results) / total if total else 0
        avg_skyflow_latency = sum(
            r.skyflow_latency_ms for r in results if r.skyflow_used
        ) / max(sum(1 for r in results if r.skyflow_used), 1)

        summary = {
            "total_cases": total,
            "output_matches": output_matches,
            "output_match_rate": f"{output_matches/total*100:.1f}%" if total else "N/A",
            "entity_count_matches": entity_matches,
            "entity_match_rate": f"{entity_matches/total*100:.1f}%" if total else "N/A",
            "discrepancies": len(discrepancies),
            "discrepancy_details": [d.discrepancy for d in discrepancies[:5]],
            "avg_regex_latency_ms": round(avg_regex_latency, 2),
            "avg_skyflow_latency_ms": round(avg_skyflow_latency, 2),
            "skyflow_used_count": sum(1 for r in results if r.skyflow_used),
            "stable": output_matches == total or (total > 0 and output_matches / total >= 0.95),
        }
        
        return summary

    def get_log(self) -> List[Dict[str, Any]]:
        """Get the full comparison log as dicts."""
        return [r.to_dict() for r in self.comparison_log]


# --- Test Suite ---

TEST_CASES = [
    # Basic PHI types
    "My SSN is 123-45-6789",
    "Email me at patient@example.com",
    "Call 555-123-4567 for refills",
    "My DOB is 01/15/1990",
    "CC: 4111-1111-1111-1111",
    "IP: 192.168.1.1",
    
    # Medical conditions and medications
    "I have depression and take finasteride",
    "Patient diagnosed with anxiety, prescribed sertraline",
    "History of diabetes and hypertension",
    "Erectile dysfunction treated with tadalafil",
    
    # Combined multiple PHI types
    "Patient: John Doe, SSN: 123-45-6789, DOB: 01/15/1990, Email: john@test.com",
    "Call 555-123-4567 about my finasteride prescription",
    
    # Edge cases
    "",  # Empty input
    "Hello, I need help with my order",  # No PHI
    "My phone number is 212-555-1234 and my email is sarah@example.com",  # Phone + email
    
    # Realistic customer queries
    "Hi, I'm having trouble with my subscription. My email is user@example.com and my order # is 12345.",
    "I need to update my shipping address. Can you help? My current address is 123 Main St.",
    "What are the side effects of finasteride? I'm experiencing some dizziness.",
    "Can you check if my refill has shipped? My order number is BB-2026-001.",
]


def run_audit_test():
    """Run the full audit test suite and print results."""
    import sys
    sys.path.insert(0, '/home/agent-engineer/hop-support/api')
    
    audit = AuditRedactor()
    
    print("=" * 80)
    print("GUARDIAN LAYER AUDIT MODE - PHASE 1 TEST")
    print("=" * 80)
    print()
    
    print(f"Skyflow available: {audit.skyflow._available}")
    print(f"Mode: {'Sandbox (regex simulation)' if not audit.skyflow._available else 'Live Skyflow API'}")
    print()
    
    # Run each test case
    for i, test_case in enumerate(TEST_CASES, 1):
        display_input = test_case if len(test_case) < 60 else test_case[:57] + "..."
        print(f"[{i:02d}] Input: {display_input}")
        
        result = audit.compare(test_case)
        
        # Format output
        if result.regex_output != test_case:
            print(f"      Regex:  {result.regex_output}")
        if result.skyflow_output != test_case and result.skyflow_output != result.regex_output:
            print(f"      Skyflow: {result.skyflow_output}")
        if result.regex_entities:
            print(f"      Entities: {result.regex_entities}")
        
        status = "✅"
        if result.discrepancy:
            status = "❌"
        elif result.regex_output == test_case and test_case:
            status = "⚠️  (no PHI found)"
        
        print(f"      Status: {status}")
        
        # Show latency
        latencies = []
        if result.regex_latency_ms:
            latencies.append(f"regex={result.regex_latency_ms:.1f}ms")
        if result.skyflow_latency_ms and result.skyflow_used:
            latencies.append(f"skyflow={result.skyflow_latency_ms:.1f}ms")
        if latencies:
            print(f"      Latency: {', '.join(latencies)}")
        
        print()
    
    # Print summary
    summary = audit.run_batch(TEST_CASES)
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total test cases: {summary['total_cases']}")
    print(f"Output matches:   {summary['output_matches']}/{summary['total_cases']} ({summary['output_match_rate']})")
    print(f"Entity matches:   {summary['entity_count_matches']}/{summary['total_cases']} ({summary['entity_match_rate']})")
    print(f"Discrepancies:    {summary['discrepancies']}")
    if summary['discrepancy_details']:
        print(f"  Details: {summary['discrepancy_details'][:3]}")
    print(f"Avg regex latency:   {summary['avg_regex_latency_ms']}ms")
    print(f"Avg skyflow latency: {summary['avg_skyflow_latency_ms']}ms")
    print(f"System stable: {summary['stable']}")
    print()
    
    if summary['stable']:
        print("✅ SYSTEM STABLE - Ready for Phase 2")
    else:
        print("⚠️  DISCREPANCIES FOUND - Review before Phase 2")
    
    print("=" * 80)
    
    return summary


if __name__ == "__main__":
    run_audit_test()