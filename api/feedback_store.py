"""
Hop Support - Feedback Store (Team Database version)

Stores and retrieves user feedback for AI interactions using the team database.
Records response-level feedback (thumbs up/down), session surveys (1-5 stars),
and human handover context for failure analysis.
"""

import json
import subprocess
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

FEEDBACK_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "feedback",
)

class FeedbackStore:
    """
    Stores and retrieves user feedback for AI interactions using 'team-db'.
    """

    def __init__(self, feedback_dir: str = FEEDBACK_DIR):
        self.feedback_dir = feedback_dir
        os.makedirs(feedback_dir, exist_ok=True)
        logger.info("FeedbackStore initialized with team-db")

    def _run_sql(self, sql: str) -> List[Dict]:
        """Execute a SQL statement via team-db CLI."""
        try:
            result = subprocess.run(
                ["team-db", sql],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"team-db failed: {e.stderr}")
            raise Exception(f"Database error: {e.stderr}")
        except json.JSONDecodeError:
            return []

    def _esc(self, val: Any) -> str:
        """Escape a value for inclusion in a SQL string."""
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, (int, float)):
            return str(val)
        # Escape single quotes by doubling them
        return "'" + str(val).replace("'", "''") + "'"

    def record_response_feedback(
        self,
        interaction_id: str,
        rating: int,  # 1 for thumbs up, -1 for thumbs down
        query: str,
        response: str,
        intent: str,
        confidence: float,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Record response-level feedback (Thumbs Up/Down)."""
        is_failure = rating < 0
        meta_json = json.dumps(metadata or {})
        
        sql = (
            f"INSERT INTO feedback (interaction_id, type, rating, query, response, intent, confidence, is_failure, metadata) "
            f"VALUES ({self._esc(interaction_id)}, 'response', {rating}, {self._esc(query)}, "
            f"{self._esc(response)}, {self._esc(intent)}, {confidence}, {self._esc(is_failure)}, {self._esc(meta_json)})"
        )
        self._run_sql(sql)
        
        logger.info(f"Response feedback recorded for {interaction_id}")
        return {"status": "recorded", "interaction_id": interaction_id}

    def record_session_survey(
        self,
        interaction_id: str,
        rating: int,  # 1-5 stars
        comment: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Record session-level survey (1-5 star rating)."""
        is_failure = rating <= 2
        meta_json = json.dumps(metadata or {})
        
        sql = (
            f"INSERT INTO feedback (interaction_id, type, rating, comment, is_failure, metadata) "
            f"VALUES ({self._esc(interaction_id)}, 'session_survey', {rating}, {self._esc(comment)}, "
            f"{self._esc(is_failure)}, {self._esc(meta_json)})"
        )
        self._run_sql(sql)
        
        logger.info(f"Session survey recorded for {interaction_id}")
        return {"status": "recorded", "interaction_id": interaction_id}

    def record_escalation_reason(
        self,
        interaction_id: str,
        reason: str,
        query: str,
        intent: str,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Record why a user requested human escalation."""
        meta_json = json.dumps(metadata or {})
        
        sql = (
            f"INSERT INTO feedback (interaction_id, type, reason, query, intent, is_failure, metadata) "
            f"VALUES ({self._esc(interaction_id)}, 'escalation', {self._esc(reason)}, "
            f"{self._esc(query)}, {self._esc(intent)}, 1, {self._esc(meta_json)})"
        )
        self._run_sql(sql)
        
        logger.info(f"Escalation reason recorded for {interaction_id}")
        return {"status": "recorded", "interaction_id": interaction_id}

    def get_feedback_by_date(self, date_str: str, include_failures_only: bool = False) -> List[Dict]:
        """Get feedback for a specific date (YYYY-MM-DD)."""
        where = f"WHERE date(created_at) = {self._esc(date_str)}"
        if include_failures_only:
            where += " AND is_failure = 1"
        
        sql = f"SELECT * FROM feedback {where} ORDER BY created_at DESC"
        return self._run_sql(sql)

    def get_all_failures(self) -> List[Dict]:
        """Get all failure records."""
        sql = "SELECT * FROM feedback WHERE is_failure = 1 ORDER BY created_at DESC"
        return self._run_sql(sql)

    def update_feedback_analysis(self, feedback_id: int, category: str, label: str) -> None:
        """Update a feedback record with analysis results."""
        now = datetime.utcnow().isoformat()
        sql = (
            f"UPDATE feedback SET category = {self._esc(category)}, "
            f"category_label = {self._esc(label)}, "
            f"analyzed_at = {self._esc(now)} "
            f"WHERE id = {feedback_id}"
        )
        self._run_sql(sql)

    def get_analysis_metrics(self) -> List[Dict]:
        """Get summary metrics for analyzed failures."""
        sql = "SELECT category, category_label, COUNT(*) as count FROM feedback WHERE category IS NOT NULL GROUP BY category"
        return self._run_sql(sql)

    def get_metrics(self) -> Dict[str, Any]:
        """Calculate aggregate metrics from all feedback data."""
        # Total interactions
        res = self._run_sql("SELECT COUNT(*) as count FROM feedback")
        total = res[0]["count"] if res else 0
        
        if total == 0:
            return self._empty_metrics()

        # Response metrics
        res = self._run_sql("SELECT COUNT(*) as count, SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) as pos, SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END) as neg FROM feedback WHERE type = 'response'")
        resp_stats = res[0] if res else {"count": 0, "pos": 0, "neg": 0}
        total_resp = resp_stats["count"]
        pos_resp = resp_stats["pos"] or 0
        neg_resp = resp_stats["neg"] or 0

        # Star rating
        res = self._run_sql("SELECT AVG(rating) as avg_stars, COUNT(*) as count FROM feedback WHERE type = 'session_survey'")
        survey_stats = res[0] if res else {"avg_stars": 0, "count": 0}
        avg_stars = survey_stats["avg_stars"] or 0
        total_surveys = survey_stats["count"]

        # Escalations
        res = self._run_sql("SELECT COUNT(*) as count FROM feedback WHERE type = 'escalation'")
        escalations = res[0]["count"] if res else 0

        # Total failures
        res = self._run_sql("SELECT COUNT(*) as count FROM feedback WHERE is_failure = 1")
        total_failures = res[0]["count"] if res else 0

        return {
            "total_interactions": total,
            "total_responses": total_resp,
            "positive_responses": pos_resp,
            "negative_responses": neg_resp,
            "thumbs_up_rate": round(pos_resp / total_resp, 3) if total_resp else 0,
            "session_surveys": total_surveys,
            "avg_star_rating": round(avg_stars, 2),
            "escalations": escalations,
            "total_failures": total_failures,
            "failure_rate": round(total_failures / total, 3) if total else 0,
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "total_interactions": 0,
            "total_responses": 0,
            "positive_responses": 0,
            "negative_responses": 0,
            "thumbs_up_rate": 0,
            "session_surveys": 0,
            "avg_star_rating": 0,
            "escalations": 0,
            "total_failures": 0,
            "failure_rate": 0,
        }
