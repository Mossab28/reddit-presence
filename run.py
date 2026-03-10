#!/usr/bin/env python3
"""Reddit Presence Manager - Local application."""
import os
from dotenv import load_dotenv

load_dotenv()

from app.models import init_db
from app.web import app
from app.scheduler import start_scheduler

if __name__ == "__main__":
    init_db()
    start_scheduler()
    print("=" * 50)
    print("  Reddit Presence Manager")
    print("  http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=False)
