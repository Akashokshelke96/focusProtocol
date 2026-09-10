from __future__ import annotations
"""
Pinterest Scraper - Fetch Cillian Murphy & John Wick images
"""
import requests
from pathlib import Path
from app.config.logging_config import get_logger

logger = get_logger("pinterest.scraper")


class PinterestScraper:
    """Scrape Pinterest for high-quality character images."""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def search_cillian_murphy(self, count: int = 6) -> list[str]:
        """Search for Cillian Murphy Peaky Blinders images."""
        logger.info(f"Searching for Cillian Murphy images ({count})...")

        searches = [
            "cillian murphy peaky blinders smoking suit dark",
            "peaky blinders tommy shelby dark noir cigarette",
            "cillian murphy gentleman noir 1920s fedora",
            "peaky blinders dark aesthetic moody lighting",
            "cillian murphy smoking contemplative noir",
            "peaky blinders character study dark cinematic"
        ]

        images = []
        for search in searches:
            if len(images) >= count:
                break
            images.extend(self._scrape_pinterest(search, 2))

        return images[:count]

    def search_john_wick(self, count: int = 6) -> list[str]:
        """Search for John Wick style images."""
        logger.info(f"Searching for John Wick style images ({count})...")

        searches = [
            "john wick keanu reeves dark noir suit smoking",
            "john wick dark aesthetic gentleman noir",
            "keanu reeves dark moody contemplative noir",
            "john wick smoking suit dark cinematic",
            "john wick dark gentleman assassin noir",
            "noir detective dark suit contemplative masculine"
        ]

        images = []
        for search in searches:
            if len(images) >= count:
                break
            images.extend(self._scrape_pinterest(search, 2))

        return images[:count]

    def _scrape_pinterest(self, query: str, count: int = 2) -> list[str]:
        """Scrape Pinterest for images matching query."""
        try:
            # Pinterest API alternative using search
            url = "https://www.pinterest.com/search/pins"
            params = {"q": query}

            response = requests.get(url, params=params, headers=self.headers, timeout=10)

            if response.status_code == 200:
                # Extract image URLs from response
                images = self._extract_image_urls(response.text, count)
                return images
            else:
                logger.warning(f"Pinterest search failed: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Pinterest scrape error: {e}")
            return []

    def _extract_image_urls(self, html: str, count: int) -> list[str]:
        """Extract image URLs from Pinterest HTML."""
        import re

        # Look for image URLs in Pinterest format
        pattern = r'https://[^\s"]*\.pinimg\.com/[^\s"]*\.jpg'
        urls = re.findall(pattern, html)

        return urls[:count]

    def download_image(self, url: str, output_path: Path) -> bool:
        """Download image from URL."""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Downloaded: {output_path.name}")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
