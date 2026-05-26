import os
import uuid
import json
import sqlite3
import datetime
import hashlib
import hmac
import base64

from flask import Flask, request, jsonify, g
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nirman.db")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                company TEXT,
                role TEXT,
                city TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                address TEXT,
                project_type TEXT DEFAULT 'residential_tower',
                status TEXT DEFAULT 'created',
                file_name TEXT,
                analysis TEXT,
                estimate TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS waitlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                role TEXT,
                city TEXT,
                created_at TEXT NOT NULL
            );
        """)
        db.commit()

SECRET_KEY = os.environ.get("SECRET_KEY", "nirman-secret-2025")

def hash_password(password):
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return base64.b64encode(salt + key).decode()

def verify_password(password, stored):
    try:
        raw = base64.b64decode(stored.encode())
        salt = raw[:16]
        key = raw[16:]
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(key, test)
    except Exception:
        return False

def make_token(user_id):
    payload = f"{user_id}:{now()}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.b64encode(f"{payload}:{sig}".encode()).decode()

def verify_token(token):
    try:
        decoded = base64.b64decode(token.encode()).decode()
        parts = decoded.rsplit(":", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return payload.split(":")[0]
    except Exception:
        return None

def get_current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    user_id = verify_token(auth[7:])
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "message": "Login required."}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated

def now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def uid():
    return str(uuid.uuid4())

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "product": "Nirman.ai", "version": "1.0.0"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "product": "Nirman.ai", "version": "1.0.0"})

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    company = (data.get("company") or "").strip()
    role = (data.get("role") or "").strip()
    city = (data.get("city") or "").strip()

    if not name:
        return jsonify({"success": False, "message": "Name is required."}), 400
    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Valid email is required."}), 400
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400

    db = get_db()
    if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify({"success": False, "message": "Email already registered."}), 409

    user_id = uid()
    db.execute(
        "INSERT INTO users (id, name, email, password, company, role, city, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, email, hash_password(password), company, role, city, now())
    )
    db.commit()

    return jsonify({
        "success": True,
        "token": make_token(user_id),
        "user": {"id": user_id, "name": name, "email": email, "company": company, "role": role, "city": city}
    }), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not verify_password(password, user["password"]):
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

    return jsonify({
        "success": True,
        "token": make_token(user["id"]),
        "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                 "company": user["company"], "role": user["role"], "city": user["city"]}
    })

@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    u = g.current_user
    return jsonify({
        "success": True,
        "user": {"id": u["id"], "name": u["name"], "email": u["email"],
                 "company": u["company"], "role": u["role"], "city": u["city"]}
    })

@app.route("/api/projects", methods=["POST"])
@require_auth
def create_project():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip()
    project_type = (data.get("project_type") or "residential_tower").strip()

    if not name:
        return jsonify({"success": False, "message": "Project name is required."}), 400

    db = get_db()
    project_id = uid()
    t = now()
    db.execute(
        "INSERT INTO projects (id, user_id, name, address, project_type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'created', ?, ?)",
        (project_id, g.current_user["id"], name, address, project_type, t, t)
    )
    db.commit()

    return jsonify({
        "success": True,
        "project": {"id": project_id, "name": name, "address": address,
                    "project_type": project_type, "status": "created", "created_at": t}
    }), 201

@app.route("/api/projects", methods=["GET"])
@require_auth
def list_projects():
    rows = get_db().execute(
        "SELECT id, name, address, project_type, status, file_name, created_at FROM projects WHERE user_id = ? ORDER BY created_at DESC",
        (g.current_user["id"],)
    ).fetchall()
    return jsonify({"success": True, "projects": [dict(r) for r in rows]})

@app.route("/api/projects/<project_id>", methods=["GET"])
@require_auth
def get_project(project_id):
    row = get_db().execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.current_user["id"])
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    project = dict(row)
    project["analysis"] = json.loads(row["analysis"]) if row["analysis"] else None
    project["estimate"] = json.loads(row["estimate"]) if row["estimate"] else None
    return jsonify({"success": True, "project": project})

@app.route("/api/projects/<project_id>", methods=["DELETE"])
@require_auth
def delete_project(project_id):
    db = get_db()
    row = db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.current_user["id"])
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return jsonify({"success": True, "message": "Project deleted."})

@app.route("/api/projects/<project_id>/analyze", methods=["POST"])
@require_auth
def analyze_project(project_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.current_user["id"])
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404

    analysis = {
        "building_type": "Residential Tower",
        "total_floors": 15,
        "total_units": 60,
        "unit_types": [
            {"type": "2BHK", "count": 40, "carpet_area_sqft": 850},
            {"type": "3BHK", "count": 20, "carpet_area_sqft": 1200}
        ],
        "total_built_up_area_sqft": 75000,
        "total_carpet_area_sqft": 58000,
        "plot_area_sqft": 12000,
        "structure_type": "RCC Frame",
        "basement_levels": 1,
        "parking_spaces": 65,
        "lift_count": 3,
        "confidence": "medium",
        "notes": "Demo estimate for " + row["name"]
    }

    estimate = calculate_estimate(analysis)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), now(), project_id)
    )
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate})

def calculate_estimate(analysis):
    bua = analysis.get("total_built_up_area_sqft", 75000)
    units = analysis.get("total_units", 60)
    lifts = analysis.get("lift_count", 3)
    parking = analysis.get("parking_spaces", 60)

    divisions = {
        "01": {"name": "Site Work and General Conditions", "amount": int(bua * 78)},
        "02": {"name": "Substructure and Foundation",      "amount": int(bua * 545)},
        "03": {"name": "Superstructure RCC Frame",         "amount": int(bua * 1800)},
        "04": {"name": "Exterior Finishes and Facade",     "amount": int(bua * 300)},
        "05": {"name": "Interior Finishes",                "amount": int(bua * 220) + int(units * 18000)},
        "06": {"name": "Electrical Works",                 "amount": int(bua * 125) + 1875000},
        "07": {"name": "Plumbing and Sanitary",            "amount": int(bua * 65) + int(units * 28000)},
        "08": {"name": "Fire Fighting System",             "amount": int(bua * 68)},
        "09": {"name": "Lifts and Elevators",              "amount": int(lifts * 900000) + 850000},
        "10": {"name": "External Development",             "amount": int(bua * 55) + int(parking * 45000)},
        "11": {"name": "Professional Fees and Contingency","amount": 0},
    }

    subtotal = sum(v["amount"] for k, v in divisions.items() if k != "11")
    divisions["11"]["amount"] = int(subtotal * 0.225)
    total = subtotal + divisions["11"]["amount"]
    gst = int(total * 0.12)

    return {
        "currency": "INR",
        "built_up_area": bua,
        "cost_per_sqft": int(total / bua),
        "subtotal": subtotal,
        "gst_12pct": gst,
        "total_with_gst": total + gst,
        "divisions": divisions,
        "rates_source": "Delhi NCR Market Rates 2025",
        "disclaimer": "This is an indicative estimate only. Actual costs may vary."
    }

@app.route("/api/waitlist", methods=["POST"])
def join_waitlist():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    role = (data.get("role") or "").strip()
    city = (data.get("city") or "").strip()

    if not name or not email or not role:
        return jsonify({"success": False, "message": "Name, email and role are required."}), 400

    db = get_db()
    try:
        db.execute(
            "INSERT INTO waitlist (name, email, phone, role, city, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, phone, role, city, now())
        )
        db.commit()
        total = db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
        return jsonify({"success": True, "message": "You are on the list.", "total": total}), 201
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "This email is already registered."}), 409

@app.route("/api/waitlist/count", methods=["GET"])
def waitlist_count():
    total = get_db().execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    return jsonify({"total": total})

@app.route("/api/waitlist/list", methods=["GET"])
def waitlist_list():
    key = request.args.get("key")
    if key != os.environ.get("ADMIN_KEY", "nirman-admin-2025"):
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, phone, role, city, created_at FROM waitlist ORDER BY created_at DESC"
    ).fetchall()
    return jsonify({"success": True, "total": len(rows), "entries": [dict(r) for r in rows]})

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Nirman.ai running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
