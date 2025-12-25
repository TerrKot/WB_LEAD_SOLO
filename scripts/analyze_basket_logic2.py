"""Analyze basket number logic - advanced."""
examples = [
    {"article": 458510242, "vol": 4585, "part": 458510, "basket": 26},
    {"article": 256029996, "vol": 2560, "part": 256029, "basket": 16},
    {"article": 218418267, "vol": 2184, "part": 218418, "basket": 14},
    {"article": 260289070, "vol": 2602, "part": 260289, "basket": 16},
    {"article": 317397163, "vol": 3173, "part": 317397, "basket": 19},
    {"article": 689623448, "vol": 6896, "part": 689623, "basket": 33},
]

print("Trying different formulas:")
print("=" * 80)

# Try vol // X with different X values
for x in range(100, 300, 1):
    matches = 0
    for ex in examples:
        if (ex["vol"] // x) == ex["basket"]:
            matches += 1
    
    if matches >= 2:  # At least 2 matches
        print(f"\nvol // {x}: {matches}/{len(examples)} matches")
        for ex in examples:
            result = ex["vol"] // x
            status = "✓" if result == ex["basket"] else " "
            print(f"  {status} vol={ex['vol']}: {ex['vol']} // {x} = {result} (expected {ex['basket']})")

print("\n" + "=" * 80)
print("Trying ranges-based approach:")
print("-" * 80)

# Sort by vol
sorted_examples = sorted(examples, key=lambda x: x["vol"])

print("\nSorted by vol:")
for ex in sorted_examples:
    print(f"  vol={ex['vol']}, basket={ex['basket']}")

# Try to find if basket depends on vol ranges
print("\nChecking if basket = vol // range_size:")
for range_size in [150, 160, 170, 175, 180, 190, 200, 210, 220]:
    all_match = True
    for ex in examples:
        result = ex["vol"] // range_size
        if result != ex["basket"]:
            all_match = False
            break
    
    if all_match:
        print(f"  ✓ FOUND: vol // {range_size} matches all!")
        break
    else:
        # Count matches
        matches = sum(1 for ex in examples if (ex["vol"] // range_size) == ex["basket"])
        if matches >= 2:
            print(f"  ~ vol // {range_size}: {matches}/{len(examples)} matches")

print("\n" + "=" * 80)
print("Trying formula: (vol - offset) // step")
print("-" * 80)

# Try different offsets and steps
for offset in [0, 100, 200, 300, 400, 500, 1000]:
    for step in [150, 160, 170, 175, 180, 190, 200]:
        matches = 0
        for ex in examples:
            result = (ex["vol"] - offset) // step
            if result == ex["basket"]:
                matches += 1
        
        if matches >= 3:
            print(f"\n(vol - {offset}) // {step}: {matches}/{len(examples)} matches")
            for ex in examples:
                result = (ex["vol"] - offset) // step
                status = "✓" if result == ex["basket"] else " "
                print(f"  {status} vol={ex['vol']}: ({ex['vol']} - {offset}) // {step} = {result} (expected {ex['basket']})")

print("\n" + "=" * 80)
print("Trying: vol // (some formula based on vol itself)")
print("-" * 80)

# Maybe it's vol // (vol // basket) or similar?
for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    # If vol // X = basket, then X = vol // basket
    divisor = vol // basket
    print(f"  vol={vol}, basket={basket}: divisor would be {vol} // {basket} = {divisor}")

# Check if there's a pattern in divisors
print("\nDivisors:")
divisors = [ex["vol"] // ex["basket"] for ex in examples]
print(f"  {divisors}")
print(f"  Min: {min(divisors)}, Max: {max(divisors)}, Avg: {sum(divisors)/len(divisors):.1f}")

# Maybe it's approximately vol // 175 or vol // 200?
print("\n" + "=" * 80)
print("Final check: vol // 175 and vol // 200")
print("-" * 80)

for ex in examples:
    result175 = ex["vol"] // 175
    result200 = ex["vol"] // 200
    diff175 = abs(result175 - ex["basket"])
    diff200 = abs(result200 - ex["basket"])
    
    print(f"  vol={ex['vol']}, basket={ex['basket']}:")
    print(f"    vol // 175 = {result175} (diff: {diff175})")
    print(f"    vol // 200 = {result200} (diff: {diff200})")
    
    # Maybe it's between these two?
    if result175 <= ex["basket"] <= result200 or result200 <= ex["basket"] <= result175:
        print(f"    → basket is between {result175} and {result200}")






