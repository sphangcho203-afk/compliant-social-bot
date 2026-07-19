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
                   MAX(p.published_at) AS last_published_at,
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
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) AS favorites FROM assets"
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


def _queue_form(asset: dict[str, Any]) -> str:
    asset_id = int(asset["id"])
    title = Path(str(asset["display_name"])).stem[:100]
    usage_count = int(asset["usage_count"] or 0)
    reuse = ""
    if usage_count:
        reuse = f"""
        <label class="check warning">
          <input type="checkbox" name="allow_reuse" value="1" required>
          Confirm reuse: this asset already has {usage_count} publication receipt(s).
        </label>
        """
    return f"""
    <form method="post" action="/assets/{asset_id}/queue" class="queue-form">
      <label>Title
        <input name="title" required maxlength="100" value="{html.escape(title)}">
      </label>
      <label>Caption
        <textarea name="caption" rows="3" placeholder="Optional description"></textarea>
      </label>
      <label>Privacy
        <select name="privacy">
          <option value="unlisted">unlisted</option>
          <option value="private">private</option>
          <option value="public">public</option>
        </select>
      </label>
      <label>Run after
        <input name="run_after" placeholder="2026-07-20T18:00:00+05:30">
      </label>
      {reuse}
      <label>Control token
        <input name="token" type="password" required autocomplete="off">
      </label>
      <button type="submit">Queue for approval</button>
    </form>
    """


def _asset_card(asset: dict[str, Any], controls_enabled: bool) -> str:
    favorite = "★ " if asset["favorite"] else ""
    size_mb = int(asset["file_size"] or 0) / (1024 * 1024)
    usage_count = int(asset["usage_count"] or 0)
    usage_class = "warning" if usage_count else "muted"
    tags = str(asset["tags"] or "")
    tag_html = "".join(
        f'<span class="tag">{html.escape(tag.strip())}</span>'
        for tag in tags.split(",")
        if tag.strip()
    ) or '<span class="muted">No tags</span>'
    last_used = html.escape(str(asset["last_published_at"] or "Never"))
    controls = (
        _queue_form(asset)
        if controls_enabled
        else '<div class="control-note">Start the dashboard with a control token to queue this asset.</div>'
    )
    return f"""
    <article class="asset-card">
      <div class="asset-head">
        <div>
          <div class="eyebrow">Asset #{int(asset['id'])}</div>
          <h2>{favorite}{html.escape(str(asset['display_name']))}</h2>
        </div>
        <span class="status">{html.escape(str(asset['status']))}</span>
      </div>
      <div class="meta-grid">
        <div><span>Type</span><strong>{html.escape(str(asset['media_type']))}</strong></div>
        <div><span>Size</span><strong>{size_mb:.2f} MB</strong></div>
        <div><span>License</span><strong>{html.escape(str(asset['license']))}</strong></div>
        <div><span>Uses</span><strong class="{usage_class}">{usage_count}</strong></div>
      </div>
      <div class="tags">{tag_html}</div>
      <div class="muted">Last receipt: {last_used}</div>
      <details>
        <summary>Local path</summary>
        <code>{html.escape(str(asset['local_path']))}</code>
      </details>
      {controls}
    </article>
    """


def render_assets(
    data: dict[str, Any],
    *,
    controls_enabled: bool = False,
    message: str = "",
) -> str:
    body = "".join(_asset_card(asset, controls_enabled) for asset in data["assets"])
    if not body:
        body = '<div class="empty asset-card">No matching assets.</div>'
    notice = data.get("notice")
    notice_html = f'<div class="notice">{html.escape(str(notice))}</div>' if notice else ""
    message_html = f'<div class="notice">{html.escape(message)}</div>' if message else ""
    control_notice = (
        "Queue controls are enabled. New jobs still require separate approval."
        if controls_enabled
        else "Asset inventory is read-only. Restart with --control-token to enable queue forms."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Asset Library</title>
<style>
:root {{ color-scheme:dark;font-family:system-ui,sans-serif; }}
* {{ box-sizing:border-box; }}
body {{ margin:0;background:#0b1020;color:#eef2ff; }}
main {{ max-width:1200px;margin:auto;padding:18px; }}
a {{ color:#9fc2ff; }} h1 {{ margin-bottom:4px; }}
.grid {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:18px 0; }}
.card,.asset-card {{ background:#151c33;border:1px solid #283252;border-radius:14px;padding:16px; }}
.value {{ font-size:1.7rem;font-weight:700;margin-top:6px; }}
.muted,.empty {{ color:#9aa5c4; }}
.notice,.control-note {{ margin:14px 0;padding:12px;border-radius:10px;background:#202a49; }}
.filter-form {{ display:grid;grid-template-columns:2fr 1fr auto auto;gap:8px;margin:16px 0;align-items:center; }}
input,textarea,select,button {{ width:100%;font:inherit;padding:10px;border-radius:8px;border:1px solid #39476f;background:#0f162b;color:#eef2ff; }}
button {{ cursor:pointer;background:#344c91;font-weight:650; }}
.asset-list {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:14px; }}
.asset-head {{ display:flex;justify-content:space-between;gap:12px;align-items:flex-start; }}
.asset-head h2 {{ margin:3px 0 12px;font-size:1.1rem;word-break:break-word; }}
.eyebrow,.status {{ color:#9aa5c4;text-transform:uppercase;letter-spacing:.08em;font-size:.72rem; }}
.status {{ border:1px solid #39476f;border-radius:999px;padding:5px 8px; }}
.meta-grid {{ display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0; }}
.meta-grid div {{ display:grid;gap:3px;background:#0f162b;border-radius:9px;padding:9px; }}
.meta-grid span {{ color:#9aa5c4;font-size:.78rem; }}
.warning {{ color:#ffd58a; }}
.tags {{ display:flex;flex-wrap:wrap;gap:6px;margin:10px 0; }}
.tag {{ background:#26345f;border-radius:999px;padding:4px 8px;font-size:.78rem; }}
details {{ margin:12px 0; }} code {{ display:block;margin-top:8px;word-break:break-all;color:#bac3de; }}
.queue-form {{ display:grid;gap:10px;margin-top:14px;padding-top:14px;border-top:1px solid #283252; }}
.queue-form label {{ display:grid;gap:5px;color:#bac3de;font-size:.88rem; }}
.check {{ grid-template-columns:auto 1fr!important;align-items:start; }}
.check input {{ width:auto;margin-top:3px; }}
@media (max-width:640px) {{
  main {{ padding:14px; }}
  .filter-form {{ grid-template-columns:1fr; }}
  .asset-list {{ grid-template-columns:1fr; }}
  .asset-card {{ padding:14px; }}
}}
</style></head><body><main>
<h1>Asset Library</h1>
<div class="muted"><a href="/">Dashboard</a> · <a href="/history">Job history</a> · managed media inventory</div>
{message_html}{notice_html}
<div class="notice">{html.escape(control_notice)}</div>
<div class="grid">
<div class="card"><div class="muted">Assets</div><div class="value">{data['stats']['total']}</div></div>
<div class="card"><div class="muted">Favorites</div><div class="value">{data['stats']['favorites']}</div></div>
<div class="card"><div class="muted">Matches</div><div class="value">{len(data['assets'])}</div></div>
</div>
<form method="get" action="/assets" class="filter-form">
<input name="q" value="{html.escape(str(data['query']))}" placeholder="Search name or path">
<input name="tag" value="{html.escape(str(data['tag']))}" placeholder="Tag">
<button type="submit">Search</button><a href="/assets">Clear</a>
</form>
<section class="asset-list">{body}</section>
</main></body></html>"""
