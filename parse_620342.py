import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup


async def check(code: str):
    url = f"https://www.ifcg.ru/kb/tnved/{code}/"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    duty_row = soup.find("td", string=re.compile(r"Импортная пошлина", re.I))
    tr = duty_row.find_parent("tr") if duty_row else None
    tds = tr.find_all("td") if tr else []
    full_row_text = " ".join([td.get_text(strip=True) for td in tds]) if tds else ""
    duty_value = tds[1].get_text(strip=True) if len(tds) >= 2 else ""
    minimum_match = re.search(
        r"(?:но\s+)?не\s+менее\s+([\d,\.]+)\s*(?:Евро|EUR|€)\s*/?\s*(?:кг|kg)",
        full_row_text,
        re.I,
    )
    percent_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", full_row_text, re.I)
    euro_match = (
        re.search(r"([\d,\.]+)", duty_value.replace(",", "."))
        if ("Евро" in duty_value or "EUR" in duty_value or "€" in duty_value)
        and "/" in duty_value
        else None
    )
    duty_type = None
    duty_rate = 0.0
    duty_minimum = None
    if minimum_match:
        duty_minimum = float(minimum_match.group(1).replace(",", "."))
    if percent_match:
        duty_type = "ad_valorem"
        duty_rate = float(percent_match.group(1).replace(",", "."))
    elif euro_match:
        duty_rate = float(euro_match.group(1))
        if re.search(r"/кг|/kg", duty_value, re.I):
            duty_type = "по весу"
        elif re.search(r"/пар|/pair", duty_value, re.I):
            duty_type = "по паре"
        elif re.search(r"/шт|/unit|/pc|/piece", duty_value, re.I):
            duty_type = "по единице"
        else:
            duty_type = "по единице"
    print("Строка:", duty_value)
    print("Полный текст:", full_row_text)
    print("Тип:", duty_type, "Ставка:", duty_rate)
    print("Минимум:", duty_minimum)


if __name__ == "__main__":
    asyncio.run(check("6203423100"))

