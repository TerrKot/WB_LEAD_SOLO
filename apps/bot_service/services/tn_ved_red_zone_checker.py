"""TN VED Red Zone Checker service."""
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Literal, Tuple

import structlog

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

logger = structlog.get_logger()

Decision = Literal["BLOCK", "RISK", "ALLOW"]


class TNVEDRedZoneChecker:
    """Service for checking TN VED codes against red zone rules."""

    def __init__(self, rules_file: Optional[str] = None):
        """
        Initialize checker with rules from JSON file.

        Args:
            rules_file: Path to rules JSON file. If None, uses default path.
        """
        if rules_file is None:
            # Default path relative to project root
            rules_file = project_root / "rules" / "TN VED RED ZONE RULES.json"
        
        rules_path = Path(rules_file)
        if not rules_path.is_absolute():
            rules_path = project_root / rules_path
        
        with open(rules_path, 'r', encoding='utf-8') as f:
            self.rules_data = json.load(f)
        
        self.rules = self.rules_data.get('rules', [])
        logger.info("tn_ved_red_zone_checker_initialized", rules_count=len(self.rules))

    def normalize_code(self, code: str) -> str:
        """
        Normalize TN VED code to 10-digit string.

        Args:
            code: TN VED code (can contain spaces, dots, dashes)

        Returns:
            Normalized 10-digit code string
        """
        # Extract only digits
        digits = ''.join(filter(str.isdigit, code))
        # Take first 10 digits and pad with zeros on the right if needed
        normalized = (digits[:10]).ljust(10, '0')
        
        logger.debug(
            "tn_ved_code_normalized",
            original=code,
            normalized=normalized
        )
        
        return normalized

    def check_code(self, tnved_code: str) -> Tuple[Decision, Optional[str]]:
        """
        Check TN VED code against red zone rules.

        Args:
            tnved_code: TN VED code to check

        Returns:
            Tuple of (decision, reason) where:
            - decision: "BLOCK", "RISK", or "ALLOW"
            - reason: Reason string if blocked/risky, None if allowed
        """
        normalized_code = self.normalize_code(tnved_code)
        
        # Check rules from top to bottom (first match wins)
        for rule in self.rules:
            decision = rule.get('decision')
            conditions = rule.get('conditions', [])
            
            if self._matches_conditions(normalized_code, conditions):
                reason = rule.get('reason', '')
                rule_id = rule.get('id', 'unknown')
                
                logger.info(
                    "tn_ved_red_zone_match",
                    code=normalized_code,
                    decision=decision,
                    rule_id=rule_id,
                    reason=reason
                )
                
                return decision, reason
        
        # No matches - ALLOW
        logger.debug(
            "tn_ved_red_zone_no_match",
            code=normalized_code,
            decision="ALLOW"
        )
        
        return "ALLOW", None

    def _matches_conditions(self, code: str, conditions: list) -> bool:
        """
        Check if code matches any of the conditions.

        Args:
            code: Normalized 10-digit code
            conditions: List of condition dictionaries

        Returns:
            True if code matches any condition, False otherwise
        """
        for condition in conditions:
            condition_type = condition.get('type')
            length = condition.get('length')
            value = condition.get('value')
            
            if condition_type == 'prefix':
                # Compare first N digits
                prefix = code[:length]
                if prefix == value:
                    return True
            
            elif condition_type == 'range':
                # Compare range by first N digits (string comparison)
                prefix = code[:length]
                if isinstance(value, list) and len(value) == 2:
                    start, end = value
                    # String comparison for ranges like ["01", "24"]
                    if start <= prefix <= end:
                        return True
            
            elif condition_type == 'exact':
                # Exact match of 10-digit code
                if code == value:
                    return True
        
        return False

