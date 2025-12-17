from __future__ import annotations

import re
from typing import Dict, Any


def parse_free_text(text: str) -> Dict[str, Any]:
    """Very simple heuristic parser for country, quantity, uom, price.
    Not critical for MVP; improves slot-filling UX.
    """
    country = None
    quantity = None
    uom = None
    price = None

    # price like 25$ or 25 usd
    m = re.search(r"(\d+[\.,]?\d*)\s*(\$|usd)", text, re.IGNORECASE)
    if m:
        price = float(m.group(1).replace(",", "."))

    # quantity like 100 шт/пар/кг
    m = re.search(r"(\d+[\.,]?\d*)\s*(шт|пар|кг|pcs|pairs|kg)", text, re.IGNORECASE)
    if m:
        quantity = float(m.group(1).replace(",", "."))
        uom = m.group(2).lower()

    # naive country pick (one capitalized token)
    m = re.search(r"\b(Китай|Вьетнам|Россия|Беларусь|Germany|China|Vietnam)\b", text, re.IGNORECASE)
    if m:
        country = m.group(1)

    return {
        "country_origin": country,
        "quantity": quantity,
        "uom": uom,
        "price": price,
    }


