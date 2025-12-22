import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService

async def test():
    wb = WBParserService()
    article_id = 458510242
    
    print(f"Testing article {article_id}...")
    print(f"URL will be: {wb._build_card_url(article_id)}")
    print()
    
    card_data = await wb.fetch_product_card_data(article_id)
    
    if card_data:
        print("SUCCESS: card_data received")
        print(f"imt_name: {card_data.get('imt_name', 'N/A')}")
        print(f"subj_name: {card_data.get('subj_name', 'N/A')}")
        
        weight = wb.get_package_weight(card_data)
        print(f"Package weight: {weight} kg" if weight else "Package weight: NOT FOUND")
        
        dims = wb.get_package_dimensions(card_data)
        if dims:
            print(f"Dimensions: {dims}")
            volume = wb.calculate_package_volume(card_data)
            print(f"Volume: {volume} liters" if volume else "Volume: NOT CALCULATED")
        else:
            print("Dimensions: NOT FOUND")
    else:
        print("FAILED: Could not get card_data")

asyncio.run(test())




