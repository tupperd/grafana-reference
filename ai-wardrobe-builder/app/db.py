"""Tiny SQLite data layer (stdlib only). Seeds a starter wardrobe on first run."""
import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT NOT NULL,
  type      TEXT NOT NULL,
  color     TEXT DEFAULT '',
  season    TEXT DEFAULT '',
  formality TEXT DEFAULT '',
  material  TEXT DEFAULT '',
  notes     TEXT DEFAULT ''
);
"""

# (name, type, color, season, formality, material, notes)
SEED = [
    ("White Oxford Shirt", "top", "white", "all-season", "smart-casual", "cotton", "Button-down collar"),
    ("Grey Crewneck Tee", "top", "grey", "all-season", "casual", "cotton", "Everyday basic"),
    ("Black Merino Sweater", "top", "black", "fall/winter", "smart-casual", "wool", "Lightweight knit"),
    ("Light Blue Linen Shirt", "top", "light blue", "summer", "casual", "linen", "Breathable"),
    ("Navy Chinos", "bottom", "navy", "all-season", "smart-casual", "cotton", "Slim fit"),
    ("Dark Wash Jeans", "bottom", "indigo", "all-season", "casual", "denim", "Straight leg"),
    ("Beige Shorts", "bottom", "beige", "summer", "casual", "cotton", "7-inch inseam"),
    ("Navy Suit Trousers", "bottom", "navy", "all-season", "formal", "wool", "Pairs with blazer"),
    ("Charcoal Wool Blazer", "outerwear", "charcoal", "fall/winter", "formal", "wool", "Single-breasted"),
    ("Olive Field Jacket", "outerwear", "olive", "spring/fall", "casual", "cotton", "Water-resistant"),
    ("White Sneakers", "shoes", "white", "all-season", "casual", "leather", "Minimal low-tops"),
    ("Brown Leather Chelsea Boots", "shoes", "brown", "fall/winter", "smart-casual", "leather", "Versatile"),
]


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"] == 0:
            c.executemany(
                "INSERT INTO items (name,type,color,season,formality,material,notes) "
                "VALUES (?,?,?,?,?,?,?)",
                SEED,
            )


def list_items() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM items ORDER BY id")]


def add_item(data: dict) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO items (name,type,color,season,formality,material,notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                data["name"],
                data["type"],
                data.get("color", ""),
                data.get("season", ""),
                data.get("formality", ""),
                data.get("material", ""),
                data.get("notes", ""),
            ),
        )
        row = c.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def delete_item(item_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
