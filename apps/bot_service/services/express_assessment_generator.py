"""Service for generating express assessment templates."""
from typing import Dict, Any, Literal, Optional
import structlog

logger = structlog.get_logger()

AssessmentStatus = Literal["🟢", "🟡", "🟠", "🔴"]


class ExpressAssessmentGenerator:
    """Service for generating express assessment templates."""

    # Threshold for classification
    SPECIFIC_VALUE_THRESHOLD_USD_PER_KG = 20.0

    @staticmethod
    def classify_by_specific_value(specific_value_usd_per_kg: float) -> AssessmentStatus:
        """
        Classify product by specific value.

        Args:
            specific_value_usd_per_kg: Specific value in USD/kg

        Returns:
            Assessment status: 🟢 (< 20 USD/kg) or 🟡 (>= 20 USD/kg)
        """
        if specific_value_usd_per_kg < ExpressAssessmentGenerator.SPECIFIC_VALUE_THRESHOLD_USD_PER_KG:
            return "🟢"
        else:
            return "🟡"

    @staticmethod
    def generate_template(
        status: AssessmentStatus,
        specific_value_usd_per_kg: Optional[float] = None,
        product_name: Optional[str] = None,
        tn_ved_code: Optional[str] = None,
        orange_zone_reason: Optional[str] = None,
        red_zone_reason: Optional[str] = None
    ) -> str:
        """
        Generate express assessment template.

        Args:
            status: Assessment status (🟢/🟡/🟠/🔴)
            specific_value_usd_per_kg: Specific value in USD/kg (for 🟢/🟡)
            product_name: Product name (optional)
            tn_ved_code: TN VED code (optional)
            orange_zone_reason: Orange zone reason (for 🟠)
            red_zone_reason: Red zone reason (for 🔴)

        Returns:
            Formatted assessment message
        """
        if status == "🔴":
            # Red zone - fixed template
            message = (
                "🔴 <b>Белая доставка — только после подготовки / смены продукта, с текущей категорией товара белая схема не рекомендована.</b>\n\n"
            )
            # Показываем код ТН ВЭД только если он определен
            if tn_ved_code:
                message += f"Код ТН ВЭД: <code>{tn_ved_code}</code>\n"
            if red_zone_reason:
                message += f"Причина: {red_zone_reason}\n"
            message += "\nТовар не может быть доставлен белой логистикой."
            return message

        elif status == "🟠":
            # Orange zone - template with reason
            message = (
                "🟠 <b>Белая доставка — стратегическая цель, есть дополнительные процедуры маркировки или расчеты по спец тарифам, требует больше внимания к процессам.</b>\n\n"
                f"Код ТН ВЭД: <code>{tn_ved_code or 'N/A'}</code>\n"
            )
            if orange_zone_reason:
                message += f"\n{orange_zone_reason}\n"
            return message

        elif status == "🟢":
            # Green zone - white logistics favorite
            message = (
                "🟢 <b>Белая доставка — фаворит, товар очень хорошо подходит под белую схему.</b>\n\n"
            )
            if product_name:
                message += f"Товар: {product_name}\n"
            if tn_ved_code:
                message += f"Код ТН ВЭД: <code>{tn_ved_code}</code>\n"
            message += (
                "\n✅ Товар оптимален для белой логистики.\n"
                "💡 Рекомендуется перейти к подробному расчёту."
            )
            return message

        elif status == "🟡":
            # Yellow zone - white logistics working option
            message = (
                "🟡 <b>Белая доставка — рабочий вариант, белая схема возможна, но требует детального расчета юнит-экономики</b>\n\n"
            )
            if product_name:
                message += f"Товар: {product_name}\n"
            if tn_ved_code:
                message += f"Код ТН ВЭД: <code>{tn_ved_code}</code>\n"
            message += (
                "\n⚠️ Товар может быть доставлен белой логистикой, но требует дополнительного анализа.\n"
                "💡 Рекомендуется перейти к подробному расчёту."
            )
            return message

        else:
            logger.warning(
                "unknown_assessment_status",
                status=status
            )
            return f"❓ Неизвестный статус: {status}"

    @staticmethod
    def generate_result_dict(
        status: AssessmentStatus,
        specific_value_usd_per_kg: Optional[float] = None,
        product_data: Optional[Dict[str, Any]] = None,
        tn_ved_code: Optional[str] = None,
        orange_zone_reason: Optional[str] = None,
        red_zone_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate result dictionary for express assessment.

        Args:
            status: Assessment status
            specific_value_usd_per_kg: Specific value in USD/kg
            product_data: Product data dictionary
            tn_ved_code: TN VED code
            orange_zone_reason: Orange zone reason
            red_zone_reason: Red zone reason

        Returns:
            Result dictionary
        """
        product_name = None
        if product_data:
            product_name = product_data.get('name')

        message = ExpressAssessmentGenerator.generate_template(
            status=status,
            specific_value_usd_per_kg=specific_value_usd_per_kg,
            product_name=product_name,
            tn_ved_code=tn_ved_code,
            orange_zone_reason=orange_zone_reason,
            red_zone_reason=red_zone_reason
        )

        result = {
            "status": status,
            "message": message,
            "specific_value_usd_per_kg": specific_value_usd_per_kg,
            "product_name": product_name,
            "tn_ved_code": tn_ved_code
        }

        if orange_zone_reason:
            result["orange_zone_reason"] = orange_zone_reason
        if red_zone_reason:
            result["red_zone_reason"] = red_zone_reason

        return result

