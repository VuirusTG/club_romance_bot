from __future__ import annotations

from dataclasses import dataclass, field

from scripts.gamesisart.models import StoryDocument


@dataclass
class ValidationResult:
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_story_document(document: StoryDocument) -> ValidationResult:
    result = ValidationResult()
    if not document.source_key:
        result.errors.append("Story source_key is empty.")
    if not document.source_url:
        result.errors.append("Story source_url is empty.")
    if not document.canonical_url:
        result.errors.append("Story canonical_url is empty.")
    if not document.source_title:
        result.errors.append("Story source_title is empty.")
    if not document.seasons:
        result.errors.append("Story has no seasons.")

    season_numbers: set[int] = set()
    previous_season = 0
    for season in document.seasons:
        if season.number in season_numbers:
            result.errors.append(f"Duplicate season number: {season.number}.")
        season_numbers.add(season.number)
        if season.number <= previous_season:
            result.warnings.append(f"Season order is not strictly increasing near season {season.number}.")
        previous_season = season.number
        if not season.episodes:
            result.warnings.append(f"Season {season.number} has no episodes.")

        episode_numbers: set[int] = set()
        previous_episode = 0
        for episode in season.episodes:
            if episode.number in episode_numbers:
                result.errors.append(f"Duplicate episode number {episode.number} in season {season.number}.")
            episode_numbers.add(episode.number)
            if episode.number <= previous_episode:
                result.warnings.append(
                    f"Episode order is not strictly increasing in season {season.number} near episode {episode.number}."
                )
            previous_episode = episode.number
            if not episode.title:
                result.warnings.append(f"Episode {season.number}.{episode.number} has empty title.")

            block_orders: set[int] = set()
            previous_block = 0
            for block in episode.blocks:
                if block.order in block_orders:
                    result.errors.append(
                        f"Duplicate block order {block.order} in episode {season.number}.{episode.number}."
                    )
                block_orders.add(block.order)
                if block.order <= previous_block:
                    result.warnings.append(
                        f"Block order is not strictly increasing in episode {season.number}.{episode.number}."
                    )
                previous_block = block.order
                if block.type != "unknown" and not block.text:
                    result.warnings.append(
                        f"Empty text in {block.type} block {block.order} of episode {season.number}.{episode.number}."
                    )
                if block.choice:
                    if block.choice.order != block.order:
                        result.warnings.append(
                            f"Choice order differs from block order in episode {season.number}.{episode.number}."
                        )
                    if not block.choice.text:
                        result.errors.append(
                            f"Choice block {block.order} in episode {season.number}.{episode.number} has empty text."
                        )
                    if block.choice.cost_diamonds < 0:
                        result.errors.append(
                            f"Choice block {block.order} in episode {season.number}.{episode.number} has negative cost."
                        )
    return result

