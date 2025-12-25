"""Find the exact basket formula."""
examples = [
    {"article": 458510242, "vol": 4585, "basket": 26},
    {"article": 256029996, "vol": 2560, "basket": 16},
    {"article": 218418267, "vol": 2184, "basket": 14},
    {"article": 260289070, "vol": 2602, "basket": 16},
    {"article": 317397163, "vol": 3173, "basket": 19},
    {"article": 689623448, "vol": 6896, "basket": 33},
]

print("Testing vol // 175:")
print("=" * 80)
for ex in examples:
    result = ex["vol"] // 175
    diff = abs(result - ex["basket"])
    status = "✓" if diff == 0 else " " if diff <= 2 else "✗"
    print(f"{status} vol={ex['vol']}: {ex['vol']} // 175 = {result}, basket={ex['basket']}, diff={diff}")

print("\n" + "=" * 80)
print("Testing vol // 200:")
print("-" * 80)
for ex in examples:
    result = ex["vol"] // 200
    diff = abs(result - ex["basket"])
    status = "✓" if diff == 0 else " " if diff <= 2 else "✗"
    print(f"{status} vol={ex['vol']}: {ex['vol']} // 200 = {result}, basket={ex['basket']}, diff={diff}")

print("\n" + "=" * 80)
print("Testing vol // 180:")
print("-" * 80)
for ex in examples:
    result = ex["vol"] // 180
    diff = abs(result - ex["basket"])
    status = "✓" if diff == 0 else " " if diff <= 2 else "✗"
    print(f"{status} vol={ex['vol']}: {ex['vol']} // 180 = {result}, basket={ex['basket']}, diff={diff}")

print("\n" + "=" * 80)
print("Trying: basket = vol // X where X varies by vol range")
print("-" * 80)

# Maybe it's vol // 175 for some, vol // 200 for others?
# Or maybe it's approximately vol // 175 with adjustments?

# Check if there's a pattern: maybe it's vol // (175 + adjustment)
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    # If vol // X = basket, then X ≈ vol / basket
    exact_divisor = vol / basket
    print(f"  vol={vol}, basket={basket}: exact divisor = {vol} / {basket} = {exact_divisor:.2f}")

print("\n" + "=" * 80)
print("Maybe it's: vol // (vol / basket) rounded?")
print("-" * 80)

# Try: basket = vol // round(vol / basket) - but that's circular
# Instead, let's see if there's a simple formula

# Maybe it's just: vol // 175 for vol < 3000, vol // 200 for vol >= 3000?
print("\nTrying: vol < 3000: vol // 175, vol >= 3000: vol // 200")
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 3000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: result={result}, expected={basket}")

# Or maybe: vol // 175 for vol < 4000, vol // 200 for vol >= 4000?
print("\nTrying: vol < 4000: vol // 175, vol >= 4000: vol // 200")
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 4000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: result={result}, expected={basket}")

# Or maybe: vol // 175 for vol < 5000, vol // 200 for vol >= 5000?
print("\nTrying: vol < 5000: vol // 175, vol >= 5000: vol // 200")
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 5000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: result={result}, expected={basket}")

# Or maybe it's: vol // 175 for all, but with special case for 6896?
print("\nTrying: vol // 175 for all (special case for 6896: vol // 200)")
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol == 6896:
        result = vol // 200
    else:
        result = vol // 175
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: result={result}, expected={basket}")

# Wait, let me check: maybe it's vol // 175 for vol < 7000, vol // 200 for vol >= 7000?
print("\nTrying: vol < 7000: vol // 175, vol >= 7000: vol // 200")
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    if vol < 7000:
        result = vol // 175
    else:
        result = vol // 200
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: result={result}, expected={basket}")






