"""Find perfect formula."""
examples = [
    {"article": 458510242, "vol": 4585, "basket": 26},
    {"article": 256029996, "vol": 2560, "basket": 16},
    {"article": 218418267, "vol": 2184, "basket": 14},
    {"article": 260289070, "vol": 2602, "basket": 16},
    {"article": 317397163, "vol": 3173, "basket": 19},
    {"article": 689623448, "vol": 6896, "basket": 33},
]

print("Testing: basket = (vol // 175) + adjustment")
print("=" * 80)

# Try with more precise adjustments
for ex in examples:
    vol = ex["vol"]
    base = vol // 175
    basket = ex["basket"]
    
    # Determine adjustment more precisely
    if vol < 3000:
        adjustment = 2
    elif vol < 3200:  # Special case for 3173
        adjustment = 1
    elif vol < 5000:
        adjustment = 0
    elif vol < 7000:  # Special case for 6896
        adjustment = -6
    else:
        adjustment = -6
    
    result = base + adjustment
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: ({vol} // 175) + {adjustment} = {result}, expected={basket}")

print("\n" + "=" * 80)
print("Better approach: Use different divisors for different ranges")
print("-" * 80)

# Formula: vol < 3000: // 160, 3000-3200: // 167, 3200-5000: // 175, >= 5000: // 200
print("\nFormula: vol < 3000: // 160, 3000-3200: // 167, 3200-5000: // 175, >= 5000: // 200")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 160
    elif vol < 3200:
        result = vol // 167
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** PERFECT FORMULA FOUND! ***")
    print("basket = vol // 160 if vol < 3000 else vol // 167 if vol < 3200 else vol // 175 if vol < 5000 else vol // 200")

# But wait, let me check if 6896 // 200 = 34, not 33. So maybe it's vol // 209 for >= 5000?
print("\n" + "=" * 80)
print("Checking 6896: 6896 // 200 = 34, but need 33")
print("6896 // 209 =", 6896 // 209)
print("6896 // 208 =", 6896 // 208)

# So maybe: vol >= 5000: // 209?
print("\nFormula: vol < 3000: // 160, 3000-3200: // 167, 3200-5000: // 175, >= 5000: // 209")
all_match = True
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 160
    elif vol < 3200:
        result = vol // 167
    elif vol < 5000:
        result = vol // 175
    else:
        result = vol // 209
    status = "✓" if result == basket else "✗"
    print(f"{status} vol={vol}: result={result}, expected={basket}")
    if result != basket:
        all_match = False

if all_match:
    print("\n*** PERFECT FORMULA FOUND! ***")
    print("basket = vol // 160 if vol < 3000 else vol // 167 if vol < 3200 else vol // 175 if vol < 5000 else vol // 209")


