import logging
from typing import Optional, Set
from urllib.parse import urlparse
from local_first_common.url import normalize_url
from . import store

logger = logging.getLogger(__name__)

class DiscoverySession:
    """Tracks state for a single discovery run to handle deduplication and failures."""

    def __init__(self, store_path: str, no_dedup: bool = False):
        self.store_path = store_path
        self.no_dedup = no_dedup
        self.seen_urls: Set[str] = set()
        self.failed_domains: Set[str] = set()
        self.failed_urls: Set[str] = set()

    def should_skip_url(self, url: str) -> bool:
        """Return True if the URL should be skipped based on session state or DB."""
        if not url:
            return True

        norm_url = normalize_url(url)
        
        # 1. Check in-memory session cache (fastest)
        if norm_url in self.seen_urls:
            return True
        if norm_url in self.failed_urls:
            return True
            
        # 2. Check domain-level blacklist (403/429 errors)
        domain = urlparse(norm_url).netloc.lower()
        if domain in self.failed_domains:
            return True
            
        # 3. Check persistent database
        if not self.no_dedup and store.is_seen(norm_url, self.store_path):
            return True
            
        return False

    def mark_seen(self, url: str):
        """Record that a URL has been processed in this session."""
        self.seen_urls.add(normalize_url(url))

    def mark_failed(self, url: str, status_code: Optional[int] = None):
        """Record a fetch failure and optionally blacklist the domain for this session."""
        norm_url = normalize_url(url)
        self.failed_urls.add(norm_url)
        
        # Blacklist domains that explicitly reject us (403) or rate limit us (429)
        if status_code in (403, 429):
            domain = urlparse(norm_url).netloc.lower()
            if domain:
                self.failed_domains.add(domain)
                logger.info("Skipping domain %s for the remainder of this session (HTTP %s)", domain, status_code)
