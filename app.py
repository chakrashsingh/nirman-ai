import os
import uuid
import json
import sqlite3
import datetime
import hashlib
import hmac
import base64
import copy
import csv
import io
import re
import urllib.error
import urllib.request

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nirman.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "nirman-admin-2025")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_UPLOADS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

RATE_LIBRARY = {
    "materials": [
        {"item": "Cement OPC 43", "unit": "bag", "rate": 380, "source": "Delhi NCR seed"},
        {"item": "Cement OPC 53", "unit": "bag", "rate": 395, "source": "Delhi NCR seed"},
        {"item": "PPC Cement", "unit": "bag", "rate": 365, "source": "Delhi NCR seed"},
        {"item": "TMT Steel Fe500D", "unit": "kg", "rate": 82, "source": "Delhi NCR seed"},
        {"item": "Ready Mix Concrete M25", "unit": "cum", "rate": 8250, "source": "DSR/market seed"},
        {"item": "Ready Mix Concrete M30", "unit": "cum", "rate": 8700, "source": "DSR/market seed"},
        {"item": "AAC/block masonry", "unit": "sqft", "rate": 145, "source": "DSR/market seed"},
        {"item": "Vitrified flooring", "unit": "sqft", "rate": 165, "source": "DSR/market seed"},
    ],
    "labour": [
        {"item": "Mason labour", "unit": "day", "rate": 950, "source": "Delhi NCR seed"},
        {"item": "Helper labour", "unit": "day", "rate": 650, "source": "Delhi NCR seed"},
        {"item": "Shuttering carpenter", "unit": "day", "rate": 1100, "source": "Delhi NCR seed"},
        {"item": "Steel fixer", "unit": "day", "rate": 1050, "source": "Delhi NCR seed"},
    ],
    "spec_options": SPEC_FACTORS if "SPEC_FACTORS" in globals() else {},
}

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
                file_mime TEXT,
                file_size INTEGER,
                file_data BLOB,
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
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                options TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        existing = {row["name"] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
        migrations = {
            "file_mime": "ALTER TABLE projects ADD COLUMN file_mime TEXT",
            "file_size": "ALTER TABLE projects ADD COLUMN file_size INTEGER",
            "file_data": "ALTER TABLE projects ADD COLUMN file_data BLOB",
        }
        for col, sql in migrations.items():
            if col not in existing:
                db.execute(sql)
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

def public_project(row):
    project = dict(row)
    project.pop("file_data", None)
    project["analysis"] = json.loads(row["analysis"]) if row["analysis"] else None
    project["estimate"] = json.loads(row["estimate"]) if row["estimate"] else None
    return project

def require_admin_key():
    return request.args.get("key") == ADMIN_KEY or request.headers.get("X-Admin-Key") == ADMIN_KEY

def validate_upload(file):
    filename = (file.filename or "").strip()
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_UPLOADS:
        return None, None, "Only PDF, PNG, JPG and JPEG drawings are supported."
    data = file.read()
    if not data:
        return None, None, "Uploaded file is empty."
    if len(data) > MAX_UPLOAD_BYTES:
        return None, None, "Upload must be 20MB or smaller."
    return data, ALLOWED_UPLOADS[ext], None

def get_owned_project(project_id):
    return get_db().execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.current_user["id"])
    ).fetchone()

def safe_int(value, default=0, min_value=0, max_value=None):
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    if parsed < min_value:
        parsed = min_value
    if max_value is not None and parsed > max_value:
        parsed = max_value
    return parsed

def safe_float(value, default=0, min_value=0, max_value=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < min_value:
        parsed = min_value
    if max_value is not None and parsed > max_value:
        parsed = max_value
    return parsed

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "product": "Nirman.AI", "version": "1.0.0"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "product": "Nirman.AI", "version": "1.0.0"})

@app.route("/api/rates/library", methods=["GET"])
def rates_library():
    library = copy.deepcopy(RATE_LIBRARY)
    library["spec_options"] = SPEC_FACTORS
    library["note"] = "Seed rate library for MVP scenario planning. Replace with verified supplier/labour quotes before commercial use."
    return jsonify({"success": True, "library": library})

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
        "SELECT id, name, address, project_type, status, file_name, file_mime, file_size, created_at, updated_at FROM projects WHERE user_id = ? ORDER BY created_at DESC",
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
    return jsonify({"success": True, "project": public_project(row)})

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
    db.execute("DELETE FROM scenarios WHERE project_id = ?", (project_id,))
    db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.commit()
    return jsonify({"success": True, "message": "Project deleted."})

