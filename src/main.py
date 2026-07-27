

L: list[str] = ["apple", "banana", "cherry", "date", "elderberry"]
numbers: list[int] = [1, 2, 3, 4, 5]

for fruit in L:
    d = {fruit: len(fruit)}

    print(d)
