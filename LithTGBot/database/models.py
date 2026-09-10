import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, BigInteger, Boolean, DateTime, ForeignKey, UUID, JSON, Integer
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    telegram_id = Column(BigInteger, primary_key=True)
    timezone = Column(Integer, default=3)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(500), nullable=False)
    auth_token = Column(Text, nullable=False)
    default_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="projects")
    default_message = relationship("Message", foreign_keys=[default_message_id], post_update=True)
    groups = relationship("Group", back_populates="project", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="project", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    max_group_id = Column(BigInteger, nullable=False)
    custom_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="groups")
    custom_message = relationship("Message", foreign_keys=[custom_message_id], post_update=True)
    schedules = relationship("Schedule", back_populates="group", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="group", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text_content = Column(Text, nullable=True)
    media_type = Column(String(50), nullable=True)
    media_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project_default = relationship("Project", back_populates="default_message", foreign_keys=[Project.default_message_id])
    group_custom = relationship("Group", back_populates="custom_message", foreign_keys=[Group.custom_message_id])


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    schedule_type = Column(String(20), nullable=False)
    schedule_value = Column(JSON, nullable=False)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    group = relationship("Group", back_populates="schedules")


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    group_id = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="logs")
    group = relationship("Group", back_populates="logs")
    user = relationship("User", back_populates="logs")
