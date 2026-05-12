def find_secord_largest(nums):
    first = second = float('-inf')
    for n in nums: 
        if n > first:
            second = first
            first = n
        elif n > second and n != first:
            second = n
    return second

print(find_secord_largest([3, 7, 2, 8, 1]))
print(find_secord_largest([1, 1, 1, 1, 1]))
print(find_secord_largest([1, 2, 3, 4, 5]))
print(find_secord_largest([10,2]))