"""
Тесты для модуля wb_card
"""
import pytest
from wb_card import extract_nmid, InvalidInputError


def test_extract_nmid_from_standard_url():
    """Тест извлечения nmId из стандартного URL"""
    url = "https://www.wildberries.ru/catalog/12345678/detail.aspx"
    assert extract_nmid(url) == 12345678


def test_extract_nmid_from_url_with_query():
    """Тест извлечения nmId из URL с query параметрами"""
    url = "https://www.wildberries.ru/catalog/12345678/detail.aspx?targetUrl=ABC"
    assert extract_nmid(url) == 12345678


def test_extract_nmid_from_number():
    """Тест извлечения nmId из чистого числа"""
    assert extract_nmid("12345678") == 12345678
    assert extract_nmid("987654321") == 987654321


def test_extract_nmid_from_number_with_spaces():
    """Тест извлечения nmId из числа с пробелами"""
    assert extract_nmid("  12345678  ") == 12345678


def test_extract_nmid_invalid_input():
    """Тест обработки невалидного входного значения"""
    with pytest.raises(InvalidInputError):
        extract_nmid("invalid")
    
    with pytest.raises(InvalidInputError):
        extract_nmid("https://example.com")
    
    with pytest.raises(InvalidInputError):
        extract_nmid("")
    
    with pytest.raises(InvalidInputError):
        extract_nmid("abc123")


def test_extract_nmid_from_different_url_formats():
    """Тест различных форматов URL"""
    # Стандартный формат
    assert extract_nmid("https://www.wildberries.ru/catalog/55555555/detail.aspx") == 55555555
    
    # С протоколом http
    assert extract_nmid("http://www.wildberries.ru/catalog/66666666/detail.aspx") == 66666666
    
    # С дополнительными путями
    url = "https://www.wildberries.ru/catalog/77777777/detail.aspx?targetUrl=MS&size=XL"
    assert extract_nmid(url) == 77777777

