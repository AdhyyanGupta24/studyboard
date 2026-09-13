# StudyBoard

A dark, student-focused task manager with username/password authentication, persistent SQLite storage, task gamification, friend connections, and global/friends leaderboards.

## Stack

- Python 3.11+
- Flask
- SQLite
- Werkzeug password hashing (`scrypt`)
- Vanilla HTML/CSS/JavaScript
- Gunicorn for production WSGI serving

Everything is free/open-source.

## Features

- Username + password authentication — no email or phone number.
- Persistent personal dashboard.
- Create, edit, complete, and delete assignments.
- Subject, description, precise due date/time, priority, and points.
- Default points: Low 10, Medium 20, High 30.
- Custom points per task, 0–1000.
- Completing a task adds its points to the user's score.
- Reopening a completed task removes those points.
- Deleting a completed task also removes its awarded points.
- Filters: subject, priority, completion state, overdue/today/next 7 days.
- Sorting: due date, priority, points, newest/oldest.
- Username search and connection requests.
- Accept/decline incoming requests.
- Global and connected-friends leaderboards.
- Responsive dark UI.
- Passwords are never stored in plaintext.
- Session cookies are HTTP-only and SameSite=Lax.
- CSRF protection for state-changing API requests.
- SQL queries are parameterized.
- Users can only modify their own tasks.

## Project structure

```text
student_taskboard/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── data/
│   └── .gitkeep
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```

## Local setup

### 1. Create a virtual environment

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the secret

Copy `.env.example` to `.env` and generate a random secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

For a quick local run, the application also generates an ephemeral secret automatically, but a persistent `SECRET_KEY` is strongly recommended.

This project intentionally avoids adding a dotenv dependency. Export variables in your shell or use your deployment platform's environment-variable configuration.

Linux/macOS:

```bash
export SECRET_KEY="your-generated-secret"
```

Windows PowerShell:

```powershell
$env:SECRET_KEY="your-generated-secret"
```

### 4. Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

The SQLite database is automatically created at `data/app.db`.

## Production deployment

Use Gunicorn behind a real HTTPS reverse proxy such as Nginx or Caddy:

```bash
gunicorn --workers 2 --bind 127.0.0.1:5000 app:app
```

Set:

```text
SECRET_KEY=<strong-random-value>
COOKIE_SECURE=1
DATABASE_PATH=/persistent/path/app.db
```

Important: SQLite is excellent for a small-to-medium student application, but it should live on persistent storage. If deploying to a platform with an ephemeral filesystem, mount a persistent volume or the database will be lost on restart/redeploy.

For a public deployment, put HTTPS in front of Gunicorn. Do not expose the Flask development server directly to the internet.

## API overview

All JSON state-changing requests require the CSRF token returned by:

```http
GET /api/session
```

Send it as:

```http
X-CSRF-Token: <token>
```

### Authentication

```text
POST /api/register
POST /api/login
POST /api/logout
GET  /api/session
```

Register body:

```json
{
  "username": "alex123",
  "password": "strong-password"
}
```

### Tasks

```text
GET    /api/tasks
POST   /api/tasks
PUT    /api/tasks/:id
POST   /api/tasks/:id/complete
DELETE /api/tasks/:id
```

Example task:

```json
{
  "subject": "Mathematics",
  "description": "Complete quadratic equations worksheet",
  "due_at": "2026-09-20T18:30",
  "priority": "high",
  "points": 40
}
```

Task query parameters include:

```text
subject
priority
completed=true|false
due=overdue|today|week
sort=due_asc|due_desc|priority|points|newest|oldest
```

### Friends

```text
GET  /api/friends/search?q=username
GET  /api/friends
POST /api/friends/request/:user_id
POST /api/friends/request/:request_id/respond
```

Respond with:

```json
{"action":"accept"}
```

or:

```json
{"action":"decline"}
```

### Leaderboard

```text
GET /api/leaderboard
```

Returns both global and connected-friends rankings.

## Security notes

This is a solid small-app foundation, not a substitute for a professional security audit.

Before public launch:

1. Use HTTPS everywhere.
2. Set `COOKIE_SECURE=1`.
3. Use a strong, persistent `SECRET_KEY`.
4. Put Gunicorn behind Nginx/Caddy.
5. Add application-level rate limiting to login/register endpoints.
6. Add account lockout or progressive throttling for repeated failed logins.
7. Consider a reverse-proxy/WAF rate limit.
8. Back up `data/app.db`.
9. Keep Python and dependencies patched.
10. Consider adding security headers (CSP, HSTS, etc.) at the reverse proxy.
11. If the user base becomes large or highly concurrent, consider PostgreSQL while retaining the same API design.

No email/password-reset mechanism is included because the requested identity model deliberately has no email or phone number. If users forget a password, an administrator-assisted reset flow would need to be designed separately.

## License

MIT. See `LICENSE`.
