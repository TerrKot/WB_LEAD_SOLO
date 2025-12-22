import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService

async def test():
    wb = WBParserService()
    
    # Test with known article from example
    print("Testing article 689623448 (from example)...")
    data = await wb.fetch_product_card_data(689623448)
    
    if data:
        print("SUCCESS: card_data received")
        print(f"Keys: {list(data.keys())[:10]}")
        print(f"imt_name: {data.get('imt_name', 'N/A')}")
        print(f"subj_name: {data.get('subj_name', 'N/A')}")
        
        # Test weight extraction
        weight = wb.get_package_weight(data)
        print(f"Package weight: {weight} kg" if weight else "Package weight: NOT FOUND")
        
        # Test dimensions
        dims = wb.get_package_dimensions(data)
        if dims:
            print(f"Dimensions: {dims}")
            volume = wb.calculate_package_volume(data)
            print(f"Volume: {volume} liters" if volume else "Volume: NOT CALCULATED")
        else:
            print("Dimensions: NOT FOUND")
    else:
        print("FAILED: Could not get card_data")
    
    print("\nTesting article 458510242 (requested)...")
    data2 = await wb.fetch_product_card_data(458510242)
    print("SUCCESS" if data2 else "FAILED")

asyncio.run(test())




