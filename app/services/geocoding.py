import os
from typing import Optional, Tuple

import httpx


def geocode(address: Optional[str], city: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Resolve address + city to (latitude, longitude) via Google Geocoding API.
    Returns (None, None) if the key is missing, no address data is provided,
    or the request fails for any reason.
    """
    parts = [p.strip() for p in [address, city] if p and p.strip()]
    if not parts:
        return None, None

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return None, None

    query = ", ".join(parts)
    try:
        response = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": api_key},
            timeout=5.0,
        )
        data = response.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
    except Exception:
        pass

    return None, None
