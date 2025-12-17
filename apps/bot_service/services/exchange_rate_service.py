"""Service for fetching exchange rates from Central Bank of Russia API."""
import aiohttp
import asyncio
from typing import Dict, Optional
import structlog
from datetime import datetime, timedelta

logger = structlog.get_logger()


class ExchangeRateService:
    """Service for fetching and caching exchange rates from CBR API."""
    
    # CBR API endpoint (JSON format)
    CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
    
    # Margins to add to CB rates
    MARGIN_WHITE = 1.02  # +2% for white logistics
    MARGIN_CARGO = 1.04  # +4% for cargo
    
    def __init__(self):
        """Initialize exchange rate service."""
        self._cache_cb: Optional[Dict[str, float]] = None  # Cache for CB rates (without margin)
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(hours=1)  # Cache for 1 hour
        
    async def get_rates_for_white(self) -> Dict[str, float]:
        """
        Get exchange rates for white logistics (CB rate + 2%).
        
        Returns:
            Dictionary with keys: usd_rub, eur_rub, usd_cny
        """
        cb_rates = await self._get_cb_rates()
        return {
            "usd_rub": round(cb_rates["usd_rub"] * self.MARGIN_WHITE, 2),
            "eur_rub": round(cb_rates["eur_rub"] * self.MARGIN_WHITE, 2),
            "usd_cny": cb_rates["usd_cny"]  # CNY rate doesn't need margin
        }
    
    async def get_rates_for_cargo(self) -> Dict[str, float]:
        """
        Get exchange rates for cargo (CB rate + 4%).
        
        Returns:
            Dictionary with keys: usd_rub, usd_cny
        """
        cb_rates = await self._get_cb_rates()
        return {
            "usd_rub": round(cb_rates["usd_rub"] * self.MARGIN_CARGO, 2),
            "usd_cny": cb_rates["usd_cny"]  # CNY rate doesn't need margin
        }
    
    async def get_all_rates(self) -> Dict[str, float]:
        """
        Get all exchange rates (for white logistics by default, CB + 2%).
        
        Returns:
            Dictionary with keys: usd_rub, eur_rub, usd_cny
        """
        return await self.get_rates_for_white()
    
    async def _get_cb_rates(self) -> Dict[str, float]:
        """
        Get Central Bank exchange rates from cache or fetch from API.
        
        Returns:
            Dictionary with CB rates (without margin): usd_rub, eur_rub, usd_cny
        """
        # Check cache
        if self._cache_cb and self._cache_timestamp:
            if datetime.now() - self._cache_timestamp < self._cache_ttl:
                logger.debug("exchange_rates_cb_from_cache")
                return self._cache_cb
        
        # Fetch from API
        try:
            cb_rates = await self._fetch_from_api()
            self._cache_cb = cb_rates
            self._cache_timestamp = datetime.now()
            logger.info("exchange_rates_cb_fetched", rates=cb_rates)
            return cb_rates
        except Exception as e:
            logger.error("exchange_rates_fetch_failed", error=str(e))
            # Return cached rates if available, or fallback
            if self._cache_cb:
                logger.warning("using_cached_cb_rates_on_error")
                return self._cache_cb
            # Fallback rates (CB rates without margin)
            return {
                "usd_rub": 100.0,
                "eur_rub": 110.0,
                "usd_cny": 7.2
            }
    
    async def _fetch_from_api(self) -> Dict[str, float]:
        """
        Fetch exchange rates from CBR API (without margin).
        
        Returns:
            Dictionary with CB rates (without margin): usd_rub, eur_rub, usd_cny
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.CBR_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    # API returns JavaScript file, but it's valid JSON
                    # Use text() first, then parse as JSON
                    text = await response.text()
                    import json
                    data = json.loads(text)
                
                # Extract rates from CBR API response
                # Format: {"Valute": {"USD": {"Value": 98.5}, "EUR": {"Value": 107.2}, ...}}
                valutes = data.get("Valute", {})
                
                # Get USD rate (CB rate without margin)
                usd_value = valutes.get("USD", {}).get("Value", 100.0)
                # Get EUR rate (CB rate without margin)
                eur_value = valutes.get("EUR", {}).get("Value", 110.0)
                
                usd_rub_cb = float(usd_value)
                eur_rub_cb = float(eur_value)
                
                # For USD/CNY, we need to calculate or use a fixed rate
                # CBR doesn't provide CNY directly, so we'll use a reasonable estimate
                # or calculate from other rates if available
                # For now, using a fixed rate (can be improved later)
                usd_cny = 7.2  # This could be fetched from another API if needed
                
                logger.info(
                    "exchange_rates_cb_parsed",
                    usd_rub_cb=usd_rub_cb,
                    eur_rub_cb=eur_rub_cb,
                    usd_cny=usd_cny
                )
                
                return {
                    "usd_rub": usd_rub_cb,
                    "eur_rub": eur_rub_cb,
                    "usd_cny": usd_cny
                }
        except asyncio.TimeoutError:
            logger.error("exchange_rates_api_timeout", url=self.CBR_API_URL)
            # Return fallback rates if API timeout
            return {
                "usd_rub": 100.0,
                "eur_rub": 110.0,
                "usd_cny": 7.2
            }
        except Exception as e:
            logger.error("exchange_rates_api_error", url=self.CBR_API_URL, error=str(e))
            # Return fallback rates if API error
            return {
                "usd_rub": 100.0,
                "eur_rub": 110.0,
                "usd_cny": 7.2
            }
