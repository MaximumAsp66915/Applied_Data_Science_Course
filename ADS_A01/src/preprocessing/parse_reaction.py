import re

def parse_reaction_value(cell):
    """
    Extracts valid reaction scores from a reaction string.
    Ignores malformed entries like '623:45'.
    Returns sum of valid scores.
    """
    
    total = 0
    
    # split by comma
    parts = str(cell).split(",")
    
    for p in parts:
        p = p.strip()
        
        # match pattern like "123:4" or "56:-2"
        match = re.match(r"^\s*\d+\s*:\s*(-?\d+)\s*$", p)
        
        if match:
            score = int(match.group(1))
            total += score
    
    return total


def add_reactions_weighted_sum(df):
    """
    Adds a new column reactions_w_sum based on parsed reaction scores.
    """
    df = df.copy()
    df["reactions_w_sum"] = df["reactions"].apply(parse_reaction_value)
    return df

