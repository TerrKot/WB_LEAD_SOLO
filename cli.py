"""
CLI интерфейс для WB Card утилиты (интерактивный режим)
"""
import json
import sys

from wb_card import get_link, get_data, WBCardError, InvalidInputError, NotFoundError, NetworkError


def print_json(data: dict):
    """Печатает данные в формате JSON"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print()  # Пустая строка для разделения


def process_input(user_input: str, mode: str = 'auto'):
    """
    Обрабатывает введенные пользователем данные
    
    Args:
        user_input: Введенная строка (ссылка или артикул)
        mode: Режим работы ('auto', 'link', 'fetch')
    """
    user_input = user_input.strip()
    
    if not user_input:
        return
    
    # Команды выхода
    if user_input.lower() in ('exit', 'quit', 'q', 'выход'):
        print("Выход из программы...")
        sys.exit(0)
    
    # Команды помощи
    if user_input.lower() in ('help', 'h', 'помощь'):
        print_help()
        return
    
    try:
        if mode == 'link' or (mode == 'auto' and user_input.lower().startswith('link:')):
            # Режим генерации ссылки
            if user_input.lower().startswith('link:'):
                user_input = user_input[5:].strip()
            
            result = get_link(user_input)
            print("✓ Ссылка на JSON карточки:")
            print_json(result)
            
        elif mode == 'fetch' or (mode == 'auto' and user_input.lower().startswith('fetch:')):
            # Режим получения данных
            include_raw = False
            if user_input.lower().startswith('fetch:'):
                parts = user_input.split(':', 1)
                user_input = parts[1].strip() if len(parts) > 1 else ''
                if '--raw' in parts[0] or 'raw' in parts[0]:
                    include_raw = True
            
            print("Загрузка данных...")
            result = get_data(user_input, include_raw=include_raw)
            print("✓ Данные карточки товара:")
            print_json(result)
            
        else:
            # Автоматический режим - всегда получаем данные
            print("Загрузка данных...")
            result = get_data(user_input, include_raw=False)
            print("✓ Данные карточки товара:")
            print_json(result)
            
    except InvalidInputError as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        print("Проверьте правильность введенной ссылки или артикула.\n")
    except NotFoundError as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        print("Товар не найден. Проверьте правильность артикула.\n")
    except NetworkError as e:
        error_msg = str(e)
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        if "498" in error_msg or "антибот" in error_msg.lower():
            print("\n💡 Wildberries блокирует автоматические запросы (антибот защита).")
            print("   Попробуйте позже или проверьте товар вручную на сайте.\n")
        elif "403" in error_msg:
            print("\n💡 Доступ запрещен. Попробуйте позже.\n")
        else:
            print("Проблема с сетью. Попробуйте позже.\n")
    except WBCardError as e:
        print(f"❌ Ошибка: {e}", file=sys.stderr)
        print()
    except KeyboardInterrupt:
        print("\n\nПрервано пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}", file=sys.stderr)
        print()


def print_help():
    """Выводит справку"""
    print("""
Доступные команды:
  - Введите ссылку WB или артикул для получения данных о товаре
  - link:<ссылка или артикул> - только сгенерировать ссылку на JSON
  - fetch:<ссылка или артикул> - получить данные (по умолчанию)
  - help, h - показать эту справку
  - exit, quit, q - выйти из программы

Примеры:
  12345678
  https://www.wildberries.ru/catalog/12345678/detail.aspx
  link:12345678
  fetch:12345678
    """)


def main():
    """Главная функция интерактивного режима"""
    print("=" * 60)
    print("WB Card JSON Link Generator + Parser")
    print("=" * 60)
    print("\nВведите ссылку на товар WB или артикул (nmId)")
    print("Для справки введите 'help', для выхода - 'exit'\n")
    
    try:
        while True:
            try:
                user_input = input("WB > ").strip()
                if user_input:
                    process_input(user_input)
            except EOFError:
                # Ctrl+Z на Windows или Ctrl+D на Unix
                print("\n\nВыход из программы...")
                break
            except KeyboardInterrupt:
                # Ctrl+C
                print("\n\nВыход из программы...")
                break
                
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

