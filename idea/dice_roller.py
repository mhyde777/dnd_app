# dice_roller.py
import random
import re

def roll_dice(input_string):
    # Regular expression to parse the dice notation
    dice_pattern = re.compile(r'(\d*)d(\d+)|([+-]?\d+)')
    
    total = 0
    matches = dice_pattern.findall(input_string)
    
    for match in matches:
        if match[0] and match[1]:  # Matches dice rolls (e.g., '2d6')
            num_dice = int(match[0]) if match[0] else 1
            die_type = int(match[1])
            roll_sum = sum(random.randint(1, die_type) for _ in range(num_dice))
            total += roll_sum
        elif match[2]:  # Matches flat bonuses (e.g., '+3', '-2')
            total += int(match[2])
    
    return total
