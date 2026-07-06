"""
Repository — SQLite 持久化层

将 KnowledgeBase（内存对象图）同步到 SQLite 数据库，
并在启动时将数据库恢复为内存对象。

公共接口：
    repo = Repository(db_path)
    repo.save_card(card)
    repo.delete_card(card_id)
    repo.save_image(image)
    repo.delete_image(image_id)
    repo.save_review_log(log)
    repo.load_knowledge_base() -> KnowledgeBase
    repo.save_knowledge_base(kb)   # 一次性批量保存

设计说明：
    - 复杂字段（list / dataclass）以 JSON 存储在 TEXT 列。
    - 每次 save_card / save_image 都使用 INSERT OR REPLACE，天然实现 upsert。
    - AnalyzeResult 使用 Pydantic model_dump_json() 序列化。
    - 日期时间均以 ISO 8601 字符串存储。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dataclass.models import (
    AnalyzeResult,
    Card,
    CandidateStatus,
    Category,
    KnowledgeBase,
    Link,
    RelationType,
    ReviewLog,
    ReviewRating,
    SourceImage,
)

logger = logging.getLogger("image2card.storage")


# ---------------------------------------------------------------------------
# DDL — 建表语句
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS categories (
    name        TEXT PRIMARY KEY,
    description TEXT DEFAULT '',
    color       TEXT DEFAULT '#7c6df0',
    icon        TEXT DEFAULT '\U0001f4c1',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id              TEXT PRIMARY KEY,
    term            TEXT NOT NULL,
    category        TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    model_note      TEXT DEFAULT '',
    user_note       TEXT DEFAULT '',
    links_json      TEXT DEFAULT '[]',
    source_image_ids_json TEXT DEFAULT '[]',
    edges_json      TEXT DEFAULT '[]',
    familiarity     INTEGER DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT,
    last_reviewed_at TEXT,
    difficulty      REAL DEFAULT 5.0,
    stability       REAL DEFAULT 1.0,
    next_due        TEXT,
    review_count    INTEGER DEFAULT 0,
    lapses          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_images (
    id                  TEXT PRIMARY KEY,
    file_path           TEXT DEFAULT '',
    title               TEXT DEFAULT '',
    tags_json           TEXT DEFAULT '[]',
    scene_type          TEXT DEFAULT '',
    card_ids_json       TEXT DEFAULT '[]',
    category            TEXT DEFAULT '',
    analyze_result_json TEXT,
    imported_at         TEXT,
    analyzed_at         TEXT
);

CREATE TABLE IF NOT EXISTS review_logs (
    id                      TEXT PRIMARY KEY,
    card_id                 TEXT NOT NULL,
    timestamp               TEXT,
    rating                  INTEGER,
    stability_before        REAL DEFAULT 0.0,
    stability_after         REAL DEFAULT 0.0,
    retrievability_at_review REAL DEFAULT 0.0
);
"""


# ---------------------------------------------------------------------------
# 辅助：datetime / date 序列化与反序列化
# ---------------------------------------------------------------------------

