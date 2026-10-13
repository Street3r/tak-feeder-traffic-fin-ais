# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright Stefan Gofferje (trakbridge-plugin-ais-digitraffic)
# Copyright (C) 2026 Street3r (category tags)
"""AIS ship types: description and CoT type suffix (from the TrakBridge plugin)."""

from __future__ import annotations

# AIS type -> (description, CoT suffix after "a-<affiliation>")
AIS_TYPE_DATA = {
    0: ("Not available (default)", "-S-X"),
    20: ("Wing in ground (WIG), all ships of this type", "-S-X"),
    21: ("Wing in ground (WIG), Hazardous category A", "-S-X"),
    22: ("Wing in ground (WIG), Hazardous category B", "-S-X"),
    23: ("Wing in ground (WIG), Hazardous category C", "-S-X"),
    24: ("Wing in ground (WIG), Hazardous category D", "-S-X"),
    30: ("Fishing", "-S-X-F"),
    31: ("Towing", "-S-X-M-T-O"),
    32: ("Towing: length exceeds 200m or breadth exceeds 25m", "-S-X-P"),
    33: ("Dredging or underwater ops", "-S-X-M"),
    34: ("Diving ops", "-S-X-M"),
    35: ("Military ops", "-S-C"),
    36: ("Sailing", "-S-X-R"),
    37: ("Pleasure Craft", "-S-X-P"),
    40: ("High speed craft (HSC), all ships of this type", "-S-X-A"),
    41: ("High speed craft (HSC), Hazardous category A", "-S-X-A"),
    42: ("High speed craft (HSC), Hazardous category B", "-S-X-A"),
    43: ("High speed craft (HSC), Hazardous category C", "-S-X-A"),
    44: ("High speed craft (HSC), Hazardous category D", "-S-X-A"),
    49: ("High speed craft (HSC), No additional information", "-S-X-A"),
    50: ("Pilot Vessel", "-S-X"),
    51: ("Search and Rescue vessel", "-S-N"),
    52: ("Tug", "-S-X-M-T-U"),
    53: ("Port Tender", "-S-X-M-T-U"),
    54: ("Anti-pollution equipment", "-S-X"),
    55: ("Law Enforcement", "-S-X-L"),
    58: ("Medical Transport", "-S-N-M"),
    59: ("Noncombatant ship according to RR Resolution No. 18", "-S-N"),
    60: ("Passenger, all ships of this type", "-S-X-M-P"),
    61: ("Passenger, Hazardous category A", "-S-X-M-H"),
    62: ("Passenger, Hazardous category B", "-S-X-M-H"),
    63: ("Passenger, Hazardous category C", "-S-X-M-H"),
    64: ("Passenger, Hazardous category D", "-S-X-M-H"),
    69: ("Passenger, No additional information", "-S-X-M-P"),
    70: ("Cargo, all ships of this type", "-S-X-M-C"),
    71: ("Cargo, Hazardous category A", "-S-X-M-H"),
    72: ("Cargo, Hazardous category B", "-S-X-M-H"),
    73: ("Cargo, Hazardous category C", "-S-X-M-H"),
    74: ("Cargo, Hazardous category D", "-S-X-M-H"),
    75: ("Cargo, Reserved for future use", "-S-X-M-C"),
    76: ("Cargo, Reserved for future use", "-S-X-M-C"),
    77: ("Cargo, Reserved for future use", "-S-X-M-C"),
    78: ("Cargo, Reserved for future use", "-S-X-M-C"),
    79: ("Cargo, No additional information", "-S-X-M-C"),
    80: ("Tanker, all ships of this type", "-S-X-M-O"),
    81: ("Tanker, Hazardous category A", "-S-X-M-H"),
    82: ("Tanker, Hazardous category B", "-S-X-M-H"),
    83: ("Tanker, Hazardous category C", "-S-X-M-H"),
    84: ("Tanker, Hazardous category D", "-S-X-M-H"),
    85: ("Tanker, Reserved for future use", "-S-X-M-O"),
    86: ("Tanker, Reserved for future use", "-S-X-M-O"),
    87: ("Tanker, Reserved for future use", "-S-X-M-O"),
    88: ("Tanker, Reserved for future use", "-S-X-M-O"),
    89: ("Tanker, No additional information", "-S-X-M-O"),
    90: ("Other Type, all ships of this type", "-S"),
    91: ("Other Type, Hazardous category A", "-S"),
    92: ("Other Type, Hazardous category B", "-S"),
    93: ("Other Type, Hazardous category C", "-S"),
    94: ("Other Type, Hazardous category D", "-S"),
    99: ("Other Type, no additional information", "-S"),
}


# Hashtag per AIS type range
def category(ais_type: int) -> str:
    """Short category tag for an AIS ship type."""
    fixed = {30: "fishing", 31: "towing", 32: "towing", 33: "dredging", 34: "diving",
             35: "military", 36: "sailing", 37: "pleasure", 50: "pilot", 51: "sar",
             52: "tug", 53: "tender", 54: "antipollution", 55: "lawenforcement",
             58: "medical"}
    if ais_type in fixed:
        return fixed[ais_type]
    for low, high, name in ((20, 29, "wig"), (40, 49, "highspeed"), (60, 69, "passenger"),
                            (70, 79, "cargo"), (80, 89, "tanker")):
        if low <= ais_type <= high:
            return name
    return "other"


def describe(ais_type: int) -> tuple[str, str]:
    """(description, CoT suffix); unknown types are generic surface vessels."""
    return AIS_TYPE_DATA.get(ais_type, ("Unknown", "-S-X"))
