from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(10), default="ru")
    spoiler_level: Mapped[int] = mapped_column(Integer, default=0)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)


class Story(Base, TimestampMixin):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(100), default="ongoing")
    cover_file_id: Mapped[str | None] = mapped_column(String(255))
    guide_source_name: Mapped[str | None] = mapped_column(String(255))
    guide_source_url: Mapped[str | None] = mapped_column(String(500))
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    views_count: Mapped[int] = mapped_column(Integer, default=0)

    seasons: Mapped[list["Season"]] = relationship(back_populates="story", cascade="all, delete-orphan")
    characters: Mapped[list["Character"]] = relationship(back_populates="story", cascade="all, delete-orphan")
    parameters: Mapped[list["Parameter"]] = relationship(back_populates="story", cascade="all, delete-orphan")


class Season(Base, TimestampMixin):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("story_id", "number", name="uq_story_season_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")

    story: Mapped[Story] = relationship(back_populates="seasons")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="season", cascade="all, delete-orphan")


class Episode(Base, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("season_id", "number", name="uq_season_episode_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    guide_intro: Mapped[str] = mapped_column(Text, default="")
    guide_source_name: Mapped[str | None] = mapped_column(String(255))
    guide_source_url: Mapped[str | None] = mapped_column(String(500))
    image_file_id: Mapped[str | None] = mapped_column(String(255))
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)

    season: Mapped[Season] = relationship(back_populates="episodes")
    choices: Mapped[list["Choice"]] = relationship(back_populates="episode", cascade="all, delete-orphan")


class Parameter(Base, TimestampMixin):
    __tablename__ = "parameters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    icon: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")

    story: Mapped[Story] = relationship(back_populates="parameters")


class Character(Base, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(120), default="Второстепенный персонаж")
    is_love_interest: Mapped[bool] = mapped_column(Boolean, default=False)
    spoiler_level: Mapped[int] = mapped_column(Integer, default=0)
    image_file_id: Mapped[str | None] = mapped_column(String(255))
    facts: Mapped[str] = mapped_column(Text, default="")

    story: Mapped[Story] = relationship(back_populates="characters")
    romance_routes: Mapped[list["RomanceRoute"]] = relationship(back_populates="character", cascade="all, delete-orphan")


class RomanceRoute(Base, TimestampMixin):
    __tablename__ = "romance_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    advice: Mapped[str] = mapped_column(Text, default="")
    important_choices: Mapped[str] = mapped_column(Text, default="")
    endings: Mapped[str] = mapped_column(Text, default="")
    spoiler_level: Mapped[int] = mapped_column(Integer, default=1)

    character: Mapped[Character] = relationship(back_populates="romance_routes")


class Choice(Base, TimestampMixin):
    __tablename__ = "choices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    scene_title: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    recommended_option: Mapped[str] = mapped_column(Text)
    cost_diamonds: Mapped[int] = mapped_column(Integer, default=0)
    consequence: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[str] = mapped_column(Text, default="")
    parameter_changes: Mapped[str] = mapped_column(Text, default="")
    character_effects: Mapped[str] = mapped_column(Text, default="")
    future_effects: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(255), default="")
    spoiler_level: Mapped[int] = mapped_column(Integer, default=1)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)

    episode: Mapped[Episode] = relationship(back_populates="choices")


class UpdatePost(Base, TimestampMixin):
    __tablename__ = "updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    source_name: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(500))
    game_version: Mapped[str | None] = mapped_column(String(50))
    image_file_id: Mapped[str | None] = mapped_column(String(255))
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)


class Favorite(Base, TimestampMixin):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_favorite_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(50))
    item_id: Mapped[int] = mapped_column(Integer)


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "story_id", name="uq_user_story_subscription"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    story_id: Mapped[int | None] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(100), default="story")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Progress(Base, TimestampMixin):
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("user_id", "story_id", name="uq_user_story_progress"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="SET NULL"))
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"))


class Rating(Base, TimestampMixin):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("user_id", "item_type", "item_id", name="uq_user_rating_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(50))
    item_id: Mapped[int] = mapped_column(Integer)
    value: Mapped[int] = mapped_column(Integer)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(50))
    item_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="new")


class Achievement(Base, TimestampMixin):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")


class UserAchievement(Base, TimestampMixin):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    achievement_id: Mapped[int] = mapped_column(ForeignKey("achievements.id", ondelete="CASCADE"), index=True)
