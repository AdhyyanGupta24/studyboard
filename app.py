import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "data", "app.db"))
SECRET_KEY = os.environ.get("SECRET_KEY", "")

app = Flask(__name__, static_folder="frontend", static_url_path="/static")
app.config.update(
    SECRET_KEY=SECRET_KEY or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)

if not os.path.exists(os.path.dirname(DB_PATH)):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        score INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        description TEXT NOT NULL,
        due_at TEXT NOT NULL,
        priority TEXT NOT NULL CHECK(priority IN ('low','medium','high')),
        points INTEGER NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        completed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_user_due
        ON tasks(user_id, completed, due_at);
    CREATE INDEX IF NOT EXISTS idx_tasks_user_subject
        ON tasks(user_id, subject);
    CREATE INDEX IF NOT EXISTS idx_tasks_user_priority
        ON tasks(user_id, priority);

    CREATE TABLE IF NOT EXISTS connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL,
        addressee_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','accepted','declined')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(requester_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(addressee_id) REFERENCES users(id) ON DELETE CASCADE,
        CHECK(requester_id <> addressee_id),
        UNIQUE(requester_id, addressee_id)
    );

    CREATE INDEX IF NOT EXISTS idx_connections_addressee_status
        ON connections(addressee_id, status);
    CREATE INDEX IF NOT EXISTS idx_connections_requester_status
        ON connections(requester_id, status);
    """)
    db.commit()


with app.app_context():
    init_db()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf():
    expected = session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        return jsonify({"error": "Invalid CSRF token"}), 403
    return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    return body


def clean_text(value, field, max_len):
    if not isinstance(value, str):
        raise ValueError(f"{field} is required")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} is required")
    if len(value) > max_len:
        raise ValueError(f"{field} is too long")
    return value


def normalize_priority(value):
    value = str(value).lower()
    if value not in {"low", "medium", "high"}:
        raise ValueError("Priority must be low, medium, or high")
    return value


def validate_points(value, priority):
    if value in (None, ""):
        return {"low": 10, "medium": 20, "high": 30}[priority]
    try:
        points = int(value)
    except (TypeError, ValueError):
        raise ValueError("Points must be an integer")
    if points < 0 or points > 1000:
        raise ValueError("Points must be between 0 and 1000")
    return points


def task_dict(row):
    return {
        "id": row["id"],
        "subject": row["subject"],
        "description": row["description"],
        "due_at": row["due_at"],
        "priority": row["priority"],
        "points": row["points"],
        "completed": bool(row["completed"]),
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def current_user():
    if "user_id" not in session:
        return None
    return get_db().execute(
        "SELECT id, username, score, created_at FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/session")
def api_session():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False, "csrf_token": csrf_token()})
    return jsonify({
        "authenticated": True,
        "csrf_token": csrf_token(),
        "user": dict(user),
    })


@app.post("/api/register")
def register():
    error = require_csrf()
    if error:
        return error
    try:
        body = json_body()
        username = clean_text(body.get("username"), "Username", 32)
        password = body.get("password")
        if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
            raise ValueError("Password must be 8–128 characters")
        if not all(c.isalnum() or c in "._-" for c in username):
            raise ValueError("Username may contain only letters, numbers, dots, underscores, and hyphens")

        db = get_db()
        db.execute(
            "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
            (username, generate_password_hash(password, method="scrypt"), now_iso())
        )
        db.commit()
        return jsonify({"message": "Account created"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "That username is already taken"}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/login")
def login():
    error = require_csrf()
    if error:
        return error
    try:
        body = json_body()
        username = clean_text(body.get("username"), "Username", 32)
        password = body.get("password")
        if not isinstance(password, str):
            raise ValueError("Password is required")

        db = get_db()
        user = db.execute(
            "SELECT id, username, password_hash, score, created_at FROM users WHERE username = ? COLLATE NOCASE",
            (username,)
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Invalid username or password"}), 401

        session.clear()
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)

        return jsonify({
            "message": "Logged in",
            "csrf_token": session["csrf_token"],
            "user": {
                "id": user["id"],
                "username": user["username"],
                "score": user["score"],
                "created_at": user["created_at"],
            }
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/logout")
@login_required
def logout():
    error = require_csrf()
    if error:
        return error
    session.clear()
    return jsonify({"message": "Logged out"})


@app.get("/api/tasks")
@login_required
def get_tasks():
    db = get_db()
    params = [session["user_id"]]
    where = ["user_id = ?"]

    subject = request.args.get("subject", "").strip()
    priority = request.args.get("priority", "").strip().lower()
    completed = request.args.get("completed", "").strip().lower()
    due = request.args.get("due", "").strip().lower()
    sort = request.args.get("sort", "due_asc")

    if subject:
        where.append("subject = ?")
        params.append(subject)
    if priority in {"low", "medium", "high"}:
        where.append("priority = ?")
        params.append(priority)
    if completed in {"true", "false"}:
        where.append("completed = ?")
        params.append(1 if completed == "true" else 0)
    if due == "overdue":
        where.append("completed = 0 AND due_at < ?")
        params.append(now_iso())
    elif due == "today":
        where.append("date(due_at) = date('now','localtime')")
    elif due == "week":
        where.append("due_at >= datetime('now','localtime') AND due_at < datetime('now','localtime','+7 day')")

    sort_map = {
        "due_asc": "due_at ASC",
        "due_desc": "due_at DESC",
        "priority": "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_at ASC",
        "points": "points DESC, due_at ASC",
        "newest": "created_at DESC",
        "oldest": "created_at ASC",
    }
    order = sort_map.get(sort, sort_map["due_asc"])

    rows = db.execute(
        f"SELECT * FROM tasks WHERE {' AND '.join(where)} ORDER BY {order}",
        params
    ).fetchall()

    subjects = [r["subject"] for r in db.execute(
        "SELECT DISTINCT subject FROM tasks WHERE user_id = ? ORDER BY subject",
        (session["user_id"],)
    ).fetchall()]

    return jsonify({"tasks": [task_dict(r) for r in rows], "subjects": subjects})


@app.post("/api/tasks")
@login_required
def create_task():
    error = require_csrf()
    if error:
        return error
    try:
        body = json_body()
        subject = clean_text(body.get("subject"), "Subject", 80)
        description = clean_text(body.get("description"), "Description", 2000)
        due_at = clean_text(body.get("due_at"), "Due date", 40)
        priority = normalize_priority(body.get("priority", "medium"))
        points = validate_points(body.get("points"), priority)

        # datetime-local strings are normalized to an ISO-like value.
        datetime.fromisoformat(due_at.replace("Z", "+00:00"))

        db = get_db()
        timestamp = now_iso()
        cur = db.execute("""
            INSERT INTO tasks(user_id, subject, description, due_at, priority, points, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
        """, (session["user_id"], subject, description, due_at, priority, points, timestamp, timestamp))
        db.commit()
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify({"task": task_dict(row)}), 201
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400


@app.put("/api/tasks/<int:task_id>")
@login_required
def update_task(task_id):
    error = require_csrf()
    if error:
        return error
    try:
        body = json_body()
        db = get_db()
        row = db.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"])
        ).fetchone()
        if not row:
            return jsonify({"error": "Task not found"}), 404

        subject = clean_text(body.get("subject", row["subject"]), "Subject", 80)
        description = clean_text(body.get("description", row["description"]), "Description", 2000)
        due_at = clean_text(body.get("due_at", row["due_at"]), "Due date", 40)
        priority = normalize_priority(body.get("priority", row["priority"]))
        points = validate_points(body.get("points", row["points"]), priority)
        datetime.fromisoformat(due_at.replace("Z", "+00:00"))

        db.execute("""
            UPDATE tasks
            SET subject=?, description=?, due_at=?, priority=?, points=?, updated_at=?
            WHERE id=? AND user_id=?
        """, (subject, description, due_at, priority, points, now_iso(), task_id, session["user_id"]))
        db.commit()
        updated = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return jsonify({"task": task_dict(updated)})
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/tasks/<int:task_id>/complete")
@login_required
def complete_task(task_id):
    error = require_csrf()
    if error:
        return error
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, session["user_id"])
        ).fetchone()
        if not row:
            db.rollback()
            return jsonify({"error": "Task not found"}), 404

        desired = bool(json_body().get("completed"))
        if desired == bool(row["completed"]):
            db.commit()
            return jsonify({"task": task_dict(row)})

        delta = row["points"] if desired else -row["points"]
        db.execute(
            "UPDATE tasks SET completed=?, completed_at=?, updated_at=? WHERE id=? AND user_id=?",
            (1 if desired else 0, now_iso() if desired else None, now_iso(), task_id, session["user_id"])
        )
        db.execute(
            "UPDATE users SET score = MAX(0, score + ?) WHERE id = ?",
            (delta, session["user_id"])
        )
        db.commit()
        updated = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        user = db.execute("SELECT score FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        return jsonify({"task": task_dict(updated), "score": user["score"]})
    except Exception:
        db.rollback()
        raise


@app.delete("/api/tasks/<int:task_id>")
@login_required
def delete_task(task_id):
    error = require_csrf()
    if error:
        return error
    db = get_db()
    row = db.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
        (task_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "Task not found"}), 404

    try:
        db.execute("BEGIN IMMEDIATE")
        if row["completed"]:
            db.execute(
                "UPDATE users SET score = MAX(0, score - ?) WHERE id = ?",
                (row["points"], session["user_id"])
            )
        db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
        db.commit()
        user = db.execute("SELECT score FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        return jsonify({"message": "Task deleted", "score": user["score"]})
    except Exception:
        db.rollback()
        raise


@app.get("/api/friends/search")
@login_required
def search_users():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"users": []})
    rows = get_db().execute("""
        SELECT id, username, score
        FROM users
        WHERE username LIKE ? COLLATE NOCASE
          AND id <> ?
        ORDER BY username
        LIMIT 20
    """, (q + "%", session["user_id"])).fetchall()

    return jsonify({"users": [dict(r) for r in rows]})


@app.post("/api/friends/request/<int:user_id>")
@login_required
def send_request(user_id):
    error = require_csrf()
    if error:
        return error
    if user_id == session["user_id"]:
        return jsonify({"error": "You cannot connect with yourself"}), 400

    db = get_db()
    target = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "User not found"}), 404

    existing = db.execute("""
        SELECT id, requester_id, addressee_id, status
        FROM connections
        WHERE (requester_id=? AND addressee_id=?)
           OR (requester_id=? AND addressee_id=?)
        LIMIT 1
    """, (session["user_id"], user_id, user_id, session["user_id"])).fetchone()

    if existing:
        if existing["status"] == "accepted":
            return jsonify({"error": "You are already connected"}), 409
        if existing["status"] == "pending":
            return jsonify({"error": "A connection request already exists"}), 409
        # A declined request can be sent again by replacing it.
        db.execute(
            "DELETE FROM connections WHERE id = ?", (existing["id"],)
        )

    timestamp = now_iso()
    db.execute("""
        INSERT INTO connections(requester_id, addressee_id, status, created_at, updated_at)
        VALUES(?,?,?,?,?)
    """, (session["user_id"], user_id, "pending", timestamp, timestamp))
    db.commit()
    return jsonify({"message": "Connection request sent"}), 201


@app.get("/api/friends")
@login_required
def friends():
    db = get_db()
    uid = session["user_id"]

    incoming = db.execute("""
        SELECT c.id, c.requester_id AS user_id, u.username, u.score
        FROM connections c
        JOIN users u ON u.id = c.requester_id
        WHERE c.addressee_id=? AND c.status='pending'
        ORDER BY c.created_at DESC
    """, (uid,)).fetchall()

    outgoing = db.execute("""
        SELECT c.id, c.addressee_id AS user_id, u.username, u.score
        FROM connections c
        JOIN users u ON u.id = c.addressee_id
        WHERE c.requester_id=? AND c.status='pending'
        ORDER BY c.created_at DESC
    """, (uid,)).fetchall()

    connected = db.execute("""
        SELECT u.id, u.username, u.score
        FROM connections c
        JOIN users u ON u.id = CASE
            WHEN c.requester_id=? THEN c.addressee_id
            ELSE c.requester_id
        END
        WHERE (c.requester_id=? OR c.addressee_id=?)
          AND c.status='accepted'
        ORDER BY u.score DESC, u.username ASC
    """, (uid, uid, uid)).fetchall()

    return jsonify({
        "incoming": [dict(r) for r in incoming],
        "outgoing": [dict(r) for r in outgoing],
        "friends": [dict(r) for r in connected],
    })


@app.post("/api/friends/request/<int:request_id>/respond")
@login_required
def respond_request(request_id):
    error = require_csrf()
    if error:
        return error
    try:
        action = json_body().get("action")
        if action not in {"accept", "decline"}:
            raise ValueError("Action must be accept or decline")
        db = get_db()
        row = db.execute("""
            SELECT id FROM connections
            WHERE id=? AND addressee_id=? AND status='pending'
        """, (request_id, session["user_id"])).fetchone()
        if not row:
            return jsonify({"error": "Request not found"}), 404

        status = "accepted" if action == "accept" else "declined"
        db.execute(
            "UPDATE connections SET status=?, updated_at=? WHERE id=?",
            (status, now_iso(), request_id)
        )
        db.commit()
        return jsonify({"message": f"Request {status}"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/leaderboard")
@login_required
def leaderboard():
    db = get_db()
    uid = session["user_id"]

    global_rows = db.execute("""
        SELECT id, username, score,
               RANK() OVER (ORDER BY score DESC, username ASC) AS rank
        FROM users
        ORDER BY score DESC, username ASC
        LIMIT 50
    """).fetchall()

    friend_rows = db.execute("""
        SELECT u.id, u.username, u.score,
               RANK() OVER (ORDER BY u.score DESC, u.username ASC) AS rank
        FROM users u
        WHERE u.id=? OR u.id IN (
            SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END
            FROM connections
            WHERE (requester_id=? OR addressee_id=?) AND status='accepted'
        )
        ORDER BY u.score DESC, u.username ASC
    """, (uid, uid, uid, uid)).fetchall()

    return jsonify({
        "global": [dict(r) for r in global_rows],
        "friends": [dict(r) for r in friend_rows],
    })


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Request is too large"}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
