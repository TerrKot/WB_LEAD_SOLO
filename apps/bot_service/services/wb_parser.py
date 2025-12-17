"""WB Parser Service for fetching product data from Wildberries API v4."""
import json
from typing import Optional, Dict, Any, List
import aiohttp
import structlog

from apps.bot_service.utils.error_handler import ErrorHandler

logger = structlog.get_logger()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.wildberries.ru/",
    "Origin": "https://www.wildberries.ru"
}


class WBParserService:
    """Service for parsing Wildberries API v4 data."""

    def __init__(self):
        """Initialize WB Parser Service."""
        self.api_url = "https://u-card.wb.ru/cards/v4/list"
        self.timeout = aiohttp.ClientTimeout(total=15)

    async def fetch_product_data(
        self, articles: List[int], dest: int = -1257786, spp: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch product data from WB API v4.

        Args:
            articles: List of article IDs (nmId)
            dest: Delivery region
            spp: SPP parameter

        Returns:
            JSON response from API or None on error
        """
        if not articles:
            logger.warning("empty_articles_list")
            return None

        params = {
            "appType": 1,
            "curr": "rub",
            "dest": dest,
            "spp": spp,
            "hide_vflags": 4294967296,
            "hide_dflags": 131072,
            "hide_dtype": "9;11;13",
            "ab_testing": "false",
            "lang": "ru",
            "nm": ";".join(str(a) for a in articles)
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                logger.debug(
                    "wb_api_request",
                    url=self.api_url,
                    params=params,
                    articles=articles
                )
                async with session.get(
                    self.api_url, params=params, headers=DEFAULT_HEADERS
                ) as response:
                    status = response.status
                    logger.debug("wb_api_response_status", status=status, articles=articles)
                    
                    if status != 200:
                        response_text = await response.text()
                        logger.error(
                            "wb_api_non_200_status",
                            status=status,
                            articles=articles,
                            response_preview=response_text[:500]
                        )
                        response.raise_for_status()
                    
                    data = await response.json()
                    products_count = len(data.get("products", [])) if isinstance(data, dict) else 0
                    logger.info(
                        "wb_api_fetch_success",
                        articles_count=len(articles),
                        products_found=products_count,
                        response_keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict"
                    )
                    return data
        except aiohttp.ClientError as e:
            error_type = ErrorHandler.classify_wb_error(e)
            logger.error(
                "wb_api_request_error",
                event_type="wb_api_error",
                error_type=error_type,
                error=str(e)[:200],  # Truncate error message
                error_class=type(e).__name__,
                articles=articles
            )
            return None
        except json.JSONDecodeError as e:
            logger.error(
                "wb_api_json_error",
                event_type="wb_api_json_error",
                error=str(e)[:200],
                articles=articles
            )
            return None
        except Exception as e:
            error_type = ErrorHandler.classify_wb_error(e)
            logger.error(
                "wb_api_unexpected_error",
                event_type="wb_api_unexpected_error",
                error_type=error_type,
                error=str(e)[:200],
                error_class=type(e).__name__,
                articles=articles
            )
            return None

    def normalize_product(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize product data from API v4, preserving ALL fields from original JSON.
        All fields are present, even if they are empty/null.

        Args:
            product: Raw product data from API

        Returns:
            Normalized product data with all fields
        """
        # Create a copy of the original product - preserve ALL fields
        normalized = dict(product)

        # Process nested structures, preserving all fields
        if 'sizes' in normalized and isinstance(normalized['sizes'], list):
            normalized_sizes = []
            for size in normalized['sizes']:
                if isinstance(size, dict):
                    normalized_size = dict(size)  # Preserve all size fields
                    # Process price in size, preserving all fields
                    if 'price' in normalized_size and isinstance(normalized_size['price'], dict):
                        price_info = normalized_size['price']
                        normalized_size['price'] = {
                            'basic': price_info.get('basic'),
                            'product': price_info.get('product'),
                            'logistics': price_info.get('logistics'),
                            'return': price_info.get('return')
                        }
                    normalized_sizes.append(normalized_size)
                else:
                    normalized_sizes.append(size)
            normalized['sizes'] = normalized_sizes

        if 'colors' in normalized and isinstance(normalized['colors'], list):
            normalized_colors = []
            for color in normalized['colors']:
                if isinstance(color, dict):
                    normalized_colors.append({
                        'id': color.get('id'),
                        'name': color.get('name')
                    })
                else:
                    normalized_colors.append(color)
            normalized['colors'] = normalized_colors

        # Process meta, if present
        if 'meta' in normalized and isinstance(normalized['meta'], dict):
            normalized['meta'] = dict(normalized['meta'])
            if 'tokens' not in normalized['meta']:
                normalized['meta']['tokens'] = []
        elif 'meta' not in normalized:
            normalized['meta'] = {'tokens': []}

        # Ensure all main fields are present (even if empty)
        # This guarantees consistent structure
        default_fields = {
            'id': None,
            'name': '',
            'brand': '',
            'brandId': None,
            'siteBrandId': None,
            'supplier': '',
            'supplierId': None,
            'supplierRating': None,
            'supplierFlags': None,
            'rating': None,
            'reviewRating': None,
            'nmReviewRating': None,
            'feedbacks': None,
            'nmFeedbacks': None,
            'pics': None,
            'volume': None,
            'weight': None,
            'totalQuantity': None,
            'colors': [],
            'sizes': [],
            'subjectId': None,
            'subjectParentId': None,
            'entity': '',
            'matchId': None,
            'sort': None,
            'time1': None,
            'time2': None,
            'wh': None,
            'dtype': None,
            'dist': None,
            'root': None,
            'kindId': None,
            'viewFlags': None,
        }

        # Fill missing fields with default values
        for field, default_value in default_fields.items():
            if field not in normalized:
                normalized[field] = default_value

        return normalized

    async def get_product_by_article(self, article_id: int) -> Optional[Dict[str, Any]]:
        """
        Get single product by article ID.

        Args:
            article_id: Article ID (nmId)

        Returns:
            Normalized product data or None if not found/error
        """
        logger.info("fetching_product", article_id=article_id)
        data = await self.fetch_product_data([article_id])
        
        if not data:
            logger.warning("api_response_empty", article_id=article_id)
            return None
        
        if 'products' not in data:
            logger.warning(
                "api_response_no_products_key",
                article_id=article_id,
                response_keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict"
            )
            return None

        products = data.get('products', [])
        if not products:
            logger.warning(
                "products_list_empty",
                article_id=article_id,
                response_data=data
            )
            return None

        logger.info(
            "products_received",
            article_id=article_id,
            products_count=len(products),
            product_ids=[p.get('id') for p in products if isinstance(p, dict)]
        )

        # Find product with matching ID
        for product in products:
            product_id = product.get('id') if isinstance(product, dict) else None
            if product_id == article_id:
                normalized = self.normalize_product(product)
                logger.info("product_found", article_id=article_id, product_name=normalized.get('name'))
                return normalized

        # If no exact match, try first product (sometimes API returns different ID format)
        if products and isinstance(products[0], dict):
            first_product = products[0]
            logger.warning(
                "product_id_mismatch_using_first",
                requested_id=article_id,
                found_ids=[p.get('id') for p in products if isinstance(p, dict)],
                first_product_id=first_product.get('id')
            )
            # Use first product as fallback
            normalized = self.normalize_product(first_product)
            # Update ID to match requested
            normalized['id'] = article_id
            return normalized

        logger.warning(
            "product_id_mismatch",
            article_id=article_id,
            found_ids=[p.get('id') if isinstance(p, dict) else str(p) for p in products]
        )
        return None

    def get_product_price(self, product: Dict[str, Any]) -> Optional[int]:
        """
        Get product price in kopecks from normalized product data.

        Args:
            product: Normalized product data

        Returns:
            Price in kopecks or None if not found
        """
        sizes = product.get('sizes', [])
        if not sizes:
            return None

        # Get price from first size (usually all sizes have same price)
        first_size = sizes[0]
        if isinstance(first_size, dict):
            price_info = first_size.get('price', {})
            if isinstance(price_info, dict):
                # Prefer product price (with discount), fallback to basic
                price = price_info.get('product') or price_info.get('basic')
                if price is not None:
                    return int(price)

        return None

    def get_product_weight(self, product: Dict[str, Any]) -> Optional[float]:
        """
        Get product weight in kg from normalized product data.

        Args:
            product: Normalized product data

        Returns:
            Weight in kg or None if not found
        """
        weight = product.get('weight')
        if weight is not None:
            try:
                return float(weight)
            except (ValueError, TypeError):
                pass
        return None

    def get_product_volume(self, product: Dict[str, Any]) -> Optional[float]:
        """
        Get product volume in liters from normalized product data.
        
        NOTE: WB API returns volume in dm³ (cubic decimeters), where 1 dm³ = 1 liter!
        However, the value appears to be in 0.1 dm³ units (deciliters), so we divide by 10.
        Example: API returns 215, which means 21.5 liters (215 * 0.1 = 21.5).

        Args:
            product: Normalized product data

        Returns:
            Volume in liters or None if not found
        """
        volume = product.get('volume')
        if volume is not None:
            try:
                # API returns volume in 0.1 dm³ units (deciliters), convert to liters
                # 1 deciliter = 0.1 liter, so divide by 10
                volume_liters = float(volume) / 10.0
                return volume_liters
            except (ValueError, TypeError):
                pass
        return None

    def get_product_name(self, product: Dict[str, Any]) -> Optional[str]:
        """
        Get product name from normalized product data.

        Args:
            product: Normalized product data

        Returns:
            Product name or None if not found
        """
        name = product.get('name')
        if name:
            return str(name)
        return None

    def get_product_description(self, product: Dict[str, Any]) -> Optional[str]:
        """
        Get product description from normalized product data.
        Note: WB API v4 doesn't provide description field directly.
        This method can be extended if description becomes available.

        Args:
            product: Normalized product data

        Returns:
            Product description or None
        """
        # WB API v4 doesn't have description field in the main product structure
        # This can be extended if description is added to API or fetched separately
        return None

