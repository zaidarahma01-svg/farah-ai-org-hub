#!/usr/bin/env python3
"""
Farah Gold AI Organization Hub
Coordination platform for multi-agent operations.

Governance model: "advise, decide, verify"
  - Zaid Rahma: Owner/Chairman — final authority, authorizes high-risk work,
    overrides blocks with documented exception.
  - Layla (Muse): Coordinator — coordinates technical work within delegated
    authority. No routine board votes (the old 8/1/1 split was theater).
  - ChatGPT Dot: Technical Advisor — advisory input; narrow blocking authority
    on documented security/correctness issues (must cite evidence).
  - Grok Bot: QA Advisor — advisory input; narrow blocking authority on
    mandatory test failures (must cite the specific failed test).

Risk tiers gate execution:
  - low:    research, drafts, local tests → Coordinator executes autonomously
  - medium: theme architecture, major UI, font geometry → specialist review
            + staging validation before completion
  - high:   checkout logic, live pricing, refunds, customer data, production
            manufacturing files → chairman authorization + mandatory checks
"""
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, render_template_string, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "org.db")
TOKENS_PATH = os.path.join(BASE_DIR, "TOKENS.md")

app = Flask(__name__)

@app.after_request
def _security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return resp

RISK_TIERS = ("low", "medium", "high")
VERDICTS = ("approve", "revise", "blocked")
TASK_STATUSES = ("pending", "in_progress", "completed", "failed")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS members (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        title TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'advisor',
        domain TEXT,
        api_token TEXT NOT NULL UNIQUE,
        is_chairman INTEGER NOT NULL DEFAULT 0
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        accountable TEXT NOT NULL DEFAULT 'layla',
        assigned_reviewer TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        priority TEXT NOT NULL DEFAULT 'normal',
        risk_tier TEXT NOT NULL DEFAULT 'low',
        environment TEXT NOT NULL DEFAULT 'staging',
        acceptance_criteria TEXT NOT NULL DEFAULT '',
        evidence_required TEXT NOT NULL DEFAULT '',
        evidence_submitted TEXT,
        created_by TEXT NOT NULL DEFAULT 'layla',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        result TEXT,
        blocked INTEGER NOT NULL DEFAULT 0,
        block_info TEXT,
        authorized_by TEXT,
        authorized_at TEXT,
        progress_pct INTEGER NOT NULL DEFAULT 0,
        progress_msg TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (accountable) REFERENCES members(id),
        FOREIGN KEY (assigned_reviewer) REFERENCES members(id),
        FOREIGN KEY (created_by) REFERENCES members(id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        reviewer_id TEXT NOT NULL,
        verdict TEXT NOT NULL,
        evidence TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id),
        FOREIGN KEY (reviewer_id) REFERENCES members(id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT ''
    )""")
    # Drop legacy governance tables from the voting era
    db.execute("DROP TABLE IF EXISTS proposals")
    db.execute("DROP TABLE IF EXISTS votes")
    # Migrate: add progress columns to tasks if missing
    cols = [r[1] for r in db.execute("PRAGMA table_info(tasks)").fetchall()]
    if "progress_pct" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN progress_pct INTEGER NOT NULL DEFAULT 0")
    if "progress_msg" not in cols:
        db.execute("ALTER TABLE tasks ADD COLUMN progress_msg TEXT NOT NULL DEFAULT ''")
    db.execute("""CREATE TABLE IF NOT EXISTS recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        author_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        response TEXT NOT NULL DEFAULT '',
        responded_by TEXT,
        created_at TEXT NOT NULL,
        responded_at TEXT,
        FOREIGN KEY (author_id) REFERENCES members(id)
    )""")
    db.commit()
    db.close()

def read_existing_tokens():
    """TOKENS.md is the source of truth — never rotate tokens on re-seed."""
    tokens = {}
    if os.path.exists(TOKENS_PATH):
        with open(TOKENS_PATH) as f:
            for m in re.finditer(r"- \*\*(\w+)\*\*: `([a-f0-9]+)`", f.read()):
                tokens[m.group(1)] = m.group(2)
    return tokens

def _sync_names(db):
    """Update member display names/titles from code without touching tokens."""
    updates = [
        ("victoria", "Rumi", "Executor (Muse)"),
        ("grok", "Jessica", "QA Advisor (Grok)"),
    ]
    for mid, name, title in updates:
        db.execute(
            "UPDATE members SET name=?, title=? WHERE id=?",
            (name, title, mid),
        )
    db.commit()

def seed_db():
    db = sqlite3.connect(DB_PATH)
    existing = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    if existing > 0:
        # Sync display names/titles from code even when members exist
        _sync_names(db)
        db.close()
        return {}
    old_tokens = read_existing_tokens()
    now = datetime.now(timezone.utc).isoformat()
    members = [
        # id, name, title, role, domain, chairman
        ("zaid",  "Zaid Rahma",  "Owner / Chairman",      "chairman", None,        1),
        ("layla", "Layla",       "Coordinator (Muse)",            "coordinator",      None,        0),
        ("victoria", "Rumi",      "Executor (Muse)",        "executor",   None,        0),
        ("nidhal",   "Nidhal",   "Executor (Muse)",        "executor",   None,        0),
        ("dot",   "ChatGPT Dot", "Technical Advisor",     "advisor",  "technical", 0),
        ("grok",  "Jessica",     "QA Advisor (Grok)",      "advisor",  "qa",        0),
    ]
    tokens = {}
    # Persistent tokens: HUB_TOKENS env var (JSON map of member_id -> token)
    # survives Render redeploys. Falls back to generated tokens on first run.
    _env_tokens = {}
    try:
        import json as _json
        _env_tokens = _json.loads(os.environ.get("HUB_TOKENS", "{}"))
    except Exception:
        pass
    for mid, name, title, role, domain, chairman in members:
        token = _env_tokens.get(mid) or old_tokens.get(mid, secrets.token_hex(32))
        db.execute(
            "INSERT INTO members (id, name, title, role, domain, api_token, is_chairman)"
            " VALUES (?,?,?,?,?,?,?)",
            (mid, name, title, role, domain, token, chairman),
        )
        tokens[mid] = token
    db.execute(
        "INSERT INTO activity (ts, actor, action, details) VALUES (?,?,?,?)",
        (now, "system", "org_initialized",
         "Hub governance: advise/decide/verify. Coordinator decides operational matters; advisors review; "
         "chairman authorizes high-risk work and overrides blocks."),
    )
    db.commit()
    db.close()
    return tokens

def log_activity(actor, action, details=""):
    db = get_db()
    db.execute(
        "INSERT INTO activity (ts, actor, action, details) VALUES (?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), actor, action, details),
    )
    db.commit()

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_member_by_token(token):
    if not token:
        return None
    db = get_db()
    row = db.execute("SELECT * FROM members WHERE api_token = ?", (token,)).fetchone()
    return dict(row) if row else None

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
        member = get_member_by_token(token)
        if not member:
            return jsonify({"error": "unauthorized"}), 401
        g.member = member
        return f(*args, **kwargs)
    return decorated

def is_blocked(db, task_id):
    """A task is blocked if any reviewer's latest verdict is 'blocked'."""
    rows = db.execute(
        """SELECT reviewer_id, verdict FROM reviews
           WHERE task_id = ? ORDER BY id DESC""", (task_id,)).fetchall()
    seen = set()
    for r in rows:
        if r["reviewer_id"] not in seen:
            seen.add(r["reviewer_id"])
            if r["verdict"] == "blocked":
                return True
    return False

