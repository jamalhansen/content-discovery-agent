"""URL cleaning utilities shared across feed_reader and social readers."""

from urllib.parse import urlparse, urlencode, parse_qsl

# Query parameters that are tracking-only and carry no page identity.
_TRACKING_PARAMS: frozenset[str] = frozenset({
    # UTM (Google Analytics / social scheduling tools)
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    # Platform click-tracking
    "fbclid",       # Facebook
    "gclid",        # Google Ads
    "mc_eid",       # Mailchimp
    # NOTE: "ref" and "source" intentionally excluded — too generic.
    # e.g. GitHub uses ?ref=main for branch refs; many sites use ?source= legitimately.
})


def clean_url(url: str) -> str:
    """Strip known tracking query parameters from a URL.

    The URL's path and non-tracking parameters are preserved.
    Returns the original string unchanged if parsing fails.
    """
    try:
        parsed = urlparse(url)
        kept = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
        clean_query = urlencode(kept)
        return parsed._replace(query=clean_query).geturl()
    except Exception:
        return url
