"""Final attempt to find basket formula."""
examples = [
    {"article": 458510242, "vol": 4585, "basket": 26},
    {"article": 256029996, "vol": 2560, "basket": 16},
    {"article": 218418267, "vol": 2184, "basket": 14},
    {"article": 260289070, "vol": 2602, "basket": 16},
    {"article": 317397163, "vol": 3173, "basket": 19},
    {"article": 689623448, "vol": 6896, "basket": 33},
]

print("Testing different range-based formulas:")
print("=" * 80)

# Formula 1: vol // 160 for vol < 3000, vol // 175 for 3000-5000, vol // 200 for >= 5000
print("\nFormula 1: vol < 3000: // 160, 3000-5000: // 175, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 160
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 1! ***")
    print("basket = vol // 160 if vol < 3000 else vol // 175 if vol < 5000 else vol // 200")

# Formula 2: Try with 150 instead of 160
print("\n" + "=" * 80)
print("Formula 2: vol < 3000: // 150, 3000-5000: // 175, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 150
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 2! ***")

# Formula 3: Try with different thresholds
print("\n" + "=" * 80)
print("Formula 3: vol < 2500: // 150, 2500-4500: // 175, >= 4500: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 2500:
        result = vol // 150
    elif vol < 4500:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 3! ***")

# Formula 4: Try with 155 for small vol
print("\n" + "=" * 80)
print("Formula 4: vol < 3000: // 155, 3000-5000: // 175, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 155
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 4! ***")

# Formula 5: Try with 162 for small vol (average of 160 and 164)
print("\n" + "=" * 80)
print("Formula 5: vol < 3000: // 162, 3000-5000: // 175, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 162
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 5! ***")

# Formula 6: Maybe it's simpler - just vol // 160 for all < 5000, vol // 200 for >= 5000?
print("\n" + "=" * 80)
print("Formula 6: vol < 5000: // 160, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 5000:
        result = vol // 160
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 6! ***")

# Formula 7: Try vol // 160 for < 3000, vol // 175 for 3000-7000, vol // 200 for >= 7000
print("\n" + "=" * 80)
print("Formula 7: vol < 3000: // 160, 3000-7000: // 175, >= 7000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 160
    elif vol < 7000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** FOUND FORMULA 7! ***")




