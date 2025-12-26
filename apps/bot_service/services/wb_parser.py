"""WB Parser Service for fetching product data from Wildberries API v4."""
import json
import asyncio
import re
from typing import Optional, Dict, Any, List, Tuple
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

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Initialize WB Parser Service.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 1.0)
        """
        self.api_url = "https://u-card.wb.ru/cards/v4/list"
        self.timeout = aiohttp.ClientTimeout(total=15)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def fetch_product_data(
        self, articles: List[int], dest: int = -1257786, spp: int = 30
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch product data from WB API v4 with retry logic.

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

        last_error = None
        last_status = None
        
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    logger.debug(
                        "wb_api_request",
                        url=self.api_url,
                        params=params,
                        articles=articles,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    async with session.get(
                        self.api_url, params=params, headers=DEFAULT_HEADERS
                    ) as response:
                        status = response.status
                        logger.debug(
                            "wb_api_response_status",
                            status=status,
                            articles=articles,
                            attempt=attempt + 1
                        )
                        
                        if status != 200:
                            response_text = await response.text()
                            last_status = status
                            
                            # Don't retry on 4xx client errors (except 429 rate limit)
                            if 400 <= status < 500 and status != 429:
                                logger.error(
                                    "wb_api_client_error_no_retry",
                                    status=status,
                                    articles=articles,
                                    response_preview=response_text[:500]
                                )
                                response.raise_for_status()
                            
                            # Retry on 5xx server errors and 429 rate limit
                            if attempt < self.max_retries - 1:
                                logger.warning(
                                    "wb_api_non_200_status_retrying",
                                    status=status,
                                    articles=articles,
                                    attempt=attempt + 1,
                                    max_retries=self.max_retries,
                                    response_preview=response_text[:500]
                                )
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            
                            logger.error(
                                "wb_api_non_200_status",
                                status=status,
                                articles=articles,
                                attempt=attempt + 1,
                                response_preview=response_text[:500]
                            )
                            response.raise_for_status()
                        
                        data = await response.json()
                        products_count = len(data.get("products", [])) if isinstance(data, dict) else 0
                        
                        # If products list is empty, retry (sometimes API returns empty on first request)
                        if products_count == 0 and attempt < self.max_retries - 1:
                            logger.warning(
                                "wb_api_empty_products_retrying",
                                articles_count=len(articles),
                                attempt=attempt + 1,
                                max_retries=self.max_retries
                            )
                            await asyncio.sleep(self.retry_delay * (attempt + 1))
                            continue
                        
                        logger.info(
                            "wb_api_fetch_success",
                            articles_count=len(articles),
                            products_found=products_count,
                            attempt=attempt + 1,
                            response_keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict"
                        )
                        return data
                        
            except aiohttp.ClientError as e:
                last_error = e
                error_type = ErrorHandler.classify_wb_error(e)
                
                # Retry on network errors
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "wb_api_request_error_retrying",
                        event_type="wb_api_error",
                        error_type=error_type,
                        error=str(e)[:200],
                        error_class=type(e).__name__,
                        articles=articles,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                logger.error(
                    "wb_api_request_error",
                    event_type="wb_api_error",
                    error_type=error_type,
                    error=str(e)[:200],
                    error_class=type(e).__name__,
                    articles=articles,
                    attempt=attempt + 1
                )
                return None
                
            except asyncio.TimeoutError as e:
                last_error = e
                
                # Retry on timeout
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "wb_api_timeout_retrying",
                        articles=articles,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                logger.error(
                    "wb_api_timeout",
                    articles=articles,
                    attempt=attempt + 1
                )
                return None
                
            except json.JSONDecodeError as e:
                last_error = e
                
                # Retry on JSON decode errors (might be temporary)
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "wb_api_json_error_retrying",
                        event_type="wb_api_json_error",
                        error=str(e)[:200],
                        articles=articles,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                logger.error(
                    "wb_api_json_error",
                    event_type="wb_api_json_error",
                    error=str(e)[:200],
                    articles=articles,
                    attempt=attempt + 1
                )
                return None
                
            except Exception as e:
                last_error = e
                error_type = ErrorHandler.classify_wb_error(e)
                
                # Retry on unexpected errors
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "wb_api_unexpected_error_retrying",
                        event_type="wb_api_unexpected_error",
                        error_type=error_type,
                        error=str(e)[:200],
                        error_class=type(e).__name__,
                        articles=articles,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                logger.error(
                    "wb_api_unexpected_error",
                    event_type="wb_api_unexpected_error",
                    error_type=error_type,
                    error=str(e)[:200],
                    error_class=type(e).__name__,
                    articles=articles,
                    attempt=attempt + 1
                )
                return None
        
        # All retries exhausted
        logger.error(
            "wb_api_all_retries_exhausted",
            articles=articles,
            max_retries=self.max_retries,
            last_error=str(last_error)[:200] if last_error else None,
            last_status=last_status
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
        Get single product by article ID with retry logic.

        Args:
            article_id: Article ID (nmId)

        Returns:
            Normalized product data or None if not found/error
        """
        logger.info("fetching_product", article_id=article_id)
        
        # fetch_product_data already has retry logic, but we also retry here
        # if product is not found in the response (empty products list)
        for attempt in range(self.max_retries):
            data = await self.fetch_product_data([article_id])
            
            if not data:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "api_response_empty_retrying",
                        article_id=article_id,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                logger.warning("api_response_empty", article_id=article_id)
                return None
            
            if 'products' not in data:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "api_response_no_products_key_retrying",
                        article_id=article_id,
                        response_keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict",
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                logger.warning(
                    "api_response_no_products_key",
                    article_id=article_id,
                    response_keys=list(data.keys()) if isinstance(data, dict) else "not_a_dict"
                )
                return None

            products = data.get('products', [])
            if not products:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "products_list_empty_retrying",
                        article_id=article_id,
                        attempt=attempt + 1,
                        max_retries=self.max_retries
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
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
                product_ids=[p.get('id') for p in products if isinstance(p, dict)],
                attempt=attempt + 1
            )

            # Find product with matching ID
            for product in products:
                product_id = product.get('id') if isinstance(product, dict) else None
                if product_id == article_id:
                    # Log raw data before normalization to debug reviewRating/feedbacks
                    logger.debug(
                        "product_raw_data",
                        article_id=article_id,
                        reviewRating=product.get('reviewRating'),
                        feedbacks=product.get('feedbacks'),
                        nmReviewRating=product.get('nmReviewRating'),
                        nmFeedbacks=product.get('nmFeedbacks'),
                        rating=product.get('rating')
                    )
                    normalized = self.normalize_product(product)
                    logger.info(
                        "product_found",
                        article_id=article_id,
                        product_name=normalized.get('name'),
                        reviewRating=normalized.get('reviewRating'),
                        feedbacks=normalized.get('feedbacks')
                    )
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

            # Product not found in response, retry
            if attempt < self.max_retries - 1:
                logger.warning(
                    "product_id_mismatch_retrying",
                    article_id=article_id,
                    found_ids=[p.get('id') if isinstance(p, dict) else str(p) for p in products],
                    attempt=attempt + 1,
                    max_retries=self.max_retries
                )
                await asyncio.sleep(self.retry_delay * (attempt + 1))
                continue

        logger.warning(
            "product_id_mismatch",
            article_id=article_id,
            max_retries=self.max_retries
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

    def get_product_review_rating(self, product: Dict[str, Any]) -> Optional[float]:
        """
        Get product review rating from normalized product data.

        Args:
            product: Normalized product data

        Returns:
            Review rating (0.0-5.0) or None if not found
        """
        review_rating = product.get('reviewRating')
        # Check both reviewRating and nmReviewRating as fallback
        if review_rating is None:
            review_rating = product.get('nmReviewRating')
        
        if review_rating is not None:
            try:
                rating = float(review_rating)
                if 0.0 <= rating <= 5.0:  # Validate range (0.0 is valid - no reviews yet)
                    return rating
            except (ValueError, TypeError):
                pass
        return None

    def get_product_feedbacks(self, product: Dict[str, Any]) -> Optional[int]:
        """
        Get product feedbacks count from normalized product data.

        Args:
            product: Normalized product data

        Returns:
            Number of feedbacks or None if not found
        """
        feedbacks = product.get('feedbacks')
        # Check both feedbacks and nmFeedbacks as fallback
        if feedbacks is None:
            feedbacks = product.get('nmFeedbacks')
        
        if feedbacks is not None:
            try:
                count = int(feedbacks)
                if count >= 0:  # Validate non-negative (0 is valid - no feedbacks yet)
                    return count
            except (ValueError, TypeError):
                pass
        return None

    def _calculate_basket_number(self, vol: int) -> int:
        """
        Calculate basket number from vol.
        
        For 9-digit article IDs: vol = first 4 digits
        For 8-digit article IDs: vol = first 3 digits
        
        Formula: basket = (vol // 175) + adjustment
        - adjustment = 2 for vol < 3000
        - adjustment = 1 for 3000 <= vol < 3200
        - adjustment = 0 for 3200 <= vol < 5000
        - adjustment = -6 for vol >= 5000
        
        Args:
            vol: First 3-4 digits of article_id (depending on article ID length)
            
        Returns:
            Basket number (0-99)
        """
        base = vol // 175
        
        if vol < 3000:
            adjustment = 2
        elif vol < 3200:
            adjustment = 1
        elif vol < 5000:
            adjustment = 0
        else:  # vol >= 5000
            adjustment = -6
        
        basket = base + adjustment
        # Ensure basket is in valid range (0-99)
        return max(0, min(99, basket))

    def _build_card_url(self, article_id: int) -> str:
        """
        Build URL for product card JSON from article ID.
        
        Args:
            article_id: Article ID (nmId)
            
        Returns:
            URL string
        """
        # Format: https://basket-{basket_num}.wbbasket.ru/vol{vol}/part{part}/{article_id}/info/ru/card.json
        # Example: https://basket-26.wbbasket.ru/vol4585/part458510/458510242/info/ru/card.json
        # 
        # Logic:
        # - basket number is calculated from vol using formula: (vol // 175) + adjustment
        # - vol = first 4 digits of article_id
        # - part = first 6 digits of article_id
        # Format depends on article ID length:
        # - 9 digits: vol = first 4 digits, part = first 6 digits (e.g., 458510242 -> vol4585/part458510)
        # - 8 digits: vol = first 3 digits, part = first 5 digits (e.g., 14698790 -> vol146/part14698)
        article_str = str(article_id)
        if len(article_str) >= 9:
            # 9-digit article IDs: vol = first 4 digits, part = first 6 digits
            vol = int(article_str[:4])
            part = article_str[:6]
        elif len(article_str) >= 8:
            # 8-digit article IDs: vol = first 3 digits, part = first 5 digits
            vol = int(article_str[:3])
            part = article_str[:5]
        elif len(article_str) >= 6:
            # 7-digit or 6-digit: try to use first 4 for vol, first 6 for part if possible
            vol = int(article_str[:4]) if len(article_str) >= 4 else int(article_str[:3])
            part = article_str[:6] if len(article_str) >= 6 else article_str[:5] if len(article_str) >= 5 else article_str
        elif len(article_str) >= 5:
            # 5-digit: vol = first 3, part = first 5
            vol = int(article_str[:3])
            part = article_str[:5]
        elif len(article_str) >= 3:
            vol = int(article_str[:3])
            part = article_str
        else:
            vol = int(article_str) if article_str else 0
            part = article_str
        
        basket_num = self._calculate_basket_number(vol)
        # Format basket number with leading zero if < 10 (basket-02, basket-03, etc.)
        basket_str = f"{basket_num:02d}" if basket_num < 10 else str(basket_num)
        
        return f"https://basket-{basket_str}.wbbasket.ru/vol{vol}/part{part}/{article_id}/info/ru/card.json"

    async def fetch_product_card_data(self, article_id: int, basket_num: Optional[int] = None) -> Optional[tuple[Dict[str, Any], Dict[str, int]]]:
        """
        Fetch product card data from basket-*.wbbasket.ru API.
        Basket number is calculated automatically using formula based on article_id.
        If 404 error occurs, tries neighboring basket numbers (±1 to ±8) as fallback.
        
        Args:
            article_id: Article ID (nmId)
            basket_num: Optional basket number to use directly (skip fallback)
            
        Returns:
            Tuple of (Product card JSON data, basket_info dict) or None on error.
            basket_info contains: {"calculated": calculated_basket, "actual": actual_basket}
        """
        # Extract vol and part for URL building
        # Format depends on article ID length:
        # - 9 digits: vol = first 4 digits, part = first 6 digits (e.g., 458510242 -> vol4585/part458510)
        # - 8 digits: vol = first 3 digits, part = first 5 digits (e.g., 14698790 -> vol146/part14698)
        article_str = str(article_id)
        if len(article_str) >= 9:
            # 9-digit article IDs: vol = first 4 digits, part = first 6 digits
            vol = int(article_str[:4])
            part = article_str[:6]
        elif len(article_str) >= 8:
            # 8-digit article IDs: vol = first 3 digits, part = first 5 digits
            vol = int(article_str[:3])
            part = article_str[:5]
        elif len(article_str) >= 6:
            # 7-digit or 6-digit: try to use first 4 for vol, first 6 for part if possible
            vol = int(article_str[:4]) if len(article_str) >= 4 else int(article_str[:3])
            part = article_str[:6] if len(article_str) >= 6 else article_str[:5] if len(article_str) >= 5 else article_str
        elif len(article_str) >= 5:
            # 5-digit: vol = first 3, part = first 5
            vol = int(article_str[:3])
            part = article_str[:5]
        elif len(article_str) >= 3:
            vol = int(article_str[:3])
            part = article_str
        else:
            vol = int(article_str) if article_str else 0
            part = article_str
        
        # Use provided basket number or calculate initial basket number
        if basket_num is not None and 0 <= basket_num <= 99:
            initial_basket = basket_num
            basket_numbers_to_try = [initial_basket]
            logger.info(
                "basket_number_provided",
                article_id=article_id,
                basket_num=basket_num
            )
        else:
            initial_basket = self._calculate_basket_number(vol)
            basket_numbers_to_try = [initial_basket]
        
        # Add neighboring basket numbers as fallback options (only if basket_num not provided)
        if basket_num is None:
            for offset in [-8, -7, -6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6, 7, 8]:
                neighbor_basket = initial_basket + offset
                if 0 <= neighbor_basket <= 99:
                    if neighbor_basket not in basket_numbers_to_try:
                        basket_numbers_to_try.append(neighbor_basket)
        
        logger.info(
            "basket_numbers_to_try",
            article_id=article_id,
            initial_basket=initial_basket,
            basket_numbers=basket_numbers_to_try
        )
        
        # Try each basket number
        for basket_num in basket_numbers_to_try:
            # Format basket number with leading zero if < 10 (basket-02, basket-03, etc.)
            basket_str = f"{basket_num:02d}" if basket_num < 10 else str(basket_num)
            url = f"https://basket-{basket_str}.wbbasket.ru/vol{vol}/part{part}/{article_id}/info/ru/card.json"
            
            for attempt in range(self.max_retries):
                try:
                    async with aiohttp.ClientSession(timeout=self.timeout) as session:
                        logger.debug(
                            "wb_card_api_request",
                            url=url,
                            article_id=article_id,
                            basket_num=basket_num,
                            attempt=attempt + 1,
                            max_retries=self.max_retries
                        )
                        async with session.get(url, headers=DEFAULT_HEADERS) as response:
                            status = response.status
                            
                            if status == 200:
                                data = await response.json()
                                basket_info = {
                                    "calculated": initial_basket,
                                    "actual": basket_num
                                }
                                logger.info(
                                    "wb_card_api_fetch_success",
                                    article_id=article_id,
                                    basket_num=basket_num,
                                    attempt=attempt + 1,
                                    used_fallback=(basket_num != initial_basket),
                                    calculated_basket=initial_basket,
                                    actual_basket=basket_num
                                )
                                return data, basket_info
                            
                            # If 404, try next basket number (don't retry same basket)
                            if status == 404:
                                logger.warning(
                                    "wb_card_api_404_trying_next_basket",
                                    status=status,
                                    article_id=article_id,
                                    basket_num=basket_num,
                                    url=url
                                )
                                break  # Break inner loop, try next basket
                            
                            if 400 <= status < 500 and status != 429:
                                logger.error(
                                    "wb_card_api_client_error",
                                    status=status,
                                    article_id=article_id,
                                    basket_num=basket_num,
                                    url=url
                                )
                                if attempt < self.max_retries - 1:
                                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                                    continue
                                # Try next basket number
                                break
                            
                            # For 5xx or other errors, retry
                            if attempt < self.max_retries - 1:
                                logger.warning(
                                    "wb_card_api_non_200_retrying",
                                    status=status,
                                    article_id=article_id,
                                    basket_num=basket_num,
                                    attempt=attempt + 1
                                )
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            
                            logger.error(
                                "wb_card_api_non_200",
                                status=status,
                                article_id=article_id,
                                basket_num=basket_num
                            )
                            # Try next basket number
                            break
                            
                except aiohttp.ClientError as e:
                    error_type = ErrorHandler.classify_wb_error(e)
                    error_str = str(e).lower()
                    
                    # For DNS/connection errors (Name or service not known, Cannot connect to host),
                    # don't retry - immediately try next basket server
                    is_dns_error = any(phrase in error_str for phrase in [
                        "name or service not known",
                        "cannot connect to host",
                        "nodename nor servname provided",
                        "temporary failure in name resolution"
                    ])
                    
                    if is_dns_error:
                        logger.warning(
                            "wb_card_api_dns_error_skip_retry",
                            error_type=error_type,
                            error=str(e)[:200],
                            article_id=article_id,
                            basket_num=basket_num
                        )
                        # Skip retries, try next basket immediately
                        break
                    
                    # For other connection errors, retry
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            "wb_card_api_request_error_retrying",
                            error_type=error_type,
                            error=str(e)[:200],
                            article_id=article_id,
                            basket_num=basket_num,
                            attempt=attempt + 1
                        )
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
                    
                    logger.error(
                        "wb_card_api_request_error",
                        error_type=error_type,
                        error=str(e)[:200],
                        article_id=article_id,
                        basket_num=basket_num
                    )
                    # Try next basket number
                    break
                    
                except asyncio.TimeoutError:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            "wb_card_api_timeout_retrying",
                            article_id=article_id,
                            basket_num=basket_num,
                            attempt=attempt + 1
                        )
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
                    
                    logger.error("wb_card_api_timeout", article_id=article_id, basket_num=basket_num)
                    # Try next basket number
                    break
                    
                except json.JSONDecodeError as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            "wb_card_api_json_error_retrying",
                            error=str(e)[:200],
                            article_id=article_id,
                            basket_num=basket_num,
                            attempt=attempt + 1
                        )
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
                    
                    logger.error(
                        "wb_card_api_json_error",
                        error=str(e)[:200],
                        article_id=article_id,
                        basket_num=basket_num
                    )
                    # Try next basket number
                    break
                    
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            "wb_card_api_unexpected_error_retrying",
                            error=str(e)[:200],
                            error_class=type(e).__name__,
                            article_id=article_id,
                            basket_num=basket_num,
                            attempt=attempt + 1
                        )
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                        continue
                    
                    logger.error(
                        "wb_card_api_unexpected_error",
                        error=str(e)[:200],
                        error_class=type(e).__name__,
                        article_id=article_id,
                        basket_num=basket_num
                    )
                    # Try next basket number
                    break
        
        # If we get here, all basket numbers failed
        logger.error(
            "wb_card_api_all_baskets_failed",
            article_id=article_id,
            tried_baskets=basket_numbers_to_try
        )
        return None

    async def fetch_product_category_data(self, article_id: int, subject_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Fetch product category data from webapi/product/data.
        
        Args:
            article_id: Article ID (nmId)
            subject_id: Optional subject ID from card data
            
        Returns:
            Category data with type and category names, or None on error
            Format: {
                "type_id": int,
                "type_name": str,  # e.g. "Электроника"
                "category_id": int,
                "category_name": str  # e.g. "Ноутбуки, компьютеры и периферия"
            }
        """
        # Build URL
        params = {
            "subject": subject_id or 0,
            "kind": 0,
            "brand": 0,
            "lang": "ru"
        }
        url = f"https://www.wildberries.ru/webapi/product/{article_id}/data"
        
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    logger.debug(
                        "wb_category_api_request",
                        url=url,
                        params=params,
                        article_id=article_id,
                        attempt=attempt + 1
                    )
                    async with session.get(url, params=params, headers=DEFAULT_HEADERS) as response:
                        status = response.status
                        
                        if status != 200:
                            if attempt < self.max_retries - 1:
                                logger.warning(
                                    "wb_category_api_non_200_retrying",
                                    status=status,
                                    article_id=article_id,
                                    attempt=attempt + 1
                                )
                                await asyncio.sleep(self.retry_delay * (attempt + 1))
                                continue
                            logger.error(
                                "wb_category_api_non_200",
                                status=status,
                                article_id=article_id
                            )
                            return None
                        
                        data = await response.json()
                        
                        # Extract category information
                        # Response structure: {"value": [{"id": 4830, "name": "Электроника"}, {"id": 9491, "parentId": 4830, "name": "Ноутбуки, компьютеры и периферия"}]}
                        category_info = {}
                        if isinstance(data, dict):
                            value_list = data.get("value")
                            if isinstance(value_list, list):
                                # First pass: find root category (type) - no parentId or parentId is None/0
                                for item in value_list:
                                    if isinstance(item, dict):
                                        item_id = item.get("id")
                                        parent_id = item.get("parentId")
                                        name = item.get("name")
                                        
                                        if parent_id is None or parent_id == 0:
                                            # This is a root category (type)
                                            category_info["type_id"] = item_id
                                            category_info["type_name"] = name
                                            break
                                
                                # Second pass: find subcategory with parentId matching type_id
                                type_id = category_info.get("type_id")
                                if type_id:
                                    for item in value_list:
                                        if isinstance(item, dict):
                                            item_id = item.get("id")
                                            parent_id = item.get("parentId")
                                            name = item.get("name")
                                            
                                            if parent_id == type_id:
                                                # This is a subcategory
                                                category_info["category_id"] = item_id
                                                category_info["category_name"] = name
                                                break
                        
                        # Return category_info if we have at least type_name or category_name
                        if category_info.get("type_name") or category_info.get("category_name"):
                            logger.info(
                                "wb_category_api_fetch_success",
                                article_id=article_id,
                                category_info=category_info,
                                attempt=attempt + 1
                            )
                            return category_info
                        else:
                            logger.warning(
                                "wb_category_api_incomplete_data",
                                article_id=article_id,
                                category_info=category_info
                            )
                            return None
                        
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        "wb_category_api_error_retrying",
                        error=str(e)[:200],
                        article_id=article_id,
                        attempt=attempt + 1
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                
                logger.error(
                    "wb_category_api_error",
                    error=str(e)[:200],
                    article_id=article_id
                )
                return None
        
        return None

    def get_tn_ved_basic_data(self, card_data: Dict[str, Any], category_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract basic data for TN VED code determination (stage 1).
        
        Args:
            card_data: Product card data from basket API
            category_data: Optional category data from webapi/product/data
            
        Returns:
            Dictionary with subj_name, subj_root_name, imt_name, type_name, category_name
        """
        result = {
            "subj_name": card_data.get("subj_name", ""),
            "subj_root_name": card_data.get("subj_root_name", ""),
            "imt_name": card_data.get("imt_name", "")
        }
        
        # Add category data if available
        if category_data:
            result["type_name"] = category_data.get("type_name", "")
            result["category_name"] = category_data.get("category_name", "")
        
        return result

    def get_tn_ved_with_description(self, card_data: Dict[str, Any], category_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract data with description for TN VED code determination (stage 2).
        
        Args:
            card_data: Product card data from basket API
            category_data: Optional category data from webapi/product/data
            
        Returns:
            Dictionary with basic data plus description
        """
        result = self.get_tn_ved_basic_data(card_data, category_data)
        result["description"] = card_data.get("description", "")
        return result

    def get_tn_ved_full_data(self, card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get full card data for TN VED code determination (stage 3).
        
        Args:
            card_data: Product card data from basket API
            
        Returns:
            Full card data dictionary
        """
        return dict(card_data)

    def _extract_numeric_value(self, value_str: str, unit: str = "") -> Optional[float]:
        """
        Extract numeric value from string like "2.1 кг" or "42 см".
        
        Args:
            value_str: String with value and unit
            unit: Expected unit (optional, for validation)
            
        Returns:
            Numeric value or None
        """
        if not value_str:
            return None
        
        # Remove unit if present
        value_str = value_str.strip()
        if unit:
            value_str = value_str.replace(unit, "").strip()
        
        # Extract number using regex
        match = re.search(r'[\d.]+', value_str.replace(",", "."))
        if match:
            try:
                return float(match.group())
            except (ValueError, TypeError):
                pass
        
        return None

    def get_package_weight(self, card_data: Dict[str, Any]) -> Optional[float]:
        """
        Extract package weight in kg from card data.
        Supports both "Вес с упаковкой (кг)" and "Вес товара с упаковкой (г)".
        
        Args:
            card_data: Product card data from basket API
            
        Returns:
            Weight in kg or None if not found
        """
        options = card_data.get("options", [])
        if not isinstance(options, list):
            return None
        
        for option in options:
            if isinstance(option, dict):
                name = option.get("name", "")
                value = option.get("value", "")
                
                # Try "Вес с упаковкой (кг)" first
                if name == "Вес с упаковкой (кг)":
                    weight = self._extract_numeric_value(str(value), "кг")
                    if weight is not None:
                        logger.debug(
                            "package_weight_extracted",
                            weight_kg=weight,
                            raw_value=value,
                            field="Вес с упаковкой (кг)"
                        )
                        return weight
                
                # Try "Вес товара с упаковкой (г)" - convert grams to kg
                if name == "Вес товара с упаковкой (г)":
                    weight_grams = self._extract_numeric_value(str(value), "г")
                    if weight_grams is not None:
                        weight_kg = weight_grams / 1000.0
                        logger.debug(
                            "package_weight_extracted",
                            weight_kg=weight_kg,
                            weight_grams=weight_grams,
                            raw_value=value,
                            field="Вес товара с упаковкой (г)"
                        )
                        return weight_kg
        
        logger.warning("package_weight_not_found", card_data_keys=list(card_data.keys()))
        return None

    def get_package_dimensions(self, card_data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """
        Extract package dimensions in cm from card data.
        
        Args:
            card_data: Product card data from basket API
            
        Returns:
            Dictionary with length, width, height in cm, or None if not found
        """
        # Try to get options from different possible locations
        options = card_data.get("options", [])
        
        # If not found at root level, try card_data.data.options
        if not isinstance(options, list) and "data" in card_data:
            data_section = card_data.get("data")
            if isinstance(data_section, dict):
                options = data_section.get("options", [])
        
        # Log structure for debugging
        logger.info(
            "get_package_dimensions_debug",
            has_options_root="options" in card_data,
            has_data="data" in card_data,
            data_has_options="data" in card_data and isinstance(card_data.get("data"), dict) and "options" in card_data.get("data", {}),
            options_type=type(options).__name__ if options else "None",
            options_count=len(options) if isinstance(options, list) else 0,
            card_data_keys=list(card_data.keys())[:20] if card_data else []
        )
        
        if not isinstance(options, list):
            logger.warning(
                "options_not_found_or_not_list",
                options_type=type(options).__name__ if options else "None",
                card_data_structure_keys=list(card_data.keys())[:20] if card_data else []
            )
            return None
        
        dimensions = {}
        all_option_names = []  # For logging
        
        for option in options:
            if isinstance(option, dict):
                name = option.get("name", "")
                value = option.get("value", "")
                all_option_names.append(name)
                
                # Try exact match first
                if name == "Длина упаковки":
                    length = self._extract_numeric_value(str(value), "см")
                    if length is not None:
                        dimensions["length"] = length
                        logger.debug("found_length", name=name, value=value, length=length)
                elif name == "Ширина упаковки":
                    width = self._extract_numeric_value(str(value), "см")
                    if width is not None:
                        dimensions["width"] = width
                        logger.debug("found_width", name=name, value=value, width=width)
                elif name == "Высота упаковки":
                    height = self._extract_numeric_value(str(value), "см")
                    if height is not None:
                        dimensions["height"] = height
                        logger.debug("found_height", name=name, value=value, height=height)
                # Try partial matches (case-insensitive)
                elif "длина" in name.lower() and "упаковк" in name.lower():
                    length = self._extract_numeric_value(str(value), "см")
                    if length is not None:
                        dimensions["length"] = length
                        logger.info("found_length_partial_match", name=name, value=value, length=length)
                elif "ширина" in name.lower() and "упаковк" in name.lower():
                    width = self._extract_numeric_value(str(value), "см")
                    if width is not None:
                        dimensions["width"] = width
                        logger.info("found_width_partial_match", name=name, value=value, width=width)
                elif "высота" in name.lower() and "упаковк" in name.lower():
                    height = self._extract_numeric_value(str(value), "см")
                    if height is not None:
                        dimensions["height"] = height
                        logger.info("found_height_partial_match", name=name, value=value, height=height)
        
        # Log all option names for debugging
        logger.info(
            "package_dimensions_search_result",
            all_option_names=all_option_names,
            found_dimensions=list(dimensions.keys()),
            dimensions=dimensions
        )
        
        if len(dimensions) == 3:
            logger.info(
                "package_dimensions_extracted",
                dimensions=dimensions
            )
            return dimensions
        
        logger.warning(
            "package_dimensions_incomplete",
            found_keys=list(dimensions.keys()),
            all_option_names=all_option_names,
            options_count=len(options)
        )
        return None

    def calculate_package_volume(self, card_data: Dict[str, Any]) -> Optional[float]:
        """
        Calculate package volume in liters from dimensions.
        
        Args:
            card_data: Product card data from basket API
            
        Returns:
            Volume in liters or None if dimensions not found
        """
        dimensions = self.get_package_dimensions(card_data)
        if not dimensions:
            return None
        
        length = dimensions.get("length")
        width = dimensions.get("width")
        height = dimensions.get("height")
        
        if length and width and height:
            # Calculate volume in cm³, then convert to liters (1 liter = 1000 cm³)
            volume_cm3 = length * width * height
            volume_liters = volume_cm3 / 1000.0
            
            logger.debug(
                "package_volume_calculated",
                length_cm=length,
                width_cm=width,
                height_cm=height,
                volume_liters=volume_liters
            )
            return volume_liters
        
        return None

