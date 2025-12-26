"""Test script for basket range fallback method."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from apps.bot_service.services.wb_parser import WBParserService

def test_basket_range_fallback():
    """Test _calculate_basket_number_by_ranges method."""
    parser = WBParserService()
    
    test_cases = [
        (0, 1),
        (143, 1),
        (144, 2),
        (287, 2),
        (288, 3),
        (431, 3),
        (719, 4),
        (1007, 5),
        (1061, 6),
        (1115, 7),
        (1169, 8),
        (1313, 9),
        (1601, 10),
        (1655, 11),
        (1919, 12),
        (2045, 13),
        (2189, 14),
        (2405, 15),
        (2621, 16),
        (2837, 17),
        (3053, 18),
        (3269, 19),
        (3485, 20),
        (3701, 21),
        (3917, 22),
        (4133, 23),
        (4349, 24),
        (4565, 25),
        (4877, 26),
        (5189, 27),
        (5501, 28),
        (5813, 29),
        (6125, 30),
        (6437, 31),
        (6749, 32),
        (7061, 33),
        (7373, 34),
        (7685, 35),
        (7997, 36),
        (8309, 37),
        (8310, 38),
        (10000, 38),
    ]
    
    print("Testing _calculate_basket_number_by_ranges method:")
    print("=" * 80)
    
    all_passed = True
    for vol, expected_basket in test_cases:
        result = parser._calculate_basket_number_by_ranges(vol)
        status = "OK" if result == expected_basket else "FAIL"
        if result != expected_basket:
            all_passed = False
        
        print(f"{status} vol={vol:5d} -> basket={result:2d} (expected {expected_basket:2d})")
    
    print("=" * 80)
    if all_passed:
        print("OK All tests passed!")
    else:
        print("FAIL Some tests failed!")
    
    # Test with real article IDs
    print("\nTesting with real article IDs:")
    print("=" * 80)
    
    real_articles = [
        234577722,  # From JSON workflow
        458510242,
        256029996,
        218418267,
    ]
    
    for article_id in real_articles:
        article_str = str(article_id)
        if len(article_str) >= 9:
            vol = int(article_str[:4])
        elif len(article_str) >= 8:
            vol = int(article_str[:3])
        else:
            vol = int(article_str[:3]) if len(article_str) >= 3 else int(article_str)
        
        main_basket = parser._calculate_basket_number(vol)
        range_basket = parser._calculate_basket_number_by_ranges(vol)
        
        print(f"Article: {article_id}, vol={vol}, main={main_basket}, range={range_basket}")
    
    return all_passed

if __name__ == "__main__":
    success = test_basket_range_fallback()
    sys.exit(0 if success else 1)

