#!/usr/bin/env python3
"""Builds index.html with the live guest count from flowers.db."""

import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "flowers.db")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
DOCS_OUTPUT = os.path.join(ROOT, "docs", "index.html")


def get_confirmed_count():
    if not os.path.exists(DB_PATH):
        return 0
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM guests WHERE status = 'confirmed'").fetchone()[0]
    conn.close()
    return count


def build():
    count = get_confirmed_count()
    with open(TEMPLATE) as f:
        html = f.read()
    html = html.replace("{{COUNT}}", str(count))
    with open(OUTPUT, "w") as f:
        f.write(html)
    with open(DOCS_OUTPUT, "w") as f:
        f.write(html)
    print(f"Built {OUTPUT} + {DOCS_OUTPUT} — count: {count}")


if __name__ == "__main__":
    build()
