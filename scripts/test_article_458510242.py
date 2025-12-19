import asyncio
import aiohttp
import json

async def test():
    article_id = 458510242
    article_str = str(article_id)
    vol = article_str[:4]
    part = article_str[:6]
    url = f"https://basket-33.wbbasket.ru/vol{vol}/part{part}/{article_id}/info/ru/card.json"
    
    print(f"Testing article: {article_id}")
    print(f"URL: {url}")
    print()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.wildberries.ru/",
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            print(f"Status: {response.status}")
            print(f"Headers: {dict(response.headers)}")
            
            if response.status == 200:
                data = await response.json()
                print(f"SUCCESS! Keys: {list(data.keys())[:10]}")
            elif response.status == 404:
                text = await response.text()
                print(f"404 - Not Found")
                print(f"Response: {text[:200]}")
            else:
                text = await response.text()
                print(f"Error response: {text[:500]}")

asyncio.run(test())


