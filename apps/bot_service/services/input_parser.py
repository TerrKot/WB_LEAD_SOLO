"""Input parser service for extracting article IDs from URLs or text."""
import re
from typing import Optional, List
from urllib.parse import urlparse, parse_qs
import structlog

logger = structlog.get_logger()


class InputParser:
    """Parser for extracting article IDs from WB URLs or text."""

    @staticmethod
    def detect_marketplace_type(url: str) -> Optional[str]:
        """
        Detect marketplace type from URL.
        
        Args:
            url: Product URL
            
        Returns:
            'wildberries', 'ozon', 'yandex' or None if unknown
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.netloc.lower()
            
            # Wildberries domains
            if any(domain in hostname for domain in ['wildberries.ru', 'wildberries.by', 'wildberries.kz', 'wb.ru', 'wb.by', 'wb.kz']):
                return 'wildberries'
            
            # Ozon domains
            if any(domain in hostname for domain in ['ozon.ru', 'ozon.by', 'ozon.kz', 'ozon.com']):
                return 'ozon'
            
            # Yandex Market domains
            if any(domain in hostname for domain in ['market.yandex.ru', 'market.yandex.by', 'market.yandex.kz', 'yandex.ru/market']):
                return 'yandex'
            
            return None
            
        except Exception as e:
            logger.error("marketplace_detection_error", url=url, error=str(e))
            return None

    @staticmethod
    def extract_article_from_url(url: str) -> Optional[int]:
        """
        Extract article ID from WB URL.

        Args:
            url: WB product URL

        Returns:
            Article ID (nmId) or None if not found

        Examples:
            - https://www.wildberries.ru/catalog/154345562/detail.aspx -> 154345562
            - https://wb.ru/catalog/123456/detail.aspx -> 123456
            - https://u-card.wb.ru/cards/v4/list?nm=154345562 -> 154345562
        """
        try:
            parsed = urlparse(url)
            
            # Check query parameter 'nm' (for API URLs)
            if parsed.query:
                params = parse_qs(parsed.query)
                if 'nm' in params:
                    nm_param = params['nm'][0]
                    # Extract first article from semicolon-separated list
                    articles = [int(x.strip()) for x in nm_param.split(';') if x.strip().isdigit()]
                    if articles:
                        return articles[0]
            
            # Check path for /catalog/{article_id}/ pattern
            path_match = re.search(r'/catalog/(\d+)/', parsed.path)
            if path_match:
                article_id = int(path_match.group(1))
                return article_id
            
            logger.warning("article_not_found_in_url", url=url)
            return None
            
        except Exception as e:
            logger.error("url_parsing_error", url=url, error=str(e))
            return None

    @staticmethod
    def extract_article_from_text(text: str) -> Optional[int]:
        """
        Extract article ID from text (can be plain number or URL).

        Args:
            text: Text input from user

        Returns:
            Article ID (nmId) or None if not found
        """
        # Remove whitespace
        text = text.strip()
        
        # If it's a URL, use URL parser
        if text.startswith("http://") or text.startswith("https://"):
            return InputParser.extract_article_from_url(text)
        
        # Try to extract as plain number
        # Match digits that look like article IDs (usually 6-10 digits)
        # WB article IDs can be 6-10 digits
        match = re.search(r'\b(\d{6,10})\b', text)
        if match:
            try:
                article_id = int(match.group(1))
                logger.debug("article_extracted_from_text", article_id=article_id, text=text[:50])
                return article_id
            except ValueError:
                pass
        
        logger.warning("article_not_found_in_text", text=text[:100], text_length=len(text))
        return None

    @staticmethod
    def extract_articles_from_url(url: str) -> List[int]:
        """
        Extract all article IDs from URL (for batch processing).

        Args:
            url: WB URL with article IDs

        Returns:
            List of article IDs
        """
        try:
            parsed = urlparse(url)
            
            # Check query parameter 'nm' (for API URLs)
            if parsed.query:
                params = parse_qs(parsed.query)
                if 'nm' in params:
                    nm_param = params['nm'][0]
                    articles = [int(x.strip()) for x in nm_param.split(';') if x.strip().isdigit()]
                    if articles:
                        return articles
            
            # Check path for /catalog/{article_id}/ pattern
            path_match = re.search(r'/catalog/(\d+)/', parsed.path)
            if path_match:
                article_id = int(path_match.group(1))
                return [article_id]
            
            return []
            
        except Exception as e:
            logger.error("url_parsing_error", url=url, error=str(e))
            return []