@app.route("/api/projects/<project_id>/upload", methods=["POST"])
@require_auth
def upload_project_drawing(project_id):
    db = get_db()
    row = db.execute(
        "SELECT id FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.current_user["id"])
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "message": "Please choose a drawing file to upload."}), 400

    data, mime, error = validate_upload(file)
    if error:
        return jsonify({"success": False, "message": error}), 400

    db.execute(
        """
        UPDATE projects
        SET file_name = ?, file_mime = ?, file_size = ?, file_data = ?,
            analysis = NULL, estimate = NULL, status = 'uploaded', updated_at = ?
        WHERE id = ?
        """,
        (file.filename, mime, len(data), sqlite3.Binary(data), now(), project_id)
    )
    db.commit()

    return jsonify({
        "success": True,
        "message": "Drawing uploaded.",
        "file": {"name": file.filename, "mime": mime, "size": len(data)}
    })

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

    if not row["file_data"]:
        return jsonify({"success": False, "message": "Upload a drawing before generating an estimate."}), 400

    analysis = analyze_drawing_with_ai(row)
    estimate = calculate_estimate(analysis)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), now(), project_id)
    )
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate})

@app.route("/api/projects/<project_id>/analysis", methods=["PUT"])
@require_auth
def update_project_analysis(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404

    data = request.get_json() or {}
    analysis = normalize_analysis(data, row["name"])
    analysis["ai_source"] = data.get("ai_source") or "user_reviewed"
    analysis["notes"] = data.get("notes") or "User-reviewed extraction values."
    estimate = calculate_estimate(analysis)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), now(), project_id)
    )
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate})

def fallback_analysis(project_name, reason):
    return {
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
        "ai_source": "demo_fallback",
        "drawing_review": {
            "summary": "Demo review generated because live AI extraction is not configured yet.",
            "risks": ["Verify built-up area, floor count and unit mix against issued-for-construction drawings."],
            "missing_information": ["Structural drawings", "MEP drawings", "Finishing schedule"],
            "assumptions": ["Residential tower in Delhi NCR", "RCC frame structure", "Standard finish level"]
        },
        "notes": f"Demo extraction for {project_name}. {reason}"
    }

def parse_ai_json(text):
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    return json.loads(text)