def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _date_to_str(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _str_to_date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """
    SQLite 持久化层，负责 Card / SourceImage / ReviewLog 的 CRUD 操作。
    实例在整个应用生命周期内共享（单例使用模式）。
    """

    def __init__(self, db_path: str) -> None:
        db_file = Path(db_path).expanduser().resolve()
        self._db_path = str(db_file)
        self._data_dir = db_file.parent
        self._image_dir = self._data_dir / "images"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_file), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()
        logger.info("Repository 初始化完毕：%s", db_file)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Category CRUD
    # ------------------------------------------------------------------

    def save_category(self, cat: Category) -> None:
        """upsert 一个 Category"""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO categories (name, description, color, icon, created_at)
            VALUES (:name, :description, :color, :icon, :created_at)
            """,
            {
                "name":        cat.name,
                "description": cat.description,
                "color":       cat.color,
                "icon":        cat.icon,
                "created_at":  _dt_to_str(cat.created_at),
            },
        )
        self._conn.commit()
        logger.debug("save_category: %s", cat.name)

    def delete_category(self, name: str) -> None:
        self._conn.execute("DELETE FROM categories WHERE name = ?", (name,))
        self._conn.commit()
        logger.debug("delete_category: %s", name)

    def rename_category(self, old_name: str, new_name: str) -> None:
        """重命名类别，同步更新 cards 和 source_images 表中的引用"""
        self._conn.execute(
            "UPDATE categories SET name = ? WHERE name = ?", (new_name, old_name)
        )
        self._conn.execute(
            "UPDATE cards SET category = ? WHERE category = ?", (new_name, old_name)
        )
        self._conn.execute(
            "UPDATE source_images SET category = ? WHERE category = ?", (new_name, old_name)
        )
        self._conn.commit()
        logger.info("rename_category: %r -> %r", old_name, new_name)

    def load_all_categories(self) -> list[Category]:
        rows = self._conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
        return [
            Category(
                name=r["name"],
                description=r["description"] or "",
                color=r["color"] or "#7c6df0",
                icon=r["icon"] or "📁",
                created_at=_str_to_dt(r["created_at"]) or datetime.now(),
            )
            for r in rows
        ]

    def save_card(self, card: Card) -> None:
        """插入或替换一张卡片记录（upsert）。"""
        links_data = [{"title": lk.title, "url": lk.url} for lk in card.links]
        edges_data = [
            {
                "to_card_id":    e.to_card_id,
                "relation_type": e.relation_type.value,
                "weight":        e.weight,
                "created_by":    e.created_by,
            }
            for e in card.edges
        ]
        self._conn.execute(
            """
            INSERT OR REPLACE INTO cards VALUES (
                :id, :term, :category,
                :summary, :model_note, :user_note,
                :links_json, :source_image_ids_json, :edges_json,
                :familiarity,
                :created_at, :updated_at, :last_reviewed_at,
                :difficulty, :stability, :next_due,
                :review_count, :lapses
            )
            """,
            {
                "id":                    card.id,
                "term":                  card.term,
                "category":              card.category,
                "summary":               card.summary,
                "model_note":            card.model_note,
                "user_note":             card.user_note,
                "links_json":            json.dumps(links_data, ensure_ascii=False),
                "source_image_ids_json": json.dumps(card.source_image_ids),
                "edges_json":            json.dumps(edges_data, ensure_ascii=False),
                "familiarity":           card.familiarity,
                "created_at":            _dt_to_str(card.created_at),
                "updated_at":            _dt_to_str(card.updated_at),
                "last_reviewed_at":      _dt_to_str(card.last_reviewed_at),
                "difficulty":            card.difficulty,
                "stability":             card.stability,
                "next_due":              _date_to_str(card.next_due),
                "review_count":          card.review_count,
                "lapses":                card.lapses,
            },
        )
        self._conn.commit()
        logger.debug("save_card: %s (%s)", card.id, card.term)

    def delete_card(self, card_id: str) -> None:
        self._conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        self._conn.commit()
        logger.debug("delete_card: %s", card_id)

    def load_all_cards(self) -> list[Card]:
        rows = self._conn.execute("SELECT * FROM cards").fetchall()
        cards = [self._row_to_card(r) for r in rows]
        logger.info("load_all_cards: %d 张卡片", len(cards))
        return cards

    def load_card(self, card_id: str) -> Optional[Card]:
        row = self._conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        return self._row_to_card(row) if row else None

    # ------------------------------------------------------------------
    # SourceImage CRUD
    # ------------------------------------------------------------------

    def save_image(self, image: SourceImage) -> None:
        analyze_json = (
            image.analyze_result.model_dump_json()
            if image.analyze_result else None
        )
        stored_file_path = self._image_path_for_storage(image.file_path)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO source_images VALUES (
                :id, :file_path, :title, :tags_json, :scene_type,
                :card_ids_json, :category, :analyze_result_json,
                :imported_at, :analyzed_at
            )
            """,
            {
                "id":                   image.id,
                "file_path":            stored_file_path,
                "title":                image.title,
                "tags_json":            json.dumps(image.tags, ensure_ascii=False),
                "scene_type":           image.scene_type,
                "card_ids_json":        json.dumps(image.card_ids),
                "category":             image.category,
                "analyze_result_json":  analyze_json,
                "imported_at":          _dt_to_str(image.imported_at),
                "analyzed_at":          _dt_to_str(image.analyzed_at),
            },
        )
        self._conn.commit()
        logger.debug("save_image: %s (%s)", image.id, stored_file_path)

    def delete_image(self, image_id: str) -> None:
        self._conn.execute("DELETE FROM source_images WHERE id = ?", (image_id,))
        self._conn.commit()

    def discard_images_and_source_refs(self) -> None:
        """Remove disposable image records and clear legacy card source refs."""
        self._conn.execute("DELETE FROM source_images")
        self._conn.execute("UPDATE cards SET source_image_ids_json = '[]'")
        self._conn.commit()
        logger.info("discard_images_and_source_refs: cleared source_images and card source refs")

    def load_all_images(self) -> list[SourceImage]:
        rows = self._conn.execute("SELECT * FROM source_images").fetchall()
        return [self._row_to_image(r) for r in rows]

    def repair_portable_image_paths(self) -> int:
        """
        Rewrite app-owned image paths to data-dir-relative form.

        This makes a copied ~/.image2card directory usable on another account:
        old absolute paths like /Users/alice/.image2card/images/a.jpg become
        images/a.jpg. Runtime objects still receive absolute resolved paths.
        """
        rows = self._conn.execute("SELECT id, file_path FROM source_images").fetchall()
        updates: list[tuple[str, str]] = []
        for row in rows:
            current = row["file_path"] or ""
            resolved = self._resolve_source_file_path(current)
            portable = self._image_path_for_storage(resolved)
            if portable != current:
                updates.append((portable, row["id"]))

        if updates:
            self._conn.executemany(
                "UPDATE source_images SET file_path = ? WHERE id = ?",
                updates,
            )
            self._conn.commit()
            logger.info("repair_portable_image_paths: updated %d paths", len(updates))
        return len(updates)

    # ------------------------------------------------------------------
    # ReviewLog
    # ------------------------------------------------------------------

    def save_review_log(self, log: ReviewLog) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO review_logs VALUES (
                :id, :card_id, :timestamp, :rating,
                :stability_before, :stability_after, :retrievability_at_review
            )
            """,
            {
                "id":                       log.id,
                "card_id":                  log.card_id,
                "timestamp":                _dt_to_str(log.timestamp),
                "rating":                   log.rating.value,
                "stability_before":         log.stability_before,
                "stability_after":          log.stability_after,
                "retrievability_at_review": log.retrievability_at_review,
            },
        )
        self._conn.commit()

    def load_review_logs(self, card_id: Optional[str] = None) -> list[ReviewLog]:
        if card_id:
            rows = self._conn.execute(
                "SELECT * FROM review_logs WHERE card_id = ? ORDER BY timestamp",
                (card_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM review_logs ORDER BY timestamp"
            ).fetchall()
        return [self._row_to_review_log(r) for r in rows]

    # ------------------------------------------------------------------
    # KnowledgeBase 批量操作
    # ------------------------------------------------------------------

    def load_knowledge_base(self) -> KnowledgeBase:
        """从数据库恢复完整的 KnowledgeBase（应用启动时调用）。"""
        kb = KnowledgeBase()
        for cat in self.load_all_categories():
            kb.add_category(cat)
        for card in self.load_all_cards():
            kb.add_card(card)
        for image in self.load_all_images():
            kb.add_image(image)
        logger.info(
            "load_knowledge_base: %d 类别, %d 张卡片, %d 张图片",
            len(kb.all_categories()),
            len(kb.all_cards()),
            len(kb.all_images()),
        )
        return kb

    def save_knowledge_base(self, kb: KnowledgeBase) -> None:
        """将整个 KnowledgeBase 批量保存到数据库（覆盖写入）。"""
        for cat in kb.all_categories():
            self.save_category(cat)
        for card in kb.all_cards():
            self.save_card(card)
        for image in kb.all_images():
            self.save_image(image)
        logger.info("save_knowledge_base 完成")

    # ------------------------------------------------------------------
    # 内部转换：Row → dataclass
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> Card:
        links_data = json.loads(row["links_json"] or "[]")
        links = [Link(title=lk["title"], url=lk["url"]) for lk in links_data]

        edges_data = json.loads(row["edges_json"] or "[]")
        edges = [
            Card.Edge(
                to_card_id=e["to_card_id"],
                relation_type=RelationType(e.get("relation_type", "related_to")),
                weight=e.get("weight", 1.0),
                created_by=e.get("created_by", "user"),
            )
            for e in edges_data
        ]

        return Card(
            id=row["id"],
            term=row["term"],
            category=row["category"] or "",
            summary=row["summary"] or "",
            model_note=row["model_note"] or "",
            user_note=row["user_note"] or "",
            links=links,
            source_image_ids=json.loads(row["source_image_ids_json"] or "[]"),
            edges=edges,
            familiarity=row["familiarity"],
            created_at=_str_to_dt(row["created_at"]) or datetime.now(),
            updated_at=_str_to_dt(row["updated_at"]) or datetime.now(),
            last_reviewed_at=_str_to_dt(row["last_reviewed_at"]),
            difficulty=row["difficulty"],
            stability=row["stability"],
            next_due=_str_to_date(row["next_due"]),
            review_count=row["review_count"],
            lapses=row["lapses"],
        )

    def _row_to_image(self, row: sqlite3.Row) -> SourceImage:
        analyze_result = None
        if row["analyze_result_json"]:
            try:
                analyze_result = AnalyzeResult.model_validate_json(
                    row["analyze_result_json"]
                )
            except Exception:
                pass

        return SourceImage(
            id=row["id"],
            file_path=self._resolve_source_file_path(row["file_path"] or ""),
            title=row["title"] or "",
            tags=json.loads(row["tags_json"] or "[]"),
            scene_type=row["scene_type"] or "",
            card_ids=json.loads(row["card_ids_json"] or "[]"),
            category=row["category"] or "",
            analyze_result=analyze_result,
            imported_at=_str_to_dt(row["imported_at"]) or datetime.now(),
            analyzed_at=_str_to_dt(row["analyzed_at"]),
        )

    def _resolve_source_file_path(self, file_path: str) -> str:
        """Resolve stored source-image paths against the current data directory."""
        if not file_path:
            return ""

        raw = Path(file_path).expanduser()
        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
            parts = raw.parts
            if ".image2card" in parts:
                idx = parts.index(".image2card")
                suffix = parts[idx + 1 :]
                if suffix:
                    candidates.append(self._data_dir.joinpath(*suffix))
            if raw.name:
                candidates.append(self._image_dir / raw.name)
        else:
            candidates.append(self._data_dir / raw)
            if raw.parent == Path(".") and raw.name:
                candidates.append(self._image_dir / raw.name)

        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

        # Prefer the current data dir for old app-owned paths even if the file
        # is missing, so UI/tooltips show the path the user should restore.
        if raw.is_absolute() and ".image2card" in raw.parts:
            idx = raw.parts.index(".image2card")
            suffix = raw.parts[idx + 1 :]
            if suffix:
                return str(self._data_dir.joinpath(*suffix))
        if not raw.is_absolute():
            return str(self._data_dir / raw)
        return str(raw)

    def _image_path_for_storage(self, file_path: str) -> str:
        """Store app-owned image files as data-dir-relative paths."""
        if not file_path:
            return ""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            return path.as_posix()
        try:
            rel = path.resolve().relative_to(self._data_dir)
        except (OSError, ValueError):
            return str(path)
        return rel.as_posix()

    @staticmethod
    def _row_to_review_log(row: sqlite3.Row) -> ReviewLog:
        return ReviewLog(
            id=row["id"],
            card_id=row["card_id"],
            timestamp=_str_to_dt(row["timestamp"]) or datetime.now(),
            rating=ReviewRating(row["rating"]),
            stability_before=row["stability_before"],
            stability_after=row["stability_after"],
            retrievability_at_review=row["retrievability_at_review"],
        )
