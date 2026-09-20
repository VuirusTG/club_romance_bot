from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ChoiceDocument:
    order: int
    text: str
    cost_diamonds: int = 0
    tags: list[str] = field(default_factory=list)
    parameter_changes: list[str] = field(default_factory=list)
    character_effects: list[str] = field(default_factory=list)
    future_effects: list[str] = field(default_factory=list)
    is_critical: bool = False


@dataclass
class Block:
    order: int
    type: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    choice: ChoiceDocument | None = None


@dataclass
class EpisodeDocument:
    number: int
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class SeasonDocument:
    number: int
    title: str
    episodes: list[EpisodeDocument] = field(default_factory=list)


@dataclass
class StoryDocument:
    parser_version: str
    source: str
    source_key: str
    source_url: str
    canonical_url: str
    source_title: str
    seasons: list[SeasonDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StoryDocument:
        seasons = []
        for s in d.get("seasons", []):
            episodes = []
            for ep in s.get("episodes", []):
                blocks = []
                for b in ep.get("blocks", []):
                    ch_data = b.get("choice")
                    ch = ChoiceDocument(**ch_data) if ch_data else None
                    blocks.append(
                        Block(
                            order=b["order"],
                            type=b["type"],
                            text=b["text"],
                            metadata=b.get("metadata", {}),
                            choice=ch,
                        )
                    )
                episodes.append(
                    EpisodeDocument(
                        number=ep["number"],
                        title=ep["title"],
                        blocks=blocks,
                    )
                )
            seasons.append(
                SeasonDocument(
                    number=s["number"],
                    title=s["title"],
                    episodes=episodes,
                )
            )
        return cls(
            parser_version=d.get("parser_version", "1.2.0"),
            source=d.get("source", "gamesisart"),
            source_key=d.get("source_key", ""),
            source_url=d.get("source_url", ""),
            canonical_url=d.get("canonical_url", ""),
            source_title=d.get("source_title", ""),
            seasons=seasons,
            warnings=d.get("warnings", []),
            errors=d.get("errors", []),
            metadata=d.get("metadata", {}),
        )

