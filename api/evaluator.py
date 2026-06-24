"""
Hop Support - Golden Dataset Evaluator

Tests the system against a "golden dataset" of question-answer pairs
to measure accuracy and catch regressions after changes.
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "shared",
    "golden_dataset.json",
)

EVAL_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "evaluation",
)


class GoldenDatasetEvaluator:
    """
    Evaluates the Hop Support system against a golden dataset of
    question-answer pairs to track accuracy over time.
    """

    def __init__(self, dataset_path: str = GOLDEN_DATASET_PATH):
        self.dataset_path = dataset_path
        os.makedirs(EVAL_RESULTS_DIR, exist_ok=True)
        self.dataset = self._load_dataset()
        logger.info(
            f"Evaluator initialized with {len(self.dataset)} golden question-answer pairs"
        )

    def _load_dataset(self) -> List[Dict]:
        """Load the golden dataset from JSON."""
        if not os.path.exists(self.dataset_path):
            logger.warning(f"Golden dataset not found at {self.dataset_path}")
            return []
        try:
            with open(self.dataset_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error(f"Failed to load golden dataset: {e}")
            return []

    def evaluate(
        self,
        rag_engine,
        intent_classifier=None,
    ) -> Dict[str, Any]:
        """
        Run the golden dataset through the current system and measure accuracy.
        
        Args:
            rag_engine: The RAG engine to query
            intent_classifier: Optional intent classifier to evaluate
            
        Returns:
            Dict with scores and per-question results.
        """
        if not self.dataset:
            return {"error": "Golden dataset is empty or not found", "score": 0}

        results = []
        correct_intents = 0
        total = len(self.dataset)

        for item in self.dataset:
            question = item.get("question", "")
            expected_intent = item.get("intent", "")

            result = {
                "question": question,
                "expected_intent": expected_intent,
            }

            # Evaluate intent detection
            if intent_classifier:
                intent_result = intent_classifier.classify(question)
                detected_intent = intent_result.get("intent", "")
                result["detected_intent"] = detected_intent
                result["intent_confidence"] = intent_result.get("confidence", 0)
                result["intent_method"] = intent_result.get("method", "")

                # Check if intent matches (case-insensitive, partial match)
                expected = expected_intent.lower().replace("/", "_").replace(" ", "_")
                detected = detected_intent.lower()
                result["intent_correct"] = self._intents_match(expected, detected)
                if result["intent_correct"]:
                    correct_intents += 1

            # Evaluate response via RAG
            if rag_engine:
                response = rag_engine.query(question, top_k=3)
                result["response"] = response.get("answer", "")
                result["sources"] = response.get("sources", [])

            results.append(result)

        intent_accuracy = round(correct_intents / total, 3) if total > 0 else 0

        eval_result = {
            "evaluated_at": datetime.utcnow().isoformat(),
            "total_questions": total,
            "correct_intents": correct_intents,
            "intent_accuracy": intent_accuracy,
            "results": results,
        }

        # Save evaluation results
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        result_path = os.path.join(EVAL_RESULTS_DIR, f"eval_{timestamp}.json")
        with open(result_path, "w") as f:
            json.dump(eval_result, f, indent=2, default=str)

        logger.info(
            f"Evaluation complete: {correct_intents}/{total} "
            f"intents correct ({intent_accuracy:.1%})"
        )

        return eval_result

    def _intents_match(self, expected: str, detected: str) -> bool:
        """
        Check if two intent strings match, handling different formats.
        
        Examples:
            "product_inquiry" == "product inquiry" -> True
            "return/refund request" == "return_refund" -> True
            "order_status" == "order status" -> True
        """
        # Normalize: lowercase, strip, replace separators
        def normalize(s):
            return s.lower().strip().replace("/", "_").replace("-", "_").replace(" ", "_")
        
        return normalize(expected) == normalize(detected)

    def get_evaluation_history(self) -> List[Dict]:
        """Get all past evaluation results."""
        if not os.path.exists(EVAL_RESULTS_DIR):
            return []

        history = []
        for filename in sorted(os.listdir(EVAL_RESULTS_DIR)):
            if filename.startswith("eval_") and filename.endswith(".json"):
                filepath = os.path.join(EVAL_RESULTS_DIR, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                        history.append({
                            "timestamp": data.get("evaluated_at", filename),
                            "intent_accuracy": data.get("intent_accuracy", 0),
                            "total_questions": data.get("total_questions", 0),
                            "correct_intents": data.get("correct_intents", 0),
                        })
                except (json.JSONDecodeError, FileNotFoundError):
                    pass

        return history