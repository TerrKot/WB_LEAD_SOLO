"""Unit tests for TN VED Red Zone Checker."""
import pytest
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from apps.bot_service.services.tn_ved_red_zone_checker import TNVEDRedZoneChecker, Decision


class TestTNVEDRedZoneChecker:
    """Test cases for TNVEDRedZoneChecker."""

    @pytest.fixture
    def checker(self):
        """Create TNVEDRedZoneChecker instance."""
        rules_file = project_root / "rules" / "TN VED RED ZONE RULES.json"
        return TNVEDRedZoneChecker(rules_file=str(rules_file))

    def test_normalize_code_basic(self, checker):
        """Test basic code normalization."""
        assert checker.normalize_code("3304990000") == "3304990000"
        assert checker.normalize_code("33 04 99 000 0") == "3304990000"
        assert checker.normalize_code("33.04.99.000.0") == "3304990000"
        assert checker.normalize_code("33-04-99-000-0") == "3304990000"

    def test_normalize_code_short(self, checker):
        """Test normalization of short codes."""
        assert checker.normalize_code("33") == "3300000000"
        assert checker.normalize_code("3304") == "3304000000"
        assert checker.normalize_code("330499") == "3304990000"

    def test_normalize_code_long(self, checker):
        """Test normalization of long codes."""
        assert checker.normalize_code("330499000012345") == "3304990000"

    def test_check_code_food_block(self, checker):
        """Test BLOCK for food products (chapters 01-24)."""
        decision, reason = checker.check_code("0101010000")
        assert decision == "BLOCK"
        assert reason is not None
        assert "пищевая" in reason.lower() or "food" in reason.lower()

        decision, reason = checker.check_code("2401010000")
        assert decision == "BLOCK"

    def test_check_code_pharma_block(self, checker):
        """Test BLOCK for pharmaceutical products (chapter 30)."""
        decision, reason = checker.check_code("3001010000")
        assert decision == "BLOCK"
        assert reason is not None

    def test_check_code_cosmetics_block(self, checker):
        """Test BLOCK for cosmetics (chapter 33)."""
        decision, reason = checker.check_code("3304990000")
        assert decision == "BLOCK"
        assert reason is not None
        assert "космети" in reason.lower() or "парфюмер" in reason.lower()

    def test_check_code_medical_devices_block(self, checker):
        """Test BLOCK for medical devices."""
        decision, reason = checker.check_code("9018010000")
        assert decision == "BLOCK"

        decision, reason = checker.check_code("9019010000")
        assert decision == "BLOCK"

        decision, reason = checker.check_code("9021010000")
        assert decision == "BLOCK"

    def test_check_code_alcohol_block(self, checker):
        """Test BLOCK for alcohol (2203-2208)."""
        decision, reason = checker.check_code("2203010000")
        assert decision == "BLOCK"

        decision, reason = checker.check_code("2208010000")
        assert decision == "BLOCK"

    def test_check_code_tobacco_block(self, checker):
        """Test BLOCK for tobacco (chapter 24)."""
        decision, reason = checker.check_code("2401010000")
        assert decision == "BLOCK"

    def test_check_code_weapons_block(self, checker):
        """Test BLOCK for weapons (chapter 93)."""
        decision, reason = checker.check_code("9301010000")
        assert decision == "BLOCK"

    def test_check_code_drones_block(self, checker):
        """Test BLOCK for drones (8806)."""
        decision, reason = checker.check_code("8806010000")
        assert decision == "BLOCK"

    def test_check_code_batteries_block(self, checker):
        """Test BLOCK for batteries (8507)."""
        decision, reason = checker.check_code("8507010000")
        assert decision == "BLOCK"

    def test_check_code_risk_category(self, checker):
        """Test RISK category."""
        decision, reason = checker.check_code("8471010000")
        assert decision == "RISK"
        assert reason is not None

        decision, reason = checker.check_code("8517010000")
        assert decision == "RISK"

    def test_check_code_allow_category(self, checker):
        """Test ALLOW for codes not in red zone."""
        decision, reason = checker.check_code("8501010000")  # Electric motors
        assert decision == "ALLOW"
        assert reason is None

        decision, reason = checker.check_code("6401010000")  # Footwear
        assert decision == "ALLOW"
        assert reason is None

    def test_check_code_with_spaces_and_dots(self, checker):
        """Test that codes with spaces and dots are normalized correctly."""
        decision, reason = checker.check_code("33 04 99 000 0")
        assert decision == "BLOCK"

        decision, reason = checker.check_code("33.04.99.000.0")
        assert decision == "BLOCK"

    def test_check_code_range_condition(self, checker):
        """Test range condition (e.g., food products 01-24)."""
        # Test start of range
        decision, reason = checker.check_code("0101010000")
        assert decision == "BLOCK"

        # Test middle of range
        decision, reason = checker.check_code("1201010000")
        assert decision == "BLOCK"

        # Test end of range
        decision, reason = checker.check_code("2401010000")
        assert decision == "BLOCK"

    def test_check_code_prefix_condition(self, checker):
        """Test prefix condition."""
        decision, reason = checker.check_code("3001010000")
        assert decision == "BLOCK"

        decision, reason = checker.check_code("3009999999")
        assert decision == "BLOCK"

    def test_check_code_exact_condition(self, checker):
        """Test exact condition if any exists in rules."""
        # This test depends on whether there are exact conditions in rules
        # For now, we test that exact matching logic works
        # Most rules use prefix or range, so this is a placeholder
        pass

    def test_check_code_priority_block_over_risk(self, checker):
        """Test that BLOCK has priority over RISK."""
        # Codes that match BLOCK rules should return BLOCK, not RISK
        decision, reason = checker.check_code("3304990000")
        assert decision == "BLOCK"

    def test_check_code_normalization_edge_cases(self, checker):
        """Test edge cases in normalization."""
        # Empty string
        assert checker.normalize_code("") == "0000000000"

        # Only non-digits
        assert checker.normalize_code("abc") == "0000000000"

        # Mixed digits and non-digits
        assert checker.normalize_code("33abc04") == "3304000000"

