"""Analyze basket number logic from examples."""
examples = [
    {"article": 458510242, "vol": 4585, "part": 458510, "basket": 26},
    {"article": 256029996, "vol": 2560, "part": 256029, "basket": 16},
    {"article": 218418267, "vol": 2184, "part": 218418, "basket": 14},
    {"article": 260289070, "vol": 2602, "part": 260289, "basket": 16},
    {"article": 317397163, "vol": 3173, "part": 317397, "basket": 19},
    {"article": 689623448, "vol": 6896, "part": 689623, "basket": 33},
]

print("Analyzing basket number logic:")
print("=" * 80)

for ex in examples:
    vol = ex["vol"]
    part = ex["part"]
    basket = ex["basket"]
    
    print(f"\nArticle: {ex['article']}, vol={vol}, part={part}, basket={basket}")
    print("-" * 80)
    
    # Try different formulas
    formulas = {
        "vol % 100": vol % 100,
        "vol // 100": vol // 100,
        "(vol // 100) % 100": (vol // 100) % 100,
        "vol % 1000": vol % 1000,
        "vol // 10": vol // 10,
        "vol // 10 % 100": (vol // 10) % 100,
        "part % 100": part % 100,
        "part // 100": part // 100,
        "(part // 100) % 100": (part // 100) % 100,
        "part // 1000": part // 1000,
        "part // 10000": part // 10000,
        "vol // 100 % 50": (vol // 100) % 50,
        "vol // 200": vol // 200,
        "vol // 200 % 50": (vol // 200) % 50,
        "vol // 150": vol // 150,
        "vol // 150 % 50": (vol // 150) % 50,
    }
    
    for name, result in formulas.items():
        if result == basket:
            print(f"  ✓ MATCH: {name} = {result}")
        elif abs(result - basket) <= 2:
            print(f"  ~ CLOSE: {name} = {result} (diff: {abs(result - basket)})")

print("\n" + "=" * 80)
print("Looking for pattern in vol digits...")
print("-" * 80)

for ex in examples:
    vol = ex["vol"]
    basket = ex["basket"]
    vol_str = str(vol)
    
    # Extract digits
    d1 = int(vol_str[0]) if len(vol_str) >= 1 else 0
    d2 = int(vol_str[1]) if len(vol_str) >= 2 else 0
    d3 = int(vol_str[2]) if len(vol_str) >= 2 else 0
    d4 = int(vol_str[3]) if len(vol_str) >= 3 else 0
    
    last2 = int(vol_str[-2:]) if len(vol_str) >= 2 else 0
    first2 = int(vol_str[:2]) if len(vol_str) >= 2 else 0
    
    print(f"\nvol={vol}, basket={basket}:")
    print(f"  last2={last2}, first2={first2}, d1={d1}, d2={d2}, d3={d3}, d4={d4}")

print("\n" + "=" * 80)
print("Trying vol // X formulas...")
print("-" * 80)

# Try different divisors
for divisor in [100, 150, 175, 200, 220, 250, 300]:
    print(f"\nvol // {divisor}:")
    for ex in examples:
        result = ex["vol"] // divisor
        if result == ex["basket"]:
            print(f"  ✓ {ex['article']}: {ex['vol']} // {divisor} = {result} (MATCH!)")
        else:
            print(f"    {ex['article']}: {ex['vol']} // {divisor} = {result} (expected {ex['basket']})")

print("\n" + "=" * 80)
print("Trying (vol // X) % Y formulas...")
print("-" * 80)

# Try combinations
for div in [100, 150, 200]:
    for mod in [50, 100]:
        matches = 0
        for ex in examples:
            result = (ex["vol"] // div) % mod
            if result == ex["basket"]:
                matches += 1
        
        if matches > 0:
            print(f"\n(vol // {div}) % {mod}: {matches}/{len(examples)} matches")
            for ex in examples:
                result = (ex["vol"] // div) % mod
                status = "✓" if result == ex["basket"] else " "
                print(f"  {status} {ex['article']}: ({ex['vol']} // {div}) % {mod} = {result} (expected {ex['basket']})")





