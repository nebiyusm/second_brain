"""Notion database keys, controlled vocabulary, and property names."""
from __future__ import annotations

# Logical database keys (must match NOTION_DB_IDS keys in .env)
INBOX = "inbox"
PROJECTS = "projects"
AREAS = "areas"
RESOURCES = "resources"
TASKS = "tasks"
IDEAS = "ideas"
MEDIA = "media"

# Controlled tag vocabulary — use ONLY these tags everywhere.
CONTROLLED_TAGS = [
    "realestate",
    "hospitality",
    "agriculture",
    "crypto",
    "software",
    "art-tech",
    "music",
    "content",
    "personal-growth",
    "finance",
    "legal",
    "research",
    "idea",
    "meeting",
    "decision",
]

# Idea options
IDEA_DOMAINS = ["Business", "Art", "Tech", "Personal"]
IDEA_STAGES = ["Seed", "Exploring", "Validating", "Promoted", "Parked", "Dropped"]

# Project options
PROJECT_STATUSES = ["Active", "Incubating", "Parked", "Done"]

# Task options
TASK_STATUSES = ["To do", "Doing", "Done"]
TASK_PRIORITIES = ["High", "Medium", "Low"]

# Inbox options
INBOX_STATUSES = ["Unprocessed", "Triaged", "Filed"]
INBOX_TYPES = ["Text", "Voice note", "Photo", "Link", "Video"]

# Media options
MEDIA_TYPES = ["Book", "Podcast", "Documentary", "Movie", "Video"]
MEDIA_STATUSES = ["Queue", "In progress", "Done", "Dropped"]

# Task relation property name (the spec uses "Project / Area")
TASK_PROJECT_PROP = "Project / Area"
