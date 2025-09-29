import math
from scipy.optimize import fsolve

def american_to_prob(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

def prob_to_american(prob):
    decimal_odds = 1 / prob
    if decimal_odds >= 2:
        return (decimal_odds - 1) * 100
    else:
        return -100 / (decimal_odds - 1)

def power_no_vig(odds1, odds2):
    p1 = american_to_prob(odds1)
    p2 = american_to_prob(odds2)

    # Step 2: Define function to solve for k
    def equation(k):
        q1 = p1**k
        q2 = p2**k
        total = q1 + q2
        return (q1/total + q2/total) - 1  # should equal 0

    # Step 3: Solve for k numerically (start near 1)
    k = fsolve(equation, 1)[0]

    # Step 4: Apply power and normalize
    q1, q2 = p1**k, p2**k
    total = q1 + q2
    fair_p1, fair_p2 = q1/total, q2/total

    # Step 5: Convert back to American odds
    fair_odds1 = prob_to_american(fair_p1)
    fair_odds2 = prob_to_american(fair_p2)

    return {
        "k": k,
        "fair_probs": (fair_p1, fair_p2),
        "fair_odds": (fair_odds1, fair_odds2)
    }

# --- Example with +122 / -138 ---
result = power_no_vig(122, -138)

print("Power parameter k:", result["k"])
print("No-vig probabilities:", result["fair_probs"])
print("No-vig odds (American):", result["fair_odds"])