def review_count(db, task_id):
    return db.execute(
        "SELECT COUNT(DISTINCT reviewer_id) FROM reviews WHERE task_id = ?",
        (task_id,)).fetchone()[0]

# ---------------------------------------------------------------------------
# API — Tasks
# ---------------------------------------------------------------------------

@app.route("/api/tasks/pending", methods=["GET"])
@require_auth
def api_pending_tasks():
    agent = request.args.get("agent", g.member["id"])
    db = get_db()
    rows = db.execute(
        "SELECT * FROM tasks WHERE accountable = ? AND status IN ('pending','in_progress')"
        " ORDER BY created_at",
        (agent,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/tasks", methods=["GET"])
@require_auth
def api_list_tasks():
    db = get_db()
    q = "SELECT * FROM tasks WHERE 1=1"
    params = []
    for key in ("status", "risk_tier", "accountable", "assigned_reviewer"):
        val = request.args.get(key)
        if val:
            q += f" AND {key} = ?"
            params.append(val)
    q += " ORDER BY created_at DESC LIMIT 100"
    rows = db.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/tasks/<int:task_id>", methods=["GET"])
@require_auth
def api_get_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    t = dict(task)
    t["reviews"] = [dict(r) for r in db.execute(
        "SELECT * FROM reviews WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()]
    return jsonify(t)

@app.route("/api/tasks", methods=["POST"])
@require_auth
def api_create_task():
    # Only coordinator and chairman can create tasks (per charter)
    if g.member["role"] not in ("coordinator",) and not g.member["is_chairman"]:
        return jsonify({"error": "only coordinator or chairman can create tasks"}), 403
    data = request.get_json(force=True)
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    risk = data.get("risk_tier", "low")
    if risk not in RISK_TIERS:
        return jsonify({"error": f"risk_tier must be one of {RISK_TIERS}"}), 400
    env = data.get("environment", "staging")
    if env not in ("staging", "production"):
        return jsonify({"error": "environment must be staging or production"}), 400
    db = get_db()
    for mid, label in ((data.get("accountable", "layla"), "accountable"),
                       (data.get("assigned_reviewer"), "assigned_reviewer")):
        if mid and not db.execute("SELECT 1 FROM members WHERE id = ?", (mid,)).fetchone():
            return jsonify({"error": f"unknown member in {label}: {mid}"}), 400
    if risk == "high" and env != "production":
        pass  # high-risk work is defined by impact, not environment
    now = datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """INSERT INTO tasks
           (title, description, accountable, assigned_reviewer, status, priority,
            risk_tier, environment, acceptance_criteria, evidence_required,
            created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (title, data.get("description", ""), data.get("accountable", "layla"),
         data.get("assigned_reviewer"), "pending", data.get("priority", "normal"),
         risk, env, data.get("acceptance_criteria", ""),
         data.get("evidence_required", ""), g.member["id"], now, now),
    )
    task_id = cur.lastrowid
    db.commit()
    log_activity(g.member["id"], "task_created",
                 f"Task #{task_id} [{risk}/{env}] '{title}' accountable: {data.get('accountable','layla')}"
                 + (f", reviewer: {data.get('assigned_reviewer')}" if data.get("assigned_reviewer") else ""))
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return jsonify(dict(task)), 201

@app.route("/api/tasks/<int:task_id>/start", methods=["POST"])
@require_auth
def api_start_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if task["accountable"] != g.member["id"] and g.member["id"] not in ("layla", "zaid"):
        return jsonify({"error": "you are not accountable for this task"}), 403
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?", (now, task_id))
    db.commit()
    log_activity(g.member["id"], "task_started", f"Task #{task_id} started")
    return jsonify({"ok": True, "status": "in_progress"})

def _completion_gate(db, task, member):
    """Returns (allowed: bool, reason: str). Enforces risk-tier release gates."""
    if task["blocked"] and not member["is_chairman"]:
        return False, "task is blocked on evidence — resolve the block or escalate to chairman for override"
    if task["risk_tier"] == "medium" and review_count(db, task["id"]) == 0:
        return False, "medium-risk tasks require at least one specialist review before completion"
    if task["risk_tier"] == "high":
        if review_count(db, task["id"]) == 0:
            return False, "high-risk tasks require at least one specialist review before completion"
        if not task["authorized_by"]:
            return False, "high-risk tasks require chairman authorization (POST /api/tasks/{id}/authorize)"
    return True, ""

@app.route("/api/tasks/<int:task_id>/progress", methods=["POST"])
@require_auth
def api_task_progress(task_id):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if task["accountable"] != g.member["id"] and g.member["id"] not in ("layla", "zaid"):
        return jsonify({"error": "you are not accountable for this task"}), 403
    pct = max(0, min(100, int(data.get("percent", 0))))
    msg = str(data.get("message", ""))[:280]
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE tasks SET progress_pct=?, progress_msg=?, updated_at=? WHERE id=?",
        (pct, msg, now, task_id),
    )
    db.commit()
    return jsonify({"ok": True, "percent": pct})

@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@require_auth
def api_complete_task(task_id):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if task["accountable"] != g.member["id"] and g.member["id"] not in ("layla", "zaid"):
        return jsonify({"error": "you are not accountable for this task"}), 403
    ok, reason = _completion_gate(db, task, g.member)
    if not ok:
        return jsonify({"error": reason}), 403
    if task["evidence_required"] and not data.get("evidence"):
        return jsonify({"error": f"this task requires evidence: {task['evidence_required']}"}), 400
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "UPDATE tasks SET status='completed', result=?, evidence_submitted=?, completed_at=?, updated_at=? WHERE id=?",
        (data.get("result", ""), data.get("evidence"), now, now, task_id),
    )
    db.commit()
    log_activity(g.member["id"], "task_completed",
                 f"Task #{task_id} [{task['risk_tier']}] '{task['title']}' completed")
    return jsonify({"ok": True, "status": "completed"})

@app.route("/api/tasks/<int:task_id>/fail", methods=["POST"])
@require_auth
def api_fail_task(task_id):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if task["accountable"] != g.member["id"] and g.member["id"] not in ("layla", "zaid"):
        return jsonify({"error": "you are not accountable for this task"}), 403
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE tasks SET status='failed', result=?, updated_at=? WHERE id=?",
               (data.get("error", "no reason given"), now, task_id))
    db.commit()
    log_activity(g.member["id"], "task_failed",
                 f"Task #{task_id} '{task['title']}' failed: {data.get('error','')}")
    return jsonify({"ok": True, "status": "failed"})

# ---------------------------------------------------------------------------
# API — Advisory reviews (replaces voting)
# ---------------------------------------------------------------------------

@app.route("/api/tasks/<int:task_id>/review", methods=["POST"])
@require_auth
def api_review_task(task_id):
    data = request.get_json(force=True)
    verdict = data.get("verdict", "").lower()
    if verdict not in VERDICTS:
        return jsonify({"error": f"verdict must be one of {VERDICTS}"}), 400
    evidence = data.get("evidence", "").strip()
    if verdict == "blocked" and not evidence:
        return jsonify({"error": "a block must cite evidence — what failed, and where"}), 400
    if g.member["role"] not in ("advisor", "coordinator", "chairman"):
        return jsonify({"error": "only advisors, coordinator, or chairman can review"}), 403
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if task["status"] in ("completed", "failed"):
        return jsonify({"error": f"task is {task['status']} — reviews are closed"}), 400
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO reviews (task_id, reviewer_id, verdict, evidence, created_at) VALUES (?,?,?,?,?)",
        (task_id, g.member["id"], verdict, evidence, now),
    )
    blocked = is_blocked(db, task_id)
    db.execute("UPDATE tasks SET blocked=?, updated_at=? WHERE id=?",
               (1 if blocked else 0, now, task_id))
    if verdict == "blocked":
        db.execute("UPDATE tasks SET block_info=? WHERE id=?",
                   (f"{g.member['id']}: {evidence}", task_id))
    db.commit()
    log_activity(g.member["id"], f"review_{verdict}",
                 f"Task #{task_id}: {g.member['id']} → {verdict}"
                 + (f" — evidence: {evidence[:200]}" if evidence else "")
                 + (" — TASK BLOCKED" if blocked else ""))
    return jsonify({"ok": True, "verdict": verdict, "task_blocked": blocked})

@app.route("/api/tasks/<int:task_id>/authorize", methods=["POST"])
@require_auth
def api_authorize_task(task_id):
    """Chairman authorizes a high-risk task. Required before completion."""
    if not g.member["is_chairman"]:
        return jsonify({"error": "only the chairman can authorize high-risk tasks"}), 403
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE tasks SET authorized_by=?, authorized_at=?, updated_at=? WHERE id=?",
               (g.member["id"], now, now, task_id))
    db.commit()
    log_activity(g.member["id"], "task_authorized",
                 f"Task #{task_id} [{task['risk_tier']}] authorized by chairman"
                 + (f": {data.get('note','')}" if data.get("note") else ""))
    return jsonify({"ok": True, "authorized_by": g.member["id"]})

@app.route("/api/tasks/<int:task_id>/override", methods=["POST"])
@require_auth
def api_override_block(task_id):
    """Chairman overrides an evidence block with a documented exception."""
    if not g.member["is_chairman"]:
        return jsonify({"error": "only the chairman can override a block"}), 403
    data = request.get_json(force=True, silent=True) or {}
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"error": "override requires a documented reason"}), 400
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "task not found"}), 404
    if not task["blocked"]:
        return jsonify({"error": "task is not blocked — nothing to override"}), 400
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE tasks SET blocked=0, block_info=?, updated_at=? WHERE id=?",
               (f"chairman override: {reason}", now, task_id))
    db.commit()
    log_activity(g.member["id"], "block_overridden",
                 f"Task #{task_id}: chairman override — {reason}")
    return jsonify({"ok": True, "blocked": False})

# ---------------------------------------------------------------------------
# API — misc
# ---------------------------------------------------------------------------

@app.route("/api/activity", methods=["GET"])
@require_auth
def api_activity():
    try:
        limit = int(request.args.get("limit", 50))
    except (ValueError, TypeError):
        return jsonify({"error": "limit must be an integer"}), 400
    limit = max(1, min(limit, 200))
    db = get_db()
    rows = db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/me", methods=["GET"])
@require_auth
def api_me():
    m = dict(g.member)
    m.pop("api_token", None)
    return jsonify(m)

# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@app.route("/api/recommendations", methods=["POST"])
@require_auth
def api_create_recommendation():
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    now = datetime.now(timezone.utc).isoformat()
    db = get_db()
    cur = db.execute(
        "INSERT INTO recommendations (title, body, author_id, status, created_at)"
        " VALUES (?,?,?,?,?)",
        (title, body, g.member["id"], "pending", now),
    )
    rid = cur.lastrowid
    db.commit()
    log_activity(g.member["id"], "recommendation_submitted", f"Recommendation #{rid}: {title}")
    return jsonify({"ok": True, "id": rid, "status": "pending"})

@app.route("/api/recommendations", methods=["GET"])
@require_auth
def api_list_recommendations():
    status = request.args.get("status")
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM recommendations WHERE status=? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM recommendations ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/recommendations/<int:rec_id>/respond", methods=["POST"])
@require_auth
def api_respond_recommendation(rec_id):
    # Only coordinator and chairman can respond to recommendations
    if g.member["role"] not in ("coordinator",) and not g.member["is_chairman"]:
        return jsonify({"error": "only coordinator or chairman can respond"}), 403
    data = request.get_json(force=True, silent=True) or {}
    response = str(data.get("response", "")).strip()
    new_status = str(data.get("status", "acknowledged")).strip()
    if new_status not in ("acknowledged", "accepted", "rejected", "deferred"):
        return jsonify({"error": "invalid status"}), 400
    now = datetime.now(timezone.utc).isoformat()
    db = get_db()
    rec = db.execute("SELECT * FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if not rec:
        return jsonify({"error": "not found"}), 404
    db.execute(
        "UPDATE recommendations SET status=?, response=?, responded_by=?, responded_at=?"
        " WHERE id=?",
        (new_status, response, g.member["id"], now, rec_id),
    )
    db.commit()
    log_activity(g.member["id"], "recommendation_responded",
                 f"Recommendation #{rec_id} -> {new_status}")
    return jsonify({"ok": True, "status": new_status})

# ---------------------------------------------------------------------------
# Operating charter
# ---------------------------------------------------------------------------

CHARTER_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Operating Charter — Farah Gold AI Organization Hub</title>
<style>
  :root { --gold:#c9a227; --bg:#0d0b08; --card:#171310; --text:#e8dfd0; --muted:#9a8f7a; }
  body { background:var(--bg); color:var(--text); font-family:Georgia,serif;
         max-width:800px; margin:0 auto; padding:32px 24px; line-height:1.7; }
  h1 { color:var(--gold); letter-spacing:1px; }
  h2 { color:var(--gold); margin-top:32px; font-size:19px; text-transform:uppercase; letter-spacing:1px; }
  li { margin-bottom:8px; } .muted { color:var(--muted); font-size:13px; }
  a { color:var(--gold); } table { border-collapse:collapse; width:100%; margin:12px 0; }
  th, td { border:1px solid #2a2318; padding:10px 12px; text-align:left; font-size:14px; }
  th { color:var(--gold); }
</style></head><body>
<h1>◆ Operating Charter</h1>
<p class="muted">Farah Gold AI Organization Hub · Governance: <strong>advise, decide, verify</strong></p>

<h2>1. Authority</h2>
<ul>
  <li><strong>Chairman (Zaid Rahma)</strong> — final authority. Authorizes high-risk work.
      Overrides evidence blocks with a documented exception. Can overrule any decision.</li>
  <li><strong>Coordinator (Layla)</strong> — decides all operational matters within delegated authority.
      Creates and assigns tasks, sets risk tiers, executes after gates are satisfied.
      There are no routine board votes.</li>
  <li><strong>Technical Advisor (ChatGPT Dot)</strong> — advisory input on architecture,
      correctness, security. Narrow blocking authority: may block on a <em>documented</em>
      security or correctness issue, citing evidence.</li>
  <li><strong>QA Advisor (Grok Bot)</strong> — advisory input on quality and edge cases.
      Narrow blocking authority: may block a deployment if a <em>mandatory test fails</em>,
      citing the specific failed test.</li>
</ul>
<p>Advisors advise. They do not veto on opinion — only on evidence, and only within
their domain. A block without cited evidence is not a valid block.</p>

<h2>2. Risk tiers</h2>
<table>
  <tr><th>Tier</th><th>Examples</th><th>Gate</th></tr>
  <tr><td><strong>Low</strong></td><td>Research, draft content, local tests</td>
      <td>Coordinator executes autonomously</td></tr>
  <tr><td><strong>Medium</strong></td><td>Theme architecture, major UI, font geometry</td>
      <td>Targeted specialist review + staging validation before completion</td></tr>
  <tr><td><strong>High</strong></td><td>Checkout logic, live pricing, refunds, customer data,
      production manufacturing files</td>
      <td>Chairman authorization required + mandatory checks</td></tr>
</table>

<h2>3. Release gates</h2>
<ul>
  <li><strong>Low:</strong> accountable agent completes; result + evidence (if required) recorded.</li>
  <li><strong>Medium:</strong> at least one specialist review (approve / revise) before completion.
      "Revise" verdicts must be addressed or explicitly accepted by the coordinator.</li>
  <li><strong>High:</strong> specialist review <em>and</em> chairman authorization
      (<code>POST /api/tasks/{id}/authorize</code>) before completion. Production
      environment changes additionally require the evidence named in
      <code>evidence_required</code>.</li>
</ul>

<h2>4. Blocking</h2>
<ul>
  <li>A block is raised via <code>POST /api/tasks/{id}/review</code> with
      <code>{"verdict":"blocked","evidence":"..."}</code>.</li>
  <li>Blocked tasks cannot complete until the block is cleared.</li>
  <li>Clearing a block: the blocking reviewer submits a new review
      (approve/revise), <em>or</em> the chairman overrides with a documented reason
      (<code>POST /api/tasks/{id}/override</code>).</li>
  <li>The coordinator cannot clear a block unilaterally — escalation goes to the chairman.</li>
</ul>

<h2>5. Escalation</h2>
<ul>
  <li>Advisor disagreement with a coordinator decision → recorded as a "revise" review with
      reasoning; coordinator decides.</li>
  <li>Advisor block the coordinator believes is wrong → coordinator escalates to chairman with context;
      chairman overrides (documented) or upholds.</li>
  <li>Anything affecting customers, money, or production files → chairman, no exceptions.</li>
</ul>

<h2>6. Records</h2>
<p>Every task carries: ID, status, accountable agent, assigned reviewer, risk tier,
environment, acceptance criteria, and evidence required. Every review, block,
authorization, and override is written to the activity log with a timestamp.
If it isn't in the log, it didn't happen.</p>

<p><a href="/">← Back to dashboard</a></p>
</body></html>"""

@app.route("/charter")
def charter():
    return render_template_string(CHARTER_HTML)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Farah Gold AI Organization Hub</title>
<style>
  :root { --gold:#c9a227; --bg:#0d0b08; --card:#171310; --text:#e8dfd0; --muted:#9a8f7a;
          --green:#4caf50; --red:#e57373; --blue:#64b5f6; --orange:#ff9800; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:Georgia,serif; padding:24px; max-width:1200px; margin:0 auto; }
  h1 { color:var(--gold); font-size:28px; margin-bottom:4px; letter-spacing:1px; }
  .sub { color:var(--muted); margin-bottom:24px; font-size:14px; }
  .sub a { color:var(--gold); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-bottom:24px; }
  .card { background:var(--card); border:1px solid #2a2318; border-radius:8px; padding:16px; }
  .card h2 { color:var(--gold); font-size:16px; margin-bottom:12px; text-transform:uppercase; letter-spacing:1px; }
  .member { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #241e14; }
  .member:last-child { border-bottom:none; }
  .role { color:var(--gold); font-size:12px; text-transform:uppercase; letter-spacing:.5px; }
  .chairman-note { color:var(--blue); font-size:12px; }
  .task, .rev, .act { padding:10px 0; border-bottom:1px solid #241e14; font-size:14px; }
  .task:last-child, .rev:last-child, .act:last-child { border-bottom:none; }
  .badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; text-transform:uppercase; letter-spacing:.5px; margin-right:4px; }
  .pending { background:#3d2f10; color:var(--gold); }
  .in_progress { background:#12365c; color:var(--blue); }
  .completed { background:#1a3a1c; color:var(--green); }
  .failed { background:#3d1515; color:var(--red); }
  .low { background:#1a3a1c; color:var(--green); }
  .medium { background:#3d2f10; color:var(--orange); }
  .high { background:#3d1515; color:var(--red); }
  .blocked-tag { background:#3d1515; color:var(--red); }
  .approve { background:#1a3a1c; color:var(--green); }
  .revise { background:#3d2f10; color:var(--orange); }
  .blocked { background:#3d1515; color:var(--red); }
  .meta { color:var(--muted); font-size:12px; margin-top:4px; }
  .empty { color:var(--muted); font-style:italic; font-size:14px; }
  footer { margin-top:32px; color:var(--muted); font-size:12px; text-align:center; }
  a { color:var(--gold); }
</style>
</head>
<body>
  <h1>◆ Farah Gold AI Organization Hub</h1>
  <div class="sub">Advise · Decide · Verify &nbsp;·&nbsp; <a href="/charter">Operating Charter</a></div>

  <div class="grid">
    <div class="card">
      <h2>Organization</h2>
      {% for m in members %}
      <div class="member">
        <div>
          <strong>{{ m.name }}</strong><br>
          <span class="meta">{{ m.title }}</span>
          {% if m.is_chairman %}<br><span class="chairman-note">Final authority · authorizes high-risk · overrides blocks</span>{% endif %}
          {% if m.domain %}<br><span class="meta">Blocking domain: {{ m.domain }}</span>{% endif %}
        </div>
        <div class="role">{{ m.role }}</div>
      </div>
      {% endfor %}
    </div>

    <div class="card">
      <h2>Active Tasks</h2>
      {% if active_tasks %}
        {% for t in active_tasks %}
        <div class="task">
          <span class="badge {{ t.status }}">{{ t.status.replace('_',' ') }}</span>
          <span class="badge {{ t.risk_tier }}">{{ t.risk_tier }}</span>
          {% if t.blocked %}<span class="badge blocked-tag">blocked</span>{% endif %}
          <strong>#{{ t.id }} {{ t.title }}</strong><br>
          <div class="meta">→ {{ t.accountable }} · {{ t.environment }}{% if t.assigned_reviewer %} · reviewer: {{ t.assigned_reviewer }}{% endif %}</div>
        </div>
        {% endfor %}
      {% else %}
        <div class="empty">No active tasks. The queue is clear.</div>
      {% endif %}
    </div>

    <div class="card">
      <h2>Recent Reviews</h2>
      {% if reviews %}
        {% for r in reviews %}
        <div class="rev">
          <span class="badge {{ r.verdict }}">{{ r.verdict }}</span>
          <strong>{{ r.reviewer_id }}</strong> on task #{{ r.task_id }}<br>
          {% if r.evidence %}<div class="meta">{{ r.evidence[:160] }}</div>{% endif %}
          <div class="meta">{{ r.created_at[:16].replace('T',' ') }} UTC</div>
        </div>
        {% endfor %}
      {% else %}
        <div class="empty">No reviews yet.</div>
      {% endif %}
    </div>
  </div>

  <div class="card">
    <h2>Recent Activity</h2>
    {% if activity %}
      {% for a in activity %}
      <div class="act">
        <strong>{{ a.actor }}</strong> · {{ a.action }}
        {% if a.details %}<br><span class="meta">{{ a.details }}</span>{% endif %}
        <div class="meta">{{ a.ts[:16].replace('T',' ') }} UTC</div>
      </div>
      {% endfor %}
    {% else %}
      <div class="empty">No activity yet.</div>
    {% endif %}
  </div>

  <footer>
    Farah Gold AI Organization Hub · <a href="/charter">Charter</a> ·
    Chairman: Zaid Rahma · Coordinator: Layla · Executors: Victoria, Nidhal · Advisors: Dot (technical), Grok (QA)
  </footer>
</body>
</html>"""

@app.route("/")
def dashboard():
    db = get_db()
    members = [dict(r) for r in db.execute(
        "SELECT id,name,title,role,domain,is_chairman FROM members").fetchall()]
    # Order: chairman, ceo, advisors
    order = {"chairman": 0, "coordinator": 1, "advisor": 2}
    members.sort(key=lambda m: order.get(m["role"], 3))
    active_tasks = [dict(r) for r in db.execute(
        "SELECT * FROM tasks WHERE status IN ('pending','in_progress') ORDER BY created_at DESC LIMIT 10").fetchall()]
    reviews = [dict(r) for r in db.execute(
        "SELECT * FROM reviews ORDER BY id DESC LIMIT 10").fetchall()]
    activity = [dict(r) for r in db.execute(
        "SELECT * FROM activity ORDER BY id DESC LIMIT 20").fetchall()]
    return render_template_string(DASHBOARD_HTML, members=members,
                                  active_tasks=active_tasks, reviews=reviews,
                                  activity=activity)

# ---------------------------------------------------------------------------
# Startup — runs on import so gunicorn workers get an initialized DB
# ---------------------------------------------------------------------------

init_db()
seed_db()  # no-op if members already exist; never rotates tokens

if __name__ == "__main__":
    print("Hub running at http://localhost:5077")
    import os
    port = int(os.environ.get("PORT", 5077))
    app.run(host="0.0.0.0", port=port, debug=False)
