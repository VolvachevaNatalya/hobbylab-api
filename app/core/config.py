import os


def parse_cors_origins() -> list:
    """Parse CORS_ORIGINS env var into a list of allowed origins.

    Default ("*"): allow all origins — preserves current production behavior.
    To restrict, set CORS_ORIGINS in Railway to a comma-separated list:
      CORS_ORIGINS=https://admin.hobbylab.co.il

    No current API client (Flutter mobile, Next.js admin) requires browser CORS,
    so this can safely be restricted to an empty list without breaking any client.
    """
    raw = os.getenv("CORS_ORIGINS", "*")
    if raw.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]
