"""
Thematic lore research service for Romance Club stories.
Fetches canonical descriptions, official synopses, and lore details
from thematic encyclopedias without exposing sources or citations in generated content.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ThematicLoreData:
    title: str
    genre: str = ""
    synopsis: str = ""
    tagline: str = ""
    characters: list[str] = field(default_factory=list)
    love_interests: list[str] = field(default_factory=list)
    extra_facts: list[str] = field(default_factory=list)


class ThematicResearcher:
    """Fetches real in-game lore, official synopses and facts for Romance Club stories."""

    _cache: dict[str, ThematicLoreData] = {}

    @classmethod
    def clean_wikitext(cls, text: str) -> str:
        """Strip wiki markup, templates, categories, and references."""
        if not text:
            return ""
        # Remove templates {{...}}
        text = re.sub(r"\{\{[^}]*\}\}", "", text)
        # Convert [[link|display]] -> display, [[display]] -> display
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Remove bold / italics
        text = re.sub(r"'{2,5}", "", text)
        # Remove multiple spaces / newlines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        return text.strip()

    @classmethod
    def fetch_story_lore(cls, story_title: str) -> ThematicLoreData | None:
        """Fetch canonical lore for a story title from Romance Club Fandom Wiki."""
        key = story_title.strip().lower()
        if key in cls._cache:
            return cls._cache[key]

        try:
            # 1. Search page by title
            encoded_title = urllib.parse.quote(story_title.strip())
            url = (
                f"https://romance-club.fandom.com/ru/api.php?"
                f"action=parse&prop=wikitext&page={encoded_title}&format=json"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "RomanceClubAssistantBot/1.0 (Thematic Research)"},
            )
            wikitext = ""
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "parse" in data and "wikitext" in data["parse"]:
                    wikitext = data["parse"]["wikitext"].get("*", "")

            # If exact title failed, search via API
            if not wikitext:
                search_url = (
                    f"https://romance-club.fandom.com/ru/api.php?"
                    f"action=query&list=search&srsearch={encoded_title}&format=json"
                )
                search_req = urllib.request.Request(
                    search_url,
                    headers={"User-Agent": "RomanceClubAssistantBot/1.0 (Thematic Research)"},
                )
                with urllib.request.urlopen(search_req, timeout=6) as resp:
                    sdata = json.loads(resp.read().decode("utf-8"))
                    results = sdata.get("query", {}).get("search", [])
                    if results:
                        real_title = results[0]["title"]
                        enc_real = urllib.parse.quote(real_title)
                        fetch_url = (
                            f"https://romance-club.fandom.com/ru/api.php?"
                            f"action=parse&prop=wikitext&page={enc_real}&format=json"
                        )
                        freq = urllib.request.Request(
                            fetch_url,
                            headers={"User-Agent": "RomanceClubAssistantBot/1.0 (Thematic Research)"},
                        )
                        with urllib.request.urlopen(freq, timeout=6) as fresp:
                            fdata = json.loads(fresp.read().decode("utf-8"))
                            wikitext = fdata.get("parse", {}).get("wikitext", {}).get("*", "")

            if not wikitext:
                return None

            # Extract fields from wikitext
            tagline = ""
            tagline_match = re.search(r"<blockquote>\s*(?:'')?«(.*?)»", wikitext, re.DOTALL)
            if tagline_match:
                tagline = cls.clean_wikitext(tagline_match.group(1))

            synopsis = ""
            syn_match = re.search(r"==\s*Описание\s*==\s*(.*?)(?:==|\Z)", wikitext, re.DOTALL)
            if syn_match:
                synopsis = cls.clean_wikitext(syn_match.group(1))
            if not synopsis and tagline:
                synopsis = tagline

            # Extract characters from wikitext (Image card templates and wiki links)
            characters: list[str] = []
            for ch_match in re.finditer(r"Страница персонажа\s*=\s*([^|}\n]+)", wikitext):
                raw_name = ch_match.group(1).strip()
                clean_name = re.sub(r"\s*\([^)]*\)", "", raw_name).strip()
                if clean_name and clean_name not in characters:
                    characters.append(clean_name)

            love_interests = characters[1:6] if len(characters) > 1 else characters[:5]

            lore_data = ThematicLoreData(
                title=story_title,
                genre=genre,
                synopsis=synopsis,
                tagline=tagline,
                characters=characters[:12],
                love_interests=love_interests,
            )
            cls._cache[key] = lore_data
            return lore_data

        except Exception as e:
            logger.debug(f"Thematic lore fetch failed for {story_title}: {e}")
            return None
