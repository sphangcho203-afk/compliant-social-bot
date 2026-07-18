from __future__ import annotations

import html
import sqlite3
from pathlib import Path
from typing import Any


def load_assets(database_path: Path, query: str = "", tag: str = "") -> dict[str, Any]:
    if not database_path.exists():
        return {"assets": [], "query": query, "tag": tag, "stats": {"total": 0, "favorites": 0}}

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(assets)").fetchall()
        }
        if "content_hash" not in columns:
            return {
                "assets": [],
                "query": query,
                "tag": tag,
                "stats": {"total": 0, "favorites": 0},
                "notice": "Run social-bot-assets once to initialize the asset library.",
            }

        clauses = ["1=1"]
        params: list[Any] = []
        if query.strip():
            needle = f"%{query.strip().lower()}%"
            clauses.append(
                "(LOWER(COALESCE(a.display_name, '')) LIKE ? OR LOWER(a.local_path) LIKE ?)"
            )
            params.extend([needle, needle])
        if tag.strip():
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags t2 WHERE t2.asset_id=a.id "
                "AND t2.tag=? COLLATE NOCASE)"
            )
            params.append(tag.strip().lower())

        rows = connection.execute(
            f"""
            SELECT a.id, COALESCE(a.display_name, a.local_path) AS display_name,
                   a.local_path, a.media_type, a.file_size, a.license, a.favorite,
                   a.status, a.created_at, a.updated_at,
                   COUNT(DISTINCT p.id) AS usage_count,
                   GROUP_CONCAT(DISTINCT t.tag) AS tags
            FROM assets a
            LEFT JOIN publications p ON p.asset_id=a.id
            LEFT JOIN asset_tags t ON t.asset_id=a.id
            WHERE {' AND '.join(clauses)}
            GROUP BY a.id
            ORDER BY a.favorite DESC, a.updated_at DESC, a.id DESC
            LIMIT 200
            """,
            params,
        ).fetchall()
        stats_row = connection.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) AS favorites FROM assets"
        ).fetchone()
        return {
            "assets": [dict(row) for row in rows],
            "query": query,
            "tag": tag,
            "stats": {
                "total": int(stats_row["total"] or 0),
                "favorites": int(stats_row["favorites"] or 0),
            },
        }
    finally:
        connection.close()


def render_assets(data: dict[str, Any]) -> str:
    rows = []
    for asset in data["assets"]:
        favorite = "★" if asset["favorite"] else ""
        size_mb = int(asset["file_size"] or 0) / (1024 * 1024)
        rows.append(
            "<tr>"
            f"<td>{asset['id']}</td>"
            f"<td>{favorite} {html.escape(str(asset['display_name']))}</td>"
            f"<td>{html.escape(str(asset['media_type']))}</td>"
            f"<td>{size_mb:.2f} MB</td>"
            f"<td>{html.escape(str(asset['tags'] or ''))}</td>"
            f"<td>{asset['usage_count']}</td>"
            f"<td>{html.escape(str(asset['license']))}</td>"
            f"<td>{html.escape(str(asset['local_path']))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="8" class="empty">No matching assets.</td></tr>'
    notice = data.get("notice")
    notice_html = f'<div class="notice">{html.escape(str(notice))}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Asset Library</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui,sans-serif; }}
body {{ margin:0;background:#0b1020;color:#eef2ff; }}
main {{ max-width:1200px;margin:auto;padding:20px; }}
a {{ color:#9fc2ff; }}
.grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0; }}
.card,section {{ background:#151c33;border:1px solid #283252;border-radius:14px;padding:16px; }}
.value {{ font-size:1.7rem;font-weight:700;margin-top:6px; }}
.muted,.empty {{ color:#9aa5c4; }}
form {{ display:flex;gap:8px;flex-wrap:wrap;margin:16px 0; }}
input,button {{ font:inherit;padding:10px;border-radius:8px;border:1px solid #39476f;background:#0f162b;color:#eef2ff; }}
button {{ background:#344c91;font-weight:650; }}
table {{ width:100%;border-collapse:collapse;font-size:.88rem; }}
th,td {{ text-align:left;padding:9px 7px;border-bottom:1px solid #283252;word-break:break-word;vertical-align:top; }}
section {{ overflow-x:auto; }} .notice {{ padding:12px;border-radius:10px;background:#202a49; }}
</style></head><body><main>
<h1>Asset Library</h1>
<div class="muted"><a href="/">Dashboard</a> · <a href="/history">Job history</a> · read-only media inventory</div>
{notice_html}
<div class="grid">
<div class="card"><div class="muted">Assets</div><div class="value">{data['stats']['total']}</div></div>
<div class="card"><div class="muted">Favorites</div><div class="value">{data['stats']['favorites']}</div></div>
<div class="card"><div class="muted">Matches</div><div class="value">{len(data['assets'])}</div></div>
</div>
<form method="get" action="/assets">
<input name="q" value="{html.escape(str(data['query']))}" placeholder="Search name or path">
<input name="tag" value="{html.escape(str(data['tag']))}" placeholder="Tag">
<button type="submit">Search</button><a href="/assets">Clear</a>
</form>
<section><table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Size</th><th>Tags</th><th>Uses</th><th>License</th><th>Path</th></tr></thead><tbody>{body}</tbody></table></section>
</main></body></html>"""