def normalize_analysis(data, project_name):
    def positive_int(value, default):
        try:
            value = int(float(value))
            return value if value > 0 else default
        except (TypeError, ValueError):
            return default

    total_units = positive_int(data.get("total_units"), 60)
    bua = positive_int(data.get("total_built_up_area_sqft"), 75000)
    carpet = positive_int(data.get("total_carpet_area_sqft"), int(bua * 0.72))

    units = data.get("unit_types")
    if not isinstance(units, list) or not units:
        units = [
            {"type": "2BHK", "count": max(total_units * 2 // 3, 1), "carpet_area_sqft": 850},
            {"type": "3BHK", "count": max(total_units // 3, 1), "carpet_area_sqft": 1200},
        ]

    normalized_units = []
    for item in units[:6]:
        if not isinstance(item, dict):
            continue
        normalized_units.append({
            "type": str(item.get("type") or "Unit"),
            "count": positive_int(item.get("count"), 1),
            "carpet_area_sqft": positive_int(item.get("carpet_area_sqft"), 850),
        })

    review = data.get("drawing_review") if isinstance(data.get("drawing_review"), dict) else {}
    return {
        "building_type": str(data.get("building_type") or "Residential Tower"),
        "total_floors": positive_int(data.get("total_floors"), 15),
        "total_units": total_units,
        "unit_types": normalized_units,
        "total_built_up_area_sqft": bua,
        "total_carpet_area_sqft": carpet,
        "plot_area_sqft": positive_int(data.get("plot_area_sqft"), int(bua * 0.16)),
        "structure_type": str(data.get("structure_type") or "RCC Frame"),
        "basement_levels": positive_int(data.get("basement_levels"), 0),
        "parking_spaces": positive_int(data.get("parking_spaces"), total_units),
        "lift_count": positive_int(data.get("lift_count"), max(2, total_units // 25)),
        "confidence": str(data.get("confidence") or "medium").lower(),
        "ai_source": data.get("ai_source") or "claude",
        "drawing_review": {
            "summary": str(review.get("summary") or data.get("notes") or f"AI extraction generated for {project_name}."),
            "risks": review.get("risks") if isinstance(review.get("risks"), list) else [],
            "missing_information": review.get("missing_information") if isinstance(review.get("missing_information"), list) else [],
            "assumptions": review.get("assumptions") if isinstance(review.get("assumptions"), list) else [],
        },
        "notes": str(data.get("notes") or f"AI extraction generated for {project_name}.")
    }

def analyze_drawing_with_ai(project):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return fallback_analysis(project["name"], "ANTHROPIC_API_KEY is not configured, so the app used a demo fallback.")

    file_data = project["file_data"]
    mime = project["file_mime"] or "application/pdf"
    b64 = base64.b64encode(file_data).decode("utf-8")
    if mime == "application/pdf":
        drawing_block = {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    else:
        drawing_block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}

    prompt = """
You are an Indian construction quantity-surveying assistant for Nirman.AI.
Read the uploaded architectural drawing and return ONLY valid JSON with these keys:
building_type, total_floors, total_units, unit_types, total_built_up_area_sqft,
total_carpet_area_sqft, plot_area_sqft, structure_type, basement_levels,
parking_spaces, lift_count, confidence, drawing_review, notes.

Rules:
- unit_types must be an array of objects with type, count, carpet_area_sqft.
- drawing_review must be an object with summary, risks, missing_information, assumptions.
- Use numeric values without commas or units.
- If a value is not visible, infer conservatively from the drawing context and explain it in notes.
- confidence must be high, medium, or low.
"""
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1600,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                drawing_block,
                {"type": "text", "text": prompt},
            ],
        }],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = "".join(block.get("text", "") for block in raw.get("content", []) if block.get("type") == "text")
        data = parse_ai_json(text)
        data["ai_source"] = "claude"
        return normalize_analysis(data, project["name"])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as exc:
        return fallback_analysis(project["name"], f"Claude analysis failed: {exc}")

def calculate_estimate(analysis):
    bua = analysis.get("total_built_up_area_sqft", 75000)
    units = analysis.get("total_units", 60)
    lifts = analysis.get("lift_count", 3)
    parking = analysis.get("parking_spaces", 60)

    def item(desc, qty, unit, rate):
        qty = round(float(qty), 2)
        rate = round(float(rate), 2)
        return {"desc": desc, "qty": qty, "unit": unit, "rate": rate, "amount": int(qty * rate)}

    divisions = {
        "01_general": {
            "name": "General Requirements and Preliminaries",
            "items": [
                item("Mobilization, barricading and temporary site office", bua, "sqft BUA", 28),
                item("Site supervision, safety and statutory coordination", bua, "sqft BUA", 34),
                item("Survey, setting out and documentation", bua, "sqft BUA", 16),
            ],
        },
        "02_sitework": {
            "name": "Site Work, Excavation and Earthwork",
            "items": [
                item("Bulk excavation in ordinary soil", bua * 0.18, "cft", 42),
                item("Backfilling, compaction and disposal lead", bua * 0.12, "cft", 38),
                item("Anti-termite treatment below plinth", bua * 0.42, "sqft", 18),
            ],
        },
        "03_foundation": {
            "name": "Substructure and Foundation",
            "items": [
                item("PCC 1:4:8 below foundations", bua * 0.025, "cum", 6900),
                item("RCC footings, raft and pedestal concrete", bua * 0.035, "cum", 8250),
                item("Reinforcement steel for foundation", bua * 2.2, "kg", 82),
            ],
        },
        "04_structure": {
            "name": "Superstructure RCC Frame",
            "items": [
                item("RCC columns, beams and slabs", bua * 0.105, "cum", 8400),
                item("TMT reinforcement Fe500D", bua * 8.5, "kg", 82),
                item("Centering, shuttering and staging", bua * 1.08, "sqft", 115),
            ],
        },
        "05_masonry": {
            "name": "Masonry and Blockwork",
            "items": [
                item("AAC/block masonry external walls", bua * 0.32, "sqft", 145),
                item("Internal partition masonry", bua * 0.46, "sqft", 112),
                item("Lintel, sill and minor RCC bands", bua * 0.05, "sqft", 165),
            ],
        },
        "06_doors_windows": {
            "name": "Doors, Windows and Glazing",
            "items": [
                item("Flush doors with hardware", units * 8, "each", 11800),
                item("Aluminium/uPVC windows with glazing", bua * 0.105, "sqft", 520),
                item("Common area fire-rated and service doors", units * 1.2, "each", 18500),
            ],
        },
        "07_finishes": {
            "name": "Interior Finishes",
            "items": [
                item("Internal plaster and putty base", bua * 1.8, "sqft", 42),
                item("Vitrified tile flooring with skirting", bua * 0.72, "sqft", 165),
                item("Internal painting, primer and finish coats", bua * 1.75, "sqft", 36),
            ],
        },
        "08_facade": {
            "name": "Exterior Finishes and Facade",
            "items": [
                item("External plaster and waterproof putty", bua * 0.38, "sqft", 68),
                item("Weatherproof exterior paint", bua * 0.38, "sqft", 48),
                item("Balcony railing and facade features", units * 70, "rft", 950),
            ],
        },
        "09_waterproofing": {
            "name": "Waterproofing and Insulation",
            "items": [
                item("Toilet and wet area waterproofing", units * 95, "sqft", 95),
                item("Terrace waterproofing treatment", bua * 0.085, "sqft", 130),
                item("Basement retaining wall waterproofing", bua * 0.035, "sqft", 210),
            ],
        },
        "10_plumbing": {
            "name": "Plumbing and Sanitary",
            "items": [
                item("CPVC/UPVC water supply and soil piping", units, "unit", 23500),
                item("Sanitary fixtures and CP fittings", units * 2.4, "toilet", 28500),
                item("UG tanks, pumps and terrace tanks", bua, "sqft BUA", 42),
            ],
        },
        "11_electrical": {
            "name": "Electrical Works",
            "items": [
                item("Conduiting, wiring and DBs", bua, "sqft BUA", 118),
                item("Switches, fixtures and apartment panels", units, "unit", 36000),
                item("Transformer, DG integration and LT panels", bua, "sqft BUA", 48),
            ],
        },
        "12_fire": {
            "name": "Fire Fighting and Life Safety",
            "items": [
                item("Hydrant, sprinkler and fire piping", bua, "sqft BUA", 52),
                item("Fire detection and alarm system", bua, "sqft BUA", 24),
                item("Staircase pressurization and signage", analysis.get("total_floors", 15), "floor", 85000),
            ],
        },
        "13_hvac": {
            "name": "Ventilation and Mechanical Services",
            "items": [
                item("Basement ventilation and jet fans", analysis.get("basement_levels", 1) or 1, "level", 850000),
                item("Shaft ventilation and exhaust systems", units, "unit", 4200),
                item("Common services mechanical supports", bua, "sqft BUA", 18),
            ],
        },
        "14_lifts": {
            "name": "Lifts and Vertical Transportation",
            "items": [
                item("Passenger lift including installation", lifts, "each", 1250000),
                item("Lift civil interface and electrical provisions", lifts, "each", 180000),
                item("Annual testing and commissioning allowance", lifts, "each", 65000),
            ],
        },
        "15_external": {
            "name": "External Development and Parking",
            "items": [
                item("Driveways, paving and hardscape", bua * 0.18, "sqft", 145),
                item("Boundary wall, gate and landscape works", bua * 0.09, "sqft", 165),
                item("Parking marking, EV provisions and signage", parking, "bay", 42000),
            ],
        },
        "16_overheads": {
            "name": "Professional Fees, Contingency and Overheads",
            "items": [],
        },
    }

    direct_total = sum(sum(i["amount"] for i in div["items"]) for key, div in divisions.items() if key != "16_overheads")
    divisions["16_overheads"]["items"] = [
        item("Architectural, structural and MEP design fees", 1, "lump sum", direct_total * 0.055),
        item("Contractor overheads and profit", 1, "lump sum", direct_total * 0.105),
        item("Construction contingency allowance", 1, "lump sum", direct_total * 0.065),
    ]

    subtotal = sum(sum(i["amount"] for i in div["items"]) for div in divisions.values())
    for div in divisions.values():
        div["amount"] = sum(i["amount"] for i in div["items"])
    total = subtotal
    gst = int(total * 0.12)

    return {
        "currency": "INR",
        "built_up_area": bua,
        "cost_per_sqft": int(total / bua),
        "subtotal": subtotal,
        "gst_12pct": gst,
        "total_with_gst": total + gst,
        "divisions": divisions,
        "rates_source": "DSR/CPWD benchmark seed rates + Delhi NCR market allowances",
        "disclaimer": "Indicative GST-compliant concept estimate. Replace seed rates with verified supplier and labour quotes before tender, bank submission or RERA filing."
    }

SCENARIO_DEFAULTS = {
    "name": "Scenario",
    "concrete_grade": "M25",
    "cement_type": "OPC 43",
    "steel_rate": 82,
    "finish_level": "standard",
    "flooring": "vitrified",
    "facade": "paint",
    "total_floors": None,
    "basement_levels": None,
    "lift_count": None,
}

SPEC_FACTORS = {
    "concrete_grade": {"M20": 0.96, "M25": 1.0, "M30": 1.055, "M35": 1.10},
    "cement_type": {"PPC": 0.985, "OPC 43": 1.0, "OPC 53": 1.02},
    "finish_level": {"economy": 0.88, "standard": 1.0, "premium": 1.22, "luxury": 1.45},
    "flooring": {"ceramic": 0.90, "vitrified": 1.0, "marble": 1.35, "wooden": 1.28},
    "facade": {"paint": 1.0, "texture": 1.12, "stone": 1.42, "glass": 1.95},
}

def normalize_scenario_options(options, analysis):
    options = options or {}
    normalized = dict(SCENARIO_DEFAULTS)
    normalized.update({k: v for k, v in options.items() if v is not None})
    normalized["name"] = str(normalized.get("name") or "Scenario")[:80]
    normalized["concrete_grade"] = normalized["concrete_grade"] if normalized["concrete_grade"] in SPEC_FACTORS["concrete_grade"] else "M25"
    normalized["cement_type"] = normalized["cement_type"] if normalized["cement_type"] in SPEC_FACTORS["cement_type"] else "OPC 43"
    normalized["finish_level"] = normalized["finish_level"] if normalized["finish_level"] in SPEC_FACTORS["finish_level"] else "standard"
    normalized["flooring"] = normalized["flooring"] if normalized["flooring"] in SPEC_FACTORS["flooring"] else "vitrified"
    normalized["facade"] = normalized["facade"] if normalized["facade"] in SPEC_FACTORS["facade"] else "paint"
    normalized["steel_rate"] = safe_float(normalized.get("steel_rate"), 82, 45, 160)
    normalized["total_floors"] = safe_int(normalized.get("total_floors"), analysis.get("total_floors", 15), 1, 80)
    normalized["basement_levels"] = safe_int(normalized.get("basement_levels"), analysis.get("basement_levels", 0), 0, 8)
    normalized["lift_count"] = safe_int(normalized.get("lift_count"), analysis.get("lift_count", 2), 0, 24)
    return normalized

def recalc_estimate_totals(estimate):
    subtotal = 0
    for div in estimate["divisions"].values():
        div_total = 0
        for item in div.get("items", []):
            item["rate"] = round(float(item.get("rate", 0)), 2)
            item["amount"] = int(float(item.get("qty", 0)) * item["rate"])
            div_total += item["amount"]
        div["amount"] = div_total
        subtotal += div_total
    gst = int(subtotal * 0.12)
    bua = max(safe_int(estimate.get("built_up_area"), 1, 1), 1)
    estimate["subtotal"] = subtotal
    estimate["gst_12pct"] = gst
    estimate["total_with_gst"] = subtotal + gst
    estimate["cost_per_sqft"] = int(subtotal / bua)
    return estimate

def apply_factor_to_divisions(estimate, division_keys, factor, affected):
    if abs(factor - 1) < 0.001:
        return
    for key in division_keys:
        div = estimate["divisions"].get(key)
        if not div:
            continue
        for item in div.get("items", []):
            item["rate"] = round(float(item.get("rate", 0)) * factor, 2)
        affected.add(key)

def apply_scenario_adjustments(estimate, options):
    affected = set()

    structure_factor = SPEC_FACTORS["concrete_grade"][options["concrete_grade"]] * SPEC_FACTORS["cement_type"][options["cement_type"]]
    apply_factor_to_divisions(estimate, ["03_foundation", "04_structure", "05_masonry"], structure_factor, affected)

    steel_rate = options["steel_rate"]
    for key in ["03_foundation", "04_structure"]:
        div = estimate["divisions"].get(key)
        if not div:
            continue
        for item in div.get("items", []):
            if item.get("unit") == "kg":
                item["rate"] = steel_rate
                affected.add(key)

    finish_factor = SPEC_FACTORS["finish_level"][options["finish_level"]]
    apply_factor_to_divisions(estimate, ["06_doors_windows", "07_finishes", "10_plumbing", "11_electrical"], finish_factor, affected)
    apply_factor_to_divisions(estimate, ["07_finishes"], SPEC_FACTORS["flooring"][options["flooring"]], affected)
    apply_factor_to_divisions(estimate, ["08_facade"], SPEC_FACTORS["facade"][options["facade"]], affected)

    return recalc_estimate_totals(estimate), sorted(affected)

def calculate_scenario(analysis, base_estimate, options):
    options = normalize_scenario_options(options, analysis)
    revised_analysis = copy.deepcopy(analysis)
    base_floors = max(safe_int(analysis.get("total_floors"), 1, 1), 1)
    new_floors = options["total_floors"]
    area_per_floor = safe_float(analysis.get("total_built_up_area_sqft"), 75000, 1) / base_floors
    unit_per_floor = safe_float(analysis.get("total_units"), 60, 1) / base_floors

    revised_analysis["total_floors"] = new_floors
    revised_analysis["basement_levels"] = options["basement_levels"]
    revised_analysis["lift_count"] = options["lift_count"]
    revised_analysis["total_built_up_area_sqft"] = int(area_per_floor * new_floors)
    revised_analysis["total_carpet_area_sqft"] = int(revised_analysis["total_built_up_area_sqft"] * 0.72)
    revised_analysis["total_units"] = max(int(unit_per_floor * new_floors), 1)
    revised_analysis["parking_spaces"] = max(safe_int(analysis.get("parking_spaces"), revised_analysis["total_units"]), revised_analysis["total_units"])

    revised_estimate = calculate_estimate(revised_analysis)
    revised_estimate, affected_keys = apply_scenario_adjustments(revised_estimate, options)
    affected_divisions = [
        {
            "key": key,
            "name": revised_estimate["divisions"][key]["name"],
            "base_amount": base_estimate.get("divisions", {}).get(key, {}).get("amount", 0),
            "revised_amount": revised_estimate["divisions"][key]["amount"],
            "delta": revised_estimate["divisions"][key]["amount"] - base_estimate.get("divisions", {}).get(key, {}).get("amount", 0),
        }
        for key in affected_keys
        if key in revised_estimate["divisions"]
    ]

    base_total = base_estimate.get("total_with_gst", 0)
    revised_total = revised_estimate.get("total_with_gst", 0)
    delta = revised_total - base_total
    percent = round((delta / base_total) * 100, 2) if base_total else 0

    return {
        "options": options,
        "base_total": base_total,
        "revised_total": revised_total,
        "delta": delta,
        "delta_percent": percent,
        "base_cost_per_sqft": base_estimate.get("cost_per_sqft", 0),
        "revised_cost_per_sqft": revised_estimate.get("cost_per_sqft", 0),
        "revised_analysis": revised_analysis,
        "revised_estimate": revised_estimate,
        "affected_divisions": affected_divisions,
        "summary": build_scenario_summary(options, delta, percent),
    }

def build_scenario_summary(options, delta, percent):
    direction = "increases" if delta >= 0 else "reduces"
    return (
        f"{options['name']} {direction} total cost by {abs(percent)}% using "
        f"{options['concrete_grade']} RCC, {options['cement_type']} cement, "
        f"{options['finish_level']} finishes and {options['facade']} facade."
    )

@app.route("/api/projects/<project_id>/scenario", methods=["POST"])
@require_auth
def preview_project_scenario(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["analysis"] or not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before running scenarios."}), 400

    analysis = json.loads(row["analysis"])
    estimate = json.loads(row["estimate"])
    result = calculate_scenario(analysis, estimate, request.get_json() or {})
    return jsonify({"success": True, "scenario": result})

@app.route("/api/projects/<project_id>/scenarios", methods=["GET"])
@require_auth
def list_project_scenarios(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    rows = get_db().execute(
        "SELECT id, name, options, result, created_at FROM scenarios WHERE project_id = ? AND user_id = ? ORDER BY created_at DESC",
        (project_id, g.current_user["id"])
    ).fetchall()
    scenarios = []
    for scenario in rows:
        item = dict(scenario)
        item["options"] = json.loads(item["options"])
        item["result"] = json.loads(item["result"])
        scenarios.append(item)
    return jsonify({"success": True, "scenarios": scenarios})

@app.route("/api/projects/<project_id>/scenarios", methods=["POST"])
@require_auth
def save_project_scenario(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["analysis"] or not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before saving scenarios."}), 400

    body = request.get_json() or {}
    options = body.get("options") or body
    analysis = json.loads(row["analysis"])
    estimate = json.loads(row["estimate"])
    result = calculate_scenario(analysis, estimate, options)
    scenario_id = uid()
    scenario_name = result["options"]["name"]

    get_db().execute(
        "INSERT INTO scenarios (id, project_id, user_id, name, options, result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (scenario_id, project_id, g.current_user["id"], scenario_name, json.dumps(result["options"]), json.dumps(result), now())
    )
    get_db().commit()
    return jsonify({"success": True, "scenario": {"id": scenario_id, "name": scenario_name, **result}}), 201

@app.route("/api/projects/<project_id>/estimate", methods=["PUT"])
@require_auth
def update_project_estimate(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["analysis"]:
        return jsonify({"success": False, "message": "Analyze or enter project data before editing BOQ."}), 400

    body = request.get_json() or {}
    estimate = body.get("estimate") or body
    if not isinstance(estimate.get("divisions"), dict):
        return jsonify({"success": False, "message": "Estimate divisions are required."}), 400

    current = json.loads(row["estimate"]) if row["estimate"] else calculate_estimate(json.loads(row["analysis"]))
    current["divisions"] = estimate["divisions"]
    current["built_up_area"] = safe_int(estimate.get("built_up_area"), current.get("built_up_area", 1), 1)
    current = recalc_estimate_totals(current)
    current["rates_source"] = estimate.get("rates_source") or "User-edited BOQ and seed rate library"
    current["disclaimer"] = estimate.get("disclaimer") or current.get("disclaimer", "")

    db.execute(
        "UPDATE projects SET estimate = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(current), now(), project_id)
    )
    db.commit()
    return jsonify({"success": True, "estimate": current})

def project_report_payload(row):
    project = public_project(row)
    scenarios = get_db().execute(
        "SELECT id, name, options, result, created_at FROM scenarios WHERE project_id = ? AND user_id = ? ORDER BY created_at DESC",
        (row["id"], row["user_id"])
    ).fetchall()
    parsed = []
    for scenario in scenarios:
        item = dict(scenario)
        item["options"] = json.loads(item["options"])
        item["result"] = json.loads(item["result"])
        parsed.append(item)
    return {
        "generated_at": now(),
        "project": project,
        "scenarios": parsed,
        "brand": "Nirman.AI",
    }

@app.route("/api/projects/<project_id>/report", methods=["GET"])
@require_auth
def project_report(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before exporting a report."}), 400
    return jsonify({"success": True, "report": project_report_payload(row)})

@app.route("/api/projects/<project_id>/report.csv", methods=["GET"])
@require_auth
def project_report_csv(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before exporting a report."}), 400
    report = project_report_payload(row)
    project = report["project"]
    estimate = project["estimate"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nirman.AI Cost Report"])
    writer.writerow(["Generated At", report["generated_at"]])
    writer.writerow(["Project", project["name"]])
    writer.writerow(["Address", project.get("address") or ""])
    writer.writerow(["Total With GST", estimate.get("total_with_gst")])
    writer.writerow(["Cost Per Sqft", estimate.get("cost_per_sqft")])
    writer.writerow([])
    writer.writerow(["Division", "Description", "Qty", "Unit", "Rate", "Amount"])
    for key, div in (estimate.get("divisions") or {}).items():
        for item in div.get("items", []):
            writer.writerow([div.get("name"), item.get("desc"), item.get("qty"), item.get("unit"), item.get("rate"), item.get("amount")])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=nirman_report_{project_id}.csv"}
    )

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
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, phone, role, city, created_at FROM waitlist ORDER BY created_at DESC"
    ).fetchall()
    return jsonify({"success": True, "total": len(rows), "entries": [dict(r) for r in rows]})

@app.route("/api/waitlist/export", methods=["GET"])
def waitlist_export():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, phone, role, city, created_at FROM waitlist ORDER BY created_at DESC"
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "email", "phone", "role", "city", "created_at"])
    for row in rows:
        writer.writerow([row["id"], row["name"], row["email"], row["phone"], row["role"], row["city"], row["created_at"]])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=nirman_waitlist.csv"}
    )

@app.route("/api/admin/summary", methods=["GET"])
def admin_summary():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401

    db = get_db()
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    projects = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    waitlist = db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    uploaded = db.execute("SELECT COUNT(*) FROM projects WHERE status IN ('uploaded', 'analyzed')").fetchone()[0]
    analyzed = db.execute("SELECT COUNT(*) FROM projects WHERE status = 'analyzed'").fetchone()[0]

    latest_users = db.execute(
        "SELECT id, name, email, company, role, city, created_at FROM users ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    latest_projects = db.execute(
        """
        SELECT p.id, p.name, p.address, p.project_type, p.status, p.file_name, p.file_size,
               p.created_at, p.updated_at, u.name AS user_name, u.email AS user_email
        FROM projects p
        LEFT JOIN users u ON u.id = p.user_id
        ORDER BY p.created_at DESC
        LIMIT 20
        """
    ).fetchall()
    latest_waitlist = db.execute(
        "SELECT id, name, email, phone, role, city, created_at FROM waitlist ORDER BY created_at DESC LIMIT 20"
    ).fetchall()

    return jsonify({
        "success": True,
        "counts": {
            "users": users,
            "projects": projects,
            "waitlist": waitlist,
            "uploaded_drawings": uploaded,
            "analyzed_projects": analyzed,
        },
        "users": [dict(r) for r in latest_users],
        "projects": [dict(r) for r in latest_projects],
        "waitlist": [dict(r) for r in latest_waitlist],
    })

@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, company, role, city, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    return jsonify({"success": True, "total": len(rows), "users": [dict(r) for r in rows]})

@app.route("/api/admin/users/export", methods=["GET"])
def admin_users_export():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, company, role, city, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "email", "company", "role", "city", "created_at"])
    for row in rows:
        writer.writerow([row["id"], row["name"], row["email"], row["company"], row["role"], row["city"], row["created_at"]])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=nirman_users.csv"})

@app.route("/api/admin/projects", methods=["GET"])
def admin_projects():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        """
        SELECT p.id, p.name, p.address, p.project_type, p.status, p.file_name, p.file_size,
               p.created_at, p.updated_at, u.name AS user_name, u.email AS user_email
        FROM projects p
        LEFT JOIN users u ON u.id = p.user_id
        ORDER BY p.created_at DESC
        """
    ).fetchall()
    return jsonify({"success": True, "total": len(rows), "projects": [dict(r) for r in rows]})

@app.route("/api/admin/projects/export", methods=["GET"])
def admin_projects_export():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        """
        SELECT p.id, p.name, p.address, p.project_type, p.status, p.file_name, p.file_size,
               p.created_at, p.updated_at, u.name AS user_name, u.email AS user_email
        FROM projects p
        LEFT JOIN users u ON u.id = p.user_id
        ORDER BY p.created_at DESC
        """
    ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "address", "project_type", "status", "file_name", "file_size", "user_name", "user_email", "created_at", "updated_at"])
    for row in rows:
        writer.writerow([row["id"], row["name"], row["address"], row["project_type"], row["status"], row["file_name"], row["file_size"], row["user_name"], row["user_email"], row["created_at"], row["updated_at"]])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=nirman_projects.csv"})

@app.route("/api/admin/waitlist", methods=["GET"])
def admin_waitlist():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT id, name, email, phone, role, city, created_at FROM waitlist ORDER BY created_at DESC"
    ).fetchall()
    return jsonify({"success": True, "total": len(rows), "waitlist": [dict(r) for r in rows]})

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Nirman.AI running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
