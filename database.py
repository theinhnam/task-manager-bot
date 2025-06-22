from sqlalchemy import create_engine, Column, String, DateTime, Integer, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
import os

Base = declarative_base()

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    user_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    project_name = Column(String)
    content = Column(String)
    due_date = Column(DateTime(timezone=True), nullable=True)
    notified_10min = Column(Boolean, default=False)
    notified_due = Column(Boolean, default=False)
    user_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Khởi tạo database
DATABASE_URL = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)