"""Unit tests for Express Assessment Generator."""
import pytest

from apps.bot_service.services.express_assessment_generator import (
    ExpressAssessmentGenerator,
    AssessmentStatus
)


class TestExpressAssessmentGenerator:
    """Test cases for ExpressAssessmentGenerator."""

    @pytest.fixture
    def generator(self):
        """Create ExpressAssessmentGenerator instance."""
        return ExpressAssessmentGenerator()

    def test_classify_green_zone(self, generator):
        """Test classification for green zone (< 10 USD/kg)."""
        status = generator.classify_by_specific_value(5.0)
        assert status == "🟢"

    def test_classify_yellow_zone(self, generator):
        """Test classification for yellow zone (>= 10 USD/kg)."""
        status = generator.classify_by_specific_value(10.0)
        assert status == "🟡"

    def test_classify_yellow_zone_high_value(self, generator):
        """Test classification for high-value yellow zone."""
        status = generator.classify_by_specific_value(50.0)
        assert status == "🟡"

    def test_classify_threshold_boundary(self, generator):
        """Test classification at threshold boundary."""
        # Just below threshold
        status_below = generator.classify_by_specific_value(9.99)
        assert status_below == "🟢"
        
        # At threshold
        status_at = generator.classify_by_specific_value(10.0)
        assert status_at == "🟡"
        
        # Just above threshold
        status_above = generator.classify_by_specific_value(10.01)
        assert status_above == "🟡"

    def test_generate_template_green(self, generator):
        """Test template generation for green zone."""
        template = generator.generate_template(
            status="🟢",
            specific_value_usd_per_kg=5.0,
            product_name="Тестовый товар",
            tn_ved_code="1234567890"
        )
        
        assert "🟢" in template
        assert "Белый фаворит" in template
        assert "5.00 USD/кг" in template
        assert "Тестовый товар" in template
        assert "1234567890" in template
        assert "оптимален для белой логистики" in template

    def test_generate_template_yellow(self, generator):
        """Test template generation for yellow zone."""
        template = generator.generate_template(
            status="🟡",
            specific_value_usd_per_kg=15.0,
            product_name="Тестовый товар",
            tn_ved_code="1234567890"
        )
        
        assert "🟡" in template
        assert "Белый рабочий вариант" in template
        assert "15.00 USD/кг" in template
        assert "Тестовый товар" in template
        assert "1234567890" in template
        assert "может быть доставлен белой логистикой" in template

    def test_generate_template_red(self, generator):
        """Test template generation for red zone."""
        template = generator.generate_template(
            status="🔴",
            tn_ved_code="1234567890",
            red_zone_reason="Товар попадает в красную зону"
        )
        
        assert "🔴" in template
        assert "Экспресс-расчёт завершён" in template
        assert "1234567890" in template
        assert "Товар попадает в красную зону" in template
        assert "не может быть доставлен белой логистикой" in template

    def test_generate_template_orange(self, generator):
        """Test template generation for orange zone."""
        template = generator.generate_template(
            status="🟠",
            tn_ved_code="1234567890",
            orange_zone_reason="Товар требует обязательной маркировки"
        )
        
        assert "🟠" in template
        assert "Экспресс-расчёт завершён" in template
        assert "1234567890" in template
        assert "Товар требует обязательной маркировки" in template
        assert "не может быть доставлен белой логистикой" in template

    def test_generate_result_dict_green(self, generator):
        """Test result dictionary generation for green zone."""
        product_data = {
            "name": "Тестовый товар",
            "id": 12345
        }
        
        result = generator.generate_result_dict(
            status="🟢",
            specific_value_usd_per_kg=5.0,
            product_data=product_data,
            tn_ved_code="1234567890"
        )
        
        assert result["status"] == "🟢"
        assert result["specific_value_usd_per_kg"] == 5.0
        assert result["product_name"] == "Тестовый товар"
        assert result["tn_ved_code"] == "1234567890"
        assert "message" in result
        assert "🟢" in result["message"]

    def test_generate_result_dict_yellow(self, generator):
        """Test result dictionary generation for yellow zone."""
        product_data = {
            "name": "Тестовый товар",
            "id": 12345
        }
        
        result = generator.generate_result_dict(
            status="🟡",
            specific_value_usd_per_kg=15.0,
            product_data=product_data,
            tn_ved_code="1234567890"
        )
        
        assert result["status"] == "🟡"
        assert result["specific_value_usd_per_kg"] == 15.0
        assert result["product_name"] == "Тестовый товар"
        assert result["tn_ved_code"] == "1234567890"
        assert "message" in result
        assert "🟡" in result["message"]

    def test_generate_result_dict_red(self, generator):
        """Test result dictionary generation for red zone."""
        result = generator.generate_result_dict(
            status="🔴",
            tn_ved_code="1234567890",
            red_zone_reason="Товар попадает в красную зону"
        )
        
        assert result["status"] == "🔴"
        assert result["tn_ved_code"] == "1234567890"
        assert result["red_zone_reason"] == "Товар попадает в красную зону"
        assert "message" in result
        assert "🔴" in result["message"]

    def test_generate_result_dict_orange(self, generator):
        """Test result dictionary generation for orange zone."""
        result = generator.generate_result_dict(
            status="🟠",
            tn_ved_code="1234567890",
            orange_zone_reason="Товар требует обязательной маркировки"
        )
        
        assert result["status"] == "🟠"
        assert result["tn_ved_code"] == "1234567890"
        assert result["orange_zone_reason"] == "Товар требует обязательной маркировки"
        assert "message" in result
        assert "🟠" in result["message"]

    def test_generate_template_minimal_data(self, generator):
        """Test template generation with minimal data."""
        template = generator.generate_template(
            status="🟢",
            specific_value_usd_per_kg=5.0
        )
        
        assert "🟢" in template
        assert "5.00 USD/кг" in template

