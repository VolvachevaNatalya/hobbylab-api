"""Firebase Cloud Messaging helper.

Initialization is deferred to the first send call.  If the
FIREBASE_SERVICE_ACCOUNT_JSON environment variable is absent or the
firebase-admin package is not installed, all send operations become no-ops
so callers never need to handle FCM-specific errors.
"""
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

_initialized = False
_enabled = False


def _ensure_initialized() -> bool:
    global _initialized, _enabled
    if _initialized:
        return _enabled
    _initialized = True

    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not service_account_json:
        logger.info("fcm_disabled | FIREBASE_SERVICE_ACCOUNT_JSON not set")
        return False

    try:
        import firebase_admin  # noqa: F401 — checked here, used below
        import firebase_admin.credentials
        import firebase_admin.messaging  # noqa: F401
    except ImportError:
        logger.warning("fcm_disabled | firebase-admin package not installed")
        return False

    try:
        import firebase_admin
        import firebase_admin.credentials

        cred_dict = json.loads(service_account_json)
        cred = firebase_admin.credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _enabled = True
        logger.info("fcm_initialized")
        return True
    except Exception as exc:
        logger.error("fcm_init_failed | error=%s", exc)
        return False


def send_to_tokens(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> List[str]:
    """Send an FCM notification to one or more device tokens.

    Returns the list of tokens that FCM reported as invalid/expired so the
    caller can remove them from the database.  Never raises — FCM errors are
    logged and swallowed so the calling request always succeeds.
    """
    if not tokens:
        return []
    if not _ensure_initialized():
        return []

    try:
        import firebase_admin.messaging as _msg

        str_data = {k: str(v) for k, v in (data or {}).items()}

        message = _msg.MulticastMessage(
            tokens=tokens[:500],  # FCM multicast limit
            notification=_msg.Notification(title=title, body=body),
            data=str_data,
            android=_msg.AndroidConfig(
                notification=_msg.AndroidNotification(
                    icon="ic_notification",
                    channel_id="hobbylab_default",
                ),
                priority="high",
            ),
        )

        result = _msg.send_each_for_multicast(message)

        invalid: List[str] = []
        for idx, response in enumerate(result.responses):
            if not response.success:
                code = ""
                if response.exception:
                    code = getattr(response.exception, "code", "") or ""
                if code in (
                    "registration-token-not-registered",
                    "invalid-registration-token",
                ):
                    invalid.append(tokens[idx])
                else:
                    logger.warning(
                        "fcm_send_failed | token_prefix=%s | code=%s",
                        tokens[idx][:8],
                        code,
                    )

        logger.info(
            "fcm_multicast | sent=%d | failed=%d | invalid=%d",
            len(tokens),
            len(result.responses) - result.success_count,
            len(invalid),
        )
        return invalid

    except Exception as exc:
        logger.error("fcm_multicast_error | count=%d | error=%s", len(tokens), exc)
        return []


# Allow tests to reset state between test runs
def _reset_for_testing() -> None:
    global _initialized, _enabled
    _initialized = False
    _enabled = False
