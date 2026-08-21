ROLES = {
    "GK": ["Goalkeeper"],
    "CB": ["Center Back", "Left Center Back", "Right Center Back"],
    "FB": ["Left Back", "Right Back", "Left Wing Back", "Right Wing Back"],
    "DM": ["Center Defensive Midfield", "Left Defensive Midfield",
           "Right Defensive Midfield"],
    "CM": ["Center Midfield", "Left Center Midfield", "Right Center Midfield",
           "Center Attacking Midfield", "Left Attacking Midfield",
           "Right Attacking Midfield"],
    "W":  ["Left Wing", "Right Wing", "Left Midfield", "Right Midfield"],
    "FW": ["Center Forward", "Left Center Forward", "Right Center Forward",
           "Secondary Striker"],
}

POS2ROLE = {p: r for r, ps in ROLES.items() for p in ps}