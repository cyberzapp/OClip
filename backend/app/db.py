import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .config import DB_PATH
from .presets import BUILTIN_RECIPES, DEFAULT_BRAND_KIT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT,
            source_path TEXT,
            proxy_path TEXT,
            thumbnail_path TEXT,
            duration_sec REAL DEFAULT 0,
            width INTEGER DEFAULT 1920,
            height INTEGER DEFAULT 1080,
            fps REAL DEFAULT 30,
            stage TEXT NOT NULL DEFAULT 'queued',
            progress INTEGER DEFAULT 0,
            status_message TEXT DEFAULT '',
            error TEXT,
            curation_pref_json TEXT DEFAULT '{}',
            render_pref_json TEXT DEFAULT '{}',
            import_pref_json TEXT DEFAULT '{}',
            recipe_id TEXT,
            brand_kit_id TEXT,
            transcript_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            duration_sec REAL NOT NULL,
            virality_score INTEGER DEFAULT 75,
            virality_breakdown_json TEXT DEFAULT '{}',
            keywords_json TEXT DEFAULT '[]',
            hashtags_json TEXT DEFAULT '[]',
            social_copy_json TEXT DEFAULT '{}',
            genre TEXT DEFAULT 'Auto',
            headline TEXT DEFAULT '',
            editing_script_json TEXT DEFAULT '{}',
            preview_path TEXT,
            export_path TEXT,
            thumbnail_path TEXT,
            render_status TEXT DEFAULT 'ready',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brand_kits (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recipes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            is_builtin INTEGER DEFAULT 0,
            settings_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
            added_at TEXT NOT NULL,
            PRIMARY KEY (collection_id, clip_id)
        );

        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id TEXT PRIMARY KEY,
            clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            title TEXT NOT NULL,
            copy TEXT NOT NULL,
            hashtags_json TEXT DEFAULT '[]',
            scheduled_at TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS credit_wallet (
            id TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 1000,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS credit_transactions (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            description TEXT NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            project_id TEXT,
            clip_id TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    # Seed built-in recipes & default brand kit if missing
    now = _now()
    cur_wallet = conn.execute("SELECT id FROM credit_wallet WHERE id = 'default'").fetchone()
    if not cur_wallet:
        conn.execute(
            "INSERT INTO credit_wallet (id, balance, updated_at) VALUES ('default', 1000, ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO credit_transactions (id, action, description, amount, balance_after, created_at) VALUES (?, 'grant', 'Initial OClip Studio local credit balance', 1000, 1000, ?)",
            (f"txn_{uuid.uuid4().hex[:10]}", now),
        )
    for r in BUILTIN_RECIPES:
        cur = conn.execute("SELECT id FROM recipes WHERE id = ?", (r["id"],)).fetchone()
        if not cur:
            conn.execute(
                "INSERT INTO recipes (id, name, description, is_builtin, settings_json, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
                (r["id"], r["name"], r["description"], json.dumps(r["settings"]), now, now),
            )
    cur_kit = conn.execute("SELECT id FROM brand_kits WHERE id = ?", (DEFAULT_BRAND_KIT["id"],)).fetchone()
    if not cur_kit:
        conn.execute(
            "INSERT INTO brand_kits (id, name, is_default, config_json, created_at, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
            (DEFAULT_BRAND_KIT["id"], DEFAULT_BRAND_KIT["name"], json.dumps(DEFAULT_BRAND_KIT["config"]), now, now),
        )
    conn.commit()
    conn.close()


def _parse_json(val: Optional[str], default: Any) -> Any:
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


def row_to_project(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["curationPref"] = _parse_json(d.pop("curation_pref_json", None), {})
    d["renderPref"] = _parse_json(d.pop("render_pref_json", None), {})
    d["importPref"] = _parse_json(d.pop("import_pref_json", None), {})
    d["transcript"] = _parse_json(d.pop("transcript_json", None), [])
    return d


def row_to_clip(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["viralityBreakdown"] = _parse_json(d.pop("virality_breakdown_json", None), {})
    d["keywords"] = _parse_json(d.pop("keywords_json", None), [])
    d["hashtags"] = _parse_json(d.pop("hashtags_json", None), [])
    d["socialCopy"] = _parse_json(d.pop("social_copy_json", None), {})
    d["editingScript"] = _parse_json(d.pop("editing_script_json", None), {})
    return d


def create_project(
    title: str,
    source_type: str,
    source_url: Optional[str],
    source_path: Optional[str],
    curation_pref: Dict[str, Any],
    render_pref: Dict[str, Any],
    import_pref: Dict[str, Any],
    recipe_id: Optional[str],
    brand_kit_id: Optional[str],
) -> Dict[str, Any]:
    pid = f"proj_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO projects (
            id, title, source_type, source_url, source_path, stage, progress,
            status_message, curation_pref_json, render_pref_json, import_pref_json,
            recipe_id, brand_kit_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'queued', 0, 'Queued for ingestion', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pid, title, source_type, source_url, source_path,
            json.dumps(curation_pref), json.dumps(render_pref), json.dumps(import_pref),
            recipe_id, brand_kit_id, now, now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return row_to_project(row)


def update_project(pid: str, **fields: Any) -> Optional[Dict[str, Any]]:
    col_map = {
        "title": "title",
        "source_path": "source_path",
        "proxy_path": "proxy_path",
        "thumbnail_path": "thumbnail_path",
        "duration_sec": "duration_sec",
        "width": "width",
        "height": "height",
        "fps": "fps",
        "stage": "stage",
        "progress": "progress",
        "status_message": "status_message",
        "error": "error",
        "transcript": ("transcript_json", json.dumps),
        "curationPref": ("curation_pref_json", json.dumps),
        "renderPref": ("render_pref_json", json.dumps),
        "importPref": ("import_pref_json", json.dumps),
    }
    sets: List[str] = []
    vals: List[Any] = []
    for k, v in fields.items():
        if k not in col_map:
            continue
        spec = col_map[k]
        if isinstance(spec, tuple):
            col, fn = spec
            sets.append(f"{col} = ?")
            vals.append(fn(v))
        else:
            sets.append(f"{spec} = ?")
            vals.append(v)
    if not sets:
        return get_project(pid)
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(pid)
    conn = get_conn()
    conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return row_to_project(row) if row else None


def get_project(pid: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return row_to_project(row) if row else None


def list_projects() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        p = row_to_project(r)
        cnt = conn.execute("SELECT COUNT(*) FROM clips WHERE project_id = ?", (p["id"],)).fetchone()[0]
        p["clipCount"] = cnt
        p.pop("transcript", None)
        result.append(p)
    conn.close()
    return result


def delete_project(pid: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_clip(project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    cid = data.get("id") or f"clip_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO clips (
            id, project_id, title, start_sec, end_sec, duration_sec,
            virality_score, virality_breakdown_json, keywords_json, hashtags_json,
            social_copy_json, genre, headline, editing_script_json,
            preview_path, export_path, thumbnail_path, render_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cid, project_id, data["title"], data["start_sec"], data["end_sec"], data["duration_sec"],
            int(data.get("virality_score", 78)),
            json.dumps(data.get("viralityBreakdown", {})),
            json.dumps(data.get("keywords", [])),
            json.dumps(data.get("hashtags", [])),
            json.dumps(data.get("socialCopy", {})),
            data.get("genre", "Auto"),
            data.get("headline", ""),
            json.dumps(data.get("editingScript", {})),
            data.get("preview_path"),
            data.get("export_path"),
            data.get("thumbnail_path"),
            data.get("render_status", "ready"),
            now, now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return row_to_clip(row)


def list_clips(project_id: Optional[str] = None, q: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    if project_id:
        rows = conn.execute(
            "SELECT * FROM clips WHERE project_id = ? ORDER BY virality_score DESC, start_sec ASC",
            (project_id,),
        ).fetchall()
    elif q:
        like = f"%{q}%"
        rows = conn.execute(
            "SELECT * FROM clips WHERE title LIKE ? OR keywords_json LIKE ? OR editing_script_json LIKE ? ORDER BY virality_score DESC",
            (like, like, like),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM clips ORDER BY created_at DESC").fetchall()
    conn.close()
    return [row_to_clip(r) for r in rows]


def get_clip(cid: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return row_to_clip(row) if row else None


def update_clip(cid: str, **fields: Any) -> Optional[Dict[str, Any]]:
    col_map = {
        "title": "title",
        "start_sec": "start_sec",
        "end_sec": "end_sec",
        "duration_sec": "duration_sec",
        "virality_score": "virality_score",
        "headline": "headline",
        "preview_path": "preview_path",
        "export_path": "export_path",
        "thumbnail_path": "thumbnail_path",
        "render_status": "render_status",
        "viralityBreakdown": ("virality_breakdown_json", json.dumps),
        "keywords": ("keywords_json", json.dumps),
        "hashtags": ("hashtags_json", json.dumps),
        "socialCopy": ("social_copy_json", json.dumps),
        "editingScript": ("editing_script_json", json.dumps),
    }
    sets: List[str] = []
    vals: List[Any] = []
    for k, v in fields.items():
        if k not in col_map:
            continue
        spec = col_map[k]
        if isinstance(spec, tuple):
            col, fn = spec
            sets.append(f"{col} = ?")
            vals.append(fn(v))
        else:
            sets.append(f"{spec} = ?")
            vals.append(v)
    if not sets:
        return get_clip(cid)
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(cid)
    conn = get_conn()
    conn.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return row_to_clip(row) if row else None


def delete_clips_for_project(pid: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM clips WHERE project_id = ?", (pid,))
    conn.commit()
    conn.close()


def list_brand_kits() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM brand_kits ORDER BY is_default DESC, created_at ASC").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["is_default"] = bool(d["is_default"])
        d["config"] = _parse_json(d.pop("config_json"), {})
        res.append(d)
    return res


def save_brand_kit(kit_id: Optional[str], name: str, config: Dict[str, Any], is_default: bool = False) -> Dict[str, Any]:
    kid = kit_id or f"kit_{uuid.uuid4().hex[:8]}"
    now = _now()
    conn = get_conn()
    if is_default:
        conn.execute("UPDATE brand_kits SET is_default = 0")
    existing = conn.execute("SELECT id FROM brand_kits WHERE id = ?", (kid,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE brand_kits SET name = ?, is_default = ?, config_json = ?, updated_at = ? WHERE id = ?",
            (name, 1 if is_default else 0, json.dumps(config), now, kid),
        )
    else:
        conn.execute(
            "INSERT INTO brand_kits (id, name, is_default, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kid, name, 1 if is_default else 0, json.dumps(config), now, now),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM brand_kits WHERE id = ?", (kid,)).fetchone()
    conn.close()
    d = dict(row)
    d["is_default"] = bool(d["is_default"])
    d["config"] = _parse_json(d.pop("config_json"), {})
    return d


def list_recipes() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM recipes ORDER BY is_builtin DESC, created_at ASC").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["is_builtin"] = bool(d["is_builtin"])
        d["settings"] = _parse_json(d.pop("settings_json"), {})
        res.append(d)
    return res


def save_recipe(recipe_id: Optional[str], name: str, description: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    rid = recipe_id or f"recipe_{uuid.uuid4().hex[:8]}"
    now = _now()
    conn = get_conn()
    existing = conn.execute("SELECT id, is_builtin FROM recipes WHERE id = ?", (rid,)).fetchone()
    if existing and not existing["is_builtin"]:
        conn.execute(
            "UPDATE recipes SET name = ?, description = ?, settings_json = ?, updated_at = ? WHERE id = ?",
            (name, description, json.dumps(settings), now, rid),
        )
    else:
        if existing and existing["is_builtin"]:
            rid = f"recipe_{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO recipes (id, name, description, is_builtin, settings_json, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
            (rid, name, description, json.dumps(settings), now, now),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone()
    conn.close()
    d = dict(row)
    d["is_builtin"] = bool(d["is_builtin"])
    d["settings"] = _parse_json(d.pop("settings_json"), {})
    return d


def delete_recipe(rid: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM recipes WHERE id = ? AND is_builtin = 0", (rid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def list_collections() -> List[Dict[str, Any]]:
    conn = get_conn()
    cols = conn.execute("SELECT * FROM collections ORDER BY created_at DESC").fetchall()
    res = []
    for c in cols:
        d = dict(c)
        items = conn.execute("SELECT clip_id FROM collection_items WHERE collection_id = ?", (d["id"],)).fetchall()
        d["clipIds"] = [i["clip_id"] for i in items]
        res.append(d)
    conn.close()
    return res


def create_collection(name: str) -> Dict[str, Any]:
    cid = f"col_{uuid.uuid4().hex[:8]}"
    now = _now()
    conn = get_conn()
    conn.execute("INSERT INTO collections (id, name, created_at) VALUES (?, ?, ?)", (cid, name, now))
    conn.commit()
    conn.close()
    return {"id": cid, "name": name, "created_at": now, "clipIds": []}


def add_to_collection(col_id: str, clip_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO collection_items (collection_id, clip_id, added_at) VALUES (?, ?, ?)",
        (col_id, clip_id, _now()),
    )
    conn.commit()
    conn.close()


def remove_from_collection(col_id: str, clip_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM collection_items WHERE collection_id = ? AND clip_id = ?", (col_id, clip_id))
    conn.commit()
    conn.close()


def list_scheduled_posts() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.*, c.title AS clip_title, c.thumbnail_path AS clip_thumbnail, c.preview_path AS clip_preview
        FROM scheduled_posts s
        JOIN clips c ON c.id = s.clip_id
        ORDER BY s.scheduled_at ASC
        """
    ).fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["hashtags"] = _parse_json(d.pop("hashtags_json", None), [])
        res.append(d)
    return res


def create_scheduled_post(clip_id: str, platform: str, title: str, copy: str, hashtags: List[str], scheduled_at: str, status: str = "scheduled") -> Dict[str, Any]:
    sid = f"post_{uuid.uuid4().hex[:8]}"
    now = _now()
    conn = get_conn()
    conn.execute(
        "INSERT INTO scheduled_posts (id, clip_id, platform, title, copy, hashtags_json, scheduled_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, clip_id, platform, title, copy, json.dumps(hashtags), scheduled_at, status, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?", (sid,)).fetchone()
    conn.close()
    d = dict(row)
    d["hashtags"] = _parse_json(d.pop("hashtags_json", None), [])
    return d


def delete_scheduled_post(sid: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_credit_wallet() -> Dict[str, Any]:
    conn = get_conn()
    row = conn.execute("SELECT balance, updated_at FROM credit_wallet WHERE id = 'default'").fetchone()
    txns = conn.execute("SELECT * FROM credit_transactions ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return {
        "balance": int(row["balance"]) if row else 1000,
        "updatedAt": row["updated_at"] if row else _now(),
        "transactions": [dict(t) for t in txns],
    }


def record_credit_change(
    action: str,
    description: str,
    amount: int,
    project_id: Optional[str] = None,
    clip_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Positive amount adds credits; negative amount deducts credits (floored at 0)."""
    now = _now()
    conn = get_conn()
    row = conn.execute("SELECT balance FROM credit_wallet WHERE id = 'default'").fetchone()
    cur_bal = int(row["balance"]) if row else 1000
    new_bal = max(0, cur_bal + amount)
    conn.execute("UPDATE credit_wallet SET balance = ?, updated_at = ? WHERE id = 'default'", (new_bal, now))
    txn_id = f"txn_{uuid.uuid4().hex[:10]}"
    conn.execute(
        "INSERT INTO credit_transactions (id, action, description, amount, balance_after, project_id, clip_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, action, description, amount, new_bal, project_id, clip_id, now),
    )
    conn.commit()
    conn.close()
    return {"balance": new_bal, "amount": amount, "txnId": txn_id}
