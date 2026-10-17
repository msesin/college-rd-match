"""Small parsing helpers with no Django dependency."""


def to_number(value):
    """Parse '$84,590', '91.00%', '1,234', '4.15' into a float. Returns None if not numeric."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("$", "").replace("%", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None
