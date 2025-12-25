"""Find exact formula."""
examples = [
    {"article": 458510242, "vol": 4585, "basket": 26},
    {"article": 256029996, "vol": 2560, "basket": 16},
    {"article": 218418267, "vol": 2184, "basket": 14},
    {"article": 260289070, "vol": 2602, "basket": 16},
    {"article": 317397163, "vol": 3173, "basket": 19},
    {"article": 689623448, "vol": 6896, "basket": 33},
]

print("Exact divisors (vol / basket):")
print("=" * 80)
for ex in examples:
    exact = ex["vol"] / ex["basket"]
    print(f"  vol={ex['vol']}, basket={ex['basket']}: {ex['vol']} / {ex['basket']} = {exact:.2f}")

print("\n" + "=" * 80)
print("Maybe it's: basket = vol // round(vol / basket)?")
print("But that's circular...")

print("\n" + "=" * 80)
print("Trying: basket = vol // (some function of vol)")
print("-" * 80)

# Maybe it's: basket = vol // (175 + adjustment based on vol)?
# Or maybe: basket = round(vol / 175) with some rounding rules?

print("\nTesting: basket = round(vol / 175)")
for ex in examples:
    result = round(ex["vol"] / 175)
    status = "✓" if result == ex["basket"] else " "
    print(f"{status} vol={ex['vol']}: round({ex['vol']} / 175) = {result}, expected={ex['basket']}")

print("\nTesting: basket = round(vol / 160)")
for ex in examples:
    result = round(ex["vol"] / 160)
    status = "✓" if result == ex["basket"] else " "
    print(f"{status} vol={ex['vol']}: round({ex['vol']} / 160) = {result}, expected={ex['basket']}")

print("\nTesting: basket = round(vol / 180)")
for ex in examples:
    result = round(ex["vol"] / 180)
    status = "✓" if result == ex["basket"] else " "
    print(f"{status} vol={ex['vol']}: round({ex['vol']} / 180) = {result}, expected={ex['basket']}")

print("\n" + "=" * 80)
print("Maybe the formula is: basket = vol // divisor, where divisor = vol / basket")
print("But we need to find a pattern in divisors...")
print("-" * 80)

divisors = [ex["vol"] / ex["basket"] for ex in examples]
print(f"Divisors: {[f'{d:.2f}' for d in divisors]}")
print(f"Min: {min(divisors):.2f}, Max: {max(divisors):.2f}, Avg: {sum(divisors)/len(divisors):.2f}")

# Maybe it's approximately 175 for most, but varies?
# Let's see: can we approximate it as vol // 175 with adjustments?

print("\n" + "=" * 80)
print("FINAL ATTEMPT: Maybe it's simply vol // 175 for most, with special cases?")
print("-" * 80)

# Check if we can use vol // 175 and then adjust
for ex in examples:
    base = ex["vol"] // 175
    basket = ex["basket"]
    diff = basket - base
    print(f"  vol={ex['vol']}: base={base}, basket={basket}, diff={diff}")

# I see: for vol < 3000, diff is +2, for 3000-5000 diff is 0, for >= 5000 diff is -6
# So maybe: basket = (vol // 175) + adjustment

print("\n" + "=" * 80)
print("Trying: basket = (vol // 175) + adjustment")
print("-" * 80)

for ex in examples:
    vol = ex["vol"]
    base = vol // 175
    basket = ex["basket"]
    
    # Determine adjustment
    if vol < 3000:
        adjustment = 2
    elif vol < 5000:
        adjustment = 0
    else:
        adjustment = -6
    
    result = base + adjustment
    status = "✓" if result == basket else " "
    print(f"{status} vol={vol}: ({vol} // 175) + {adjustment} = {result}, expected={basket}")






