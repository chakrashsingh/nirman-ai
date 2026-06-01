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
import math
import mimetypes
import urllib.error
import urllib.request

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PERSISTENT_DATA_DIR = os.environ.get("NIRMAN_DATA_DIR") or ("/var/data" if os.path.isdir("/var/data") else APP_DIR)
DB_PATH = os.environ.get("NIRMAN_DB_PATH") or os.path.join(PERSISTENT_DATA_DIR, "nirman.db")
UPLOAD_DIR = os.environ.get("NIRMAN_UPLOAD_DIR") or os.path.join(PERSISTENT_DATA_DIR, "uploads")
PAGE_RENDER_DIR = os.environ.get("NIRMAN_PAGE_DIR") or os.path.join(PERSISTENT_DATA_DIR, "pages")
for directory in [os.path.dirname(DB_PATH), UPLOAD_DIR, PAGE_RENDER_DIR]:
    os.makedirs(directory, exist_ok=True)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "nirman-admin-2025")

PROPERTY_TYPES = {
    "residential_tower": {
        "label": "Residential Tower",
        "default_floors": 15,
        "default_units": 60,
        "default_bua": 75000,
        "default_carpet_factor": 0.72,
        "default_plot_factor": 0.16,
        "default_lift_count": 3,
    },
    "group_housing": {
        "label": "Residential Group Housing",
        "default_floors": 18,
        "default_units": 160,
        "default_bua": 220000,
        "default_carpet_factor": 0.70,
        "default_plot_factor": 0.22,
        "default_lift_count": 8,
    },
    "villa": {
        "label": "Villa / Independent House",
        "default_floors": 2,
        "default_units": 1,
        "default_bua": 7500,
        "default_carpet_factor": 0.78,
        "default_plot_factor": 1.35,
        "default_lift_count": 0,
    },
    "commercial_office": {
        "label": "Commercial Office",
        "default_floors": 12,
        "default_units": 1,
        "default_bua": 120000,
        "default_carpet_factor": 0.76,
        "default_plot_factor": 0.20,
        "default_lift_count": 5,
    },
    "mall_retail": {
        "label": "Mall / Retail Complex",
        "default_floors": 5,
        "default_units": 1,
        "default_bua": 180000,
        "default_carpet_factor": 0.68,
        "default_plot_factor": 0.45,
        "default_lift_count": 8,
    },
    "banquet_hall": {
        "label": "Banquet / Event Hall",
        "default_floors": 2,
        "default_units": 1,
        "default_bua": 35000,
        "default_carpet_factor": 0.74,
        "default_plot_factor": 0.70,
        "default_lift_count": 1,
    },
    "hotel_hospitality": {
        "label": "Hotel / Hospitality",
        "default_floors": 10,
        "default_units": 120,
        "default_bua": 150000,
        "default_carpet_factor": 0.66,
        "default_plot_factor": 0.28,
        "default_lift_count": 5,
    },
    "industrial_warehouse": {
        "label": "Industrial / Warehouse",
        "default_floors": 1,
        "default_units": 1,
        "default_bua": 100000,
        "default_carpet_factor": 0.86,
        "default_plot_factor": 1.75,
        "default_lift_count": 0,
    },
    "school_institution": {
        "label": "School / Institution",
        "default_floors": 4,
        "default_units": 1,
        "default_bua": 65000,
        "default_carpet_factor": 0.76,
        "default_plot_factor": 0.85,
        "default_lift_count": 1,
    },
    "hospital_healthcare": {
        "label": "Hospital / Healthcare",
        "default_floors": 8,
        "default_units": 100,
        "default_bua": 120000,
        "default_carpet_factor": 0.70,
        "default_plot_factor": 0.42,
        "default_lift_count": 5,
    },
}

DRAWING_DISCIPLINES = {
    "architectural": "Architectural / full building",
    "hvac": "HVAC only",
    "electrical": "Electrical only",
    "plumbing": "Plumbing only",
    "fire": "Fire and life safety only",
    "structural": "Structural only",
    "interior": "Interior / fit-out only",
}

PROPERTY_COST_PROFILES = {
    "residential_tower": {
        "rcc_factor": 0.105,
        "steel_factor": 8.5,
        "electrical_rate": 118,
        "plumbing_per_unit": 23500,
        "fire_rate": 52,
        "facade_factor": 0.38,
        "glazing_factor": 0.105,
        "flooring_factor": 0.72,
        "door_factor": 8,
        "sanitary_factor": 2.4,
        "hvac_support_rate": 18,
        "finish_multiplier": 1.0,
    },
    "group_housing": {
        "rcc_factor": 0.108,
        "steel_factor": 8.8,
        "electrical_rate": 128,
        "plumbing_per_unit": 26000,
        "fire_rate": 58,
        "facade_factor": 0.42,
        "glazing_factor": 0.12,
        "flooring_factor": 0.70,
        "door_factor": 7.5,
        "sanitary_factor": 2.35,
        "hvac_support_rate": 22,
        "finish_multiplier": 1.03,
    },
    "villa": {
        "rcc_factor": 0.07,
        "steel_factor": 6.2,
        "electrical_rate": 165,
        "plumbing_per_unit": 180000,
        "fire_rate": 18,
        "facade_factor": 0.50,
        "glazing_factor": 0.18,
        "flooring_factor": 0.82,
        "door_factor": 18,
        "sanitary_factor": 6,
        "hvac_support_rate": 42,
        "finish_multiplier": 1.35,
    },
    "commercial_office": {
        "rcc_factor": 0.115,
        "steel_factor": 9.5,
        "electrical_rate": 210,
        "plumbing_per_unit": 0,
        "plumbing_sqft_rate": 58,
        "fire_rate": 72,
        "facade_factor": 0.52,
        "glazing_factor": 0.28,
        "flooring_factor": 0.82,
        "door_area_divisor": 2200,
        "sanitary_area_divisor": 2200,
        "hvac_support_rate": 115,
        "finish_multiplier": 1.18,
    },
    "mall_retail": {
        "rcc_factor": 0.12,
        "steel_factor": 10.2,
        "electrical_rate": 260,
        "plumbing_per_unit": 0,
        "plumbing_sqft_rate": 72,
        "fire_rate": 92,
        "facade_factor": 0.58,
        "glazing_factor": 0.34,
        "flooring_factor": 0.88,
        "door_area_divisor": 1700,
        "sanitary_area_divisor": 1800,
        "hvac_support_rate": 145,
        "finish_multiplier": 1.28,
    },
    "banquet_hall": {
        "rcc_factor": 0.095,
        "steel_factor": 7.4,
        "electrical_rate": 240,
        "plumbing_per_unit": 0,
        "plumbing_sqft_rate": 85,
        "fire_rate": 68,
        "facade_factor": 0.48,
        "glazing_factor": 0.18,
        "flooring_factor": 0.78,
        "door_area_divisor": 1200,
        "sanitary_area_divisor": 900,
        "hvac_support_rate": 155,
        "finish_multiplier": 1.42,
    },
    "hotel_hospitality": {
        "rcc_factor": 0.112,
        "steel_factor": 9.1,
        "electrical_rate": 225,
        "plumbing_per_unit": 52000,
        "fire_rate": 82,
        "facade_factor": 0.50,
        "glazing_factor": 0.22,
        "flooring_factor": 0.78,
        "door_factor": 2.4,
        "sanitary_factor": 1.35,
        "hvac_support_rate": 135,
        "finish_multiplier": 1.32,
    },
    "industrial_warehouse": {
        "rcc_factor": 0.06,
        "steel_factor": 5.8,
        "electrical_rate": 115,
        "plumbing_per_unit": 0,
        "plumbing_sqft_rate": 24,
        "fire_rate": 54,
        "facade_factor": 0.34,
        "glazing_factor": 0.035,
        "flooring_factor": 0.92,
        "door_area_divisor": 5000,
        "sanitary_area_divisor": 9000,
        "hvac_support_rate": 18,
        "finish_multiplier": 0.72,
    },
    "school_institution": {
        "rcc_factor": 0.095,
        "steel_factor": 7.6,
        "electrical_rate": 145,
        "plumbing_per_unit": 0,
        "plumbing_sqft_rate": 48,
        "fire_rate": 58,
        "facade_factor": 0.40,
        "glazing_factor": 0.16,
        "flooring_factor": 0.82,
        "door_area_divisor": 550,
        "sanitary_area_divisor": 1500,
        "hvac_support_rate": 38,
        "finish_multiplier": 1.05,
    },
    "hospital_healthcare": {
        "rcc_factor": 0.118,
        "steel_factor": 9.4,
        "electrical_rate": 275,
        "plumbing_per_unit": 68000,
        "fire_rate": 96,
        "facade_factor": 0.48,
        "glazing_factor": 0.20,
        "flooring_factor": 0.86,
        "door_factor": 1.8,
        "sanitary_factor": 1.1,
        "hvac_support_rate": 185,
        "finish_multiplier": 1.38,
    },
}
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "auto").strip()
GEMINI_MODEL_PREFERENCE = os.environ.get(
    "GEMINI_MODEL_PREFERENCE",
    "gemini-3.5-flash,gemini-2.5-flash,gemini-2.0-flash",
)
AI_PROVIDER = os.environ.get("AI_PROVIDER", "").strip().lower()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_UPLOADS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

SPEC_FACTORS = {
    "concrete_grade": {"M20": 0.96, "M25": 1.0, "M30": 1.055, "M35": 1.10},
    "cement_type": {"PPC": 0.985, "OPC 43": 1.0, "OPC 53": 1.02},
    "finish_level": {"economy": 0.88, "standard": 1.0, "premium": 1.22, "luxury": 1.45},
    "flooring": {"ceramic": 0.90, "vitrified": 1.0, "marble": 1.35, "wooden": 1.28},
    "facade": {"paint": 1.0, "texture": 1.12, "stone": 1.42, "glass": 1.95},
    "wall_system": {"brick": 1.08, "aac_block": 1.0, "flyash_block": 0.96, "drywall": 1.18},
    "window_glazing": {"standard_upvc": 1.0, "aluminium": 1.12, "double_glazed": 1.36, "curtain_wall": 1.85},
    "electrical_spec": {"basic": 0.88, "standard": 1.0, "premium": 1.18, "home_automation": 1.42},
    "plumbing_spec": {"basic": 0.9, "standard": 1.0, "premium": 1.2, "luxury": 1.38},
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
    "spec_options": SPEC_FACTORS,
}

NIRMAN_EXTRACTION_PROMPT = """
You are Nirman.AI, an Indian construction quantity-surveying assistant.
Read the uploaded architectural drawing/PDF and return ONLY valid JSON.

Your job:
1. Understand the project and extract construction estimate inputs.
2. Identify drawing sheets and page-level metadata.
3. Suggest editable visual regions for rooms, cores, facade, openings, walls and slabs.
4. Estimate takeoff hints conservatively where real dimensions are visible.
5. Flag missing information clearly.

Return this exact JSON shape:
{
  "building_type": "Residential Tower",
  "project_type": "residential_tower|group_housing|villa|commercial_office|mall_retail|banquet_hall|hotel_hospitality|industrial_warehouse|school_institution|hospital_healthcare",
  "drawing_discipline": "architectural|hvac|electrical|plumbing|fire|structural|interior",
  "estimate_scope": "full_project|discipline_only",
  "scope_reason": "why this should be a full BOQ or a discipline-only estimate",
  "total_floors": 15,
  "total_units": 60,
  "unit_types": [{"type":"2BHK","count":40,"carpet_area_sqft":850}],
  "total_built_up_area_sqft": 75000,
  "total_carpet_area_sqft": 58000,
  "plot_area_sqft": 12000,
  "structure_type": "RCC Frame",
  "basement_levels": 1,
  "parking_spaces": 65,
  "lift_count": 3,
  "discipline_takeoff": {
    "equipment": [{"type":"cassette ac","qty":2,"hp":2.0,"tr":1.65,"cfm":466,"notes":"visible tag"}],
    "total_tr": 3.3,
    "total_cfm": 932
  },
  "hvac_units": [{"type":"cassette ac","qty":2,"hp_rating":2.0,"tr":1.65,"cfm":466,"room":"lounge"}],
  "floor_wise_areas": {"basement":0,"ground":0,"first":0,"second":0,"terrace":0,"pool_landscape":0},
  "luxury_amenities": {"swimming_pool":false,"sauna":false,"modular_kitchen":false,"home_automation":false,"pergola":false,"fire_pit":false,"bar":false,"gym":false,"home_theater":false},
  "confidence": "high|medium|low",
  "drawing_review": {
    "summary": "short review",
    "risks": [],
    "missing_information": [],
    "assumptions": []
  },
  "drawing_sheets": [
    {
      "page": 1,
      "sheet_type": "site_plan|floor_plan|elevation|section|schedule|detail",
      "sheet_title": "Typical Floor Plan",
      "floor_name": "Typical Floor",
      "scale": "1:100",
      "scale_pixels": 0,
      "scale_real_ft": 0,
      "floor_height_ft": 10,
      "floor_height_markers": [{"label":"floor to floor","height_ft":10}],
      "north_direction": "north up / not detected",
      "detected_labels": ["rooms","lift","staircase"],
      "missing_fields": ["scale not visible"],
      "thumbnail_label": "Plan",
      "annotations": "short notes",
      "confidence": "high|medium|low"
    }
  ],
  "drawing_regions": [
    {
      "sheet_page": 2,
      "region_type": "room_zone|wall_zone|slab_zone|facade_zone|opening|core|mep_zone",
      "label": "Apartment zone",
      "x": 10,
      "y": 12,
      "w": 35,
      "h": 24,
      "quantity_sqft": 0,
      "length_ft": 0,
      "width_ft": 0,
      "height_ft": 0,
      "material": "flooring",
      "quantity_hint": "visible apartment cluster",
      "confidence": "high|medium|low"
    }
  ],
  "takeoff_hints": {
    "flooring_area_sqft": 0,
    "facade_area_sqft": 0,
    "window_glazing_area_sqft": 0,
    "wall_area_sqft": 0,
    "slab_area_sqft": 0,
    "plaster_paint_area_sqft": 0
  },
  "notes": "short notes"
}

Rules:
- Use Indian market terminology: RCC, TMT, DSR, CPWD, RERA, khasra/plot, FAR/FSI.
- Use numbers without commas or units.
- If a value is not visible, infer conservatively and list it under assumptions.
- If the sheet is HVAC, electrical, plumbing, fire, structural, or interior-only, set estimate_scope to "discipline_only" and do not generate full-project assumptions.
- If the selected/building type is villa or independent house, do not assume tower-style lifts, basements or apartment unit mixes.
- If the project is a standalone villa/bungalow, set total_units = 1, building_type = "Villa", estimate floor_wise_areas, detect amenities such as pool/sauna/bar/gym/home theater/pergola/fire pit, and list HVAC units with hp_rating when visible.
- Use school_institution for schools, colleges and educational campuses. Use hospital_healthcare for hospitals, clinics and healthcare buildings.
- Never include markdown, commentary or code fences.
"""

ESTIMATE_RATE_ALIASES = {
    "Mobilization, barricading and temporary site office": "Mobilization, barricading and temporary site office",
    "Site supervision, safety and statutory coordination": "Site supervision, safety and statutory coordination",
    "Survey, setting out and documentation": "Survey, setting out and documentation",
    "Bulk excavation in ordinary soil": "Bulk excavation in ordinary soil",
    "Backfilling, compaction and disposal lead": "Backfilling, compaction and disposal lead",
    "Anti-termite treatment below plinth": "Anti-termite treatment below plinth",
    "PCC 1:4:8 below foundations": "PCC 1:4:8 below foundations",
    "RCC footings, raft and pedestal concrete": "Ready Mix Concrete M25",
    "Reinforcement steel for foundation": "TMT Steel Fe500D",
    "RCC columns, beams and slabs": "Ready Mix Concrete M25",
    "TMT reinforcement Fe500D": "TMT Steel Fe500D",
    "Centering, shuttering and staging": "Centering, shuttering and staging",
    "AAC/block masonry external walls": "AAC/block masonry",
    "Internal partition masonry": "Internal partition masonry",
    "Lintel, sill and minor RCC bands": "Lintel, sill and minor RCC bands",
    "Aluminium/uPVC windows with glazing": "Aluminium/uPVC windows with glazing",
    "Internal plaster and putty base": "Internal plaster and putty base",
    "Vitrified tile flooring with skirting": "Vitrified flooring",
    "Internal painting, primer and finish coats": "Internal painting, primer and finish coats",
    "External plaster and waterproof putty": "External plaster and waterproof putty",
    "Weatherproof exterior paint": "Weatherproof exterior paint",
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
                file_path TEXT,
                page_manifest TEXT,
                parcel_data TEXT,
                drawing_sheets TEXT,
                drawing_regions TEXT,
                takeoffs TEXT,
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
            CREATE TABLE IF NOT EXISTS rate_items (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                item TEXT NOT NULL UNIQUE,
                unit TEXT NOT NULL,
                rate REAL NOT NULL,
                source TEXT,
                city TEXT DEFAULT 'Delhi NCR',
                updated_at TEXT NOT NULL
            );
        """)
        existing = {row["name"] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
        migrations = {
            "file_mime": "ALTER TABLE projects ADD COLUMN file_mime TEXT",
            "file_size": "ALTER TABLE projects ADD COLUMN file_size INTEGER",
            "file_data": "ALTER TABLE projects ADD COLUMN file_data BLOB",
            "file_path": "ALTER TABLE projects ADD COLUMN file_path TEXT",
            "page_manifest": "ALTER TABLE projects ADD COLUMN page_manifest TEXT",
            "parcel_data": "ALTER TABLE projects ADD COLUMN parcel_data TEXT",
            "drawing_sheets": "ALTER TABLE projects ADD COLUMN drawing_sheets TEXT",
            "drawing_regions": "ALTER TABLE projects ADD COLUMN drawing_regions TEXT",
            "takeoffs": "ALTER TABLE projects ADD COLUMN takeoffs TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing:
                db.execute(sql)
        seed_rate_items(db)
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
    project.pop("file_path", None)
    project["analysis"] = json.loads(row["analysis"]) if row["analysis"] else None
    project["estimate"] = json.loads(row["estimate"]) if row["estimate"] else None
    project["parcel_data"] = json.loads(row["parcel_data"]) if row["parcel_data"] else None
    project["drawing_sheets"] = json.loads(row["drawing_sheets"]) if row["drawing_sheets"] else None
    project["drawing_regions"] = json.loads(row["drawing_regions"]) if row["drawing_regions"] else None
    project["takeoffs"] = json.loads(row["takeoffs"]) if row["takeoffs"] else None
    manifest = json.loads(row["page_manifest"]) if "page_manifest" in row.keys() and row["page_manifest"] else None
    project["page_manifest"] = public_page_manifest(manifest, row["id"]) if manifest else None
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

def normalize_project_type(value):
    key = (value or "residential_tower").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "villa_project": "villa",
        "independent_house": "villa",
        "bungalow": "villa",
        "commercial_space": "commercial_office",
        "office": "commercial_office",
        "mall": "mall_retail",
        "retail": "mall_retail",
        "banquate_hall": "banquet_hall",
        "banquet": "banquet_hall",
        "hotel": "hotel_hospitality",
        "warehouse": "industrial_warehouse",
        "school": "school_institution",
        "institution": "school_institution",
        "college": "school_institution",
        "hospital": "hospital_healthcare",
        "healthcare": "hospital_healthcare",
    }
    key = aliases.get(key, key)
    return key if key in PROPERTY_TYPES else "residential_tower"

def property_profile(project_type):
    return PROPERTY_TYPES.get(normalize_project_type(project_type), PROPERTY_TYPES["residential_tower"])

def cost_profile(project_type):
    return PROPERTY_COST_PROFILES.get(normalize_project_type(project_type), PROPERTY_COST_PROFILES["residential_tower"])

def extract_file_text(file_path, file_mime):
    if not file_path or not os.path.exists(file_path):
        return ""
    if file_mime == "application/pdf":
        try:
            import fitz
            doc = fitz.open(file_path)
            text = "\n".join(page.get_text() for page in doc[: min(len(doc), 5)])
            doc.close()
            return text[:12000]
        except Exception:
            return ""
    return ""

def classify_drawing_scope(file_name="", text="", analysis=None):
    haystack = f"{file_name or ''}\n{text or ''}\n{json.dumps(analysis or {}, default=str)}".lower()
    checks = [
        ("hvac", ["hvac", "ahu", "odu", "idu", "cassette", "ductable", "duct", "cfm", "tr ", "hi-wall", "grill for s/a", "grill for r/a"]),
        ("electrical", ["electrical", "lighting layout", "power layout", "db schedule", "switch", "conduit", "cable tray", "lt panel"]),
        ("plumbing", ["plumbing", "water supply", "soil pipe", "drainage", "cpvc", "upvc", "sanitary", "fixture"]),
        ("fire", ["fire fighting", "sprinkler", "hydrant", "fire alarm", "detector", "hose reel"]),
        ("structural", ["structural", "beam", "column", "slab reinforcement", "footing", "raft", "rebar", "bar bending"]),
        ("interior", ["interior", "false ceiling", "furniture layout", "wardrobe", "kitchen cabinet", "floor finish"]),
    ]
    architectural_terms = ["site plan", "floor plan", "elevation", "section", "area statement", "unit plan", "typical floor"]
    for discipline, words in checks:
        hits = sum(1 for word in words if word in haystack)
        if hits >= 2 or (discipline in ["hvac", "electrical", "plumbing"] and hits >= 1 and "layout" in haystack):
            return {
                "drawing_discipline": discipline,
                "estimate_scope": "discipline_only",
                "scope_confidence": "high" if hits >= 2 else "medium",
                "scope_reason": f"Detected {DRAWING_DISCIPLINES[discipline]} drawing terms; estimate should stay discipline-specific.",
            }
    if any(term in haystack for term in architectural_terms):
        return {
            "drawing_discipline": "architectural",
            "estimate_scope": "full_project",
            "scope_confidence": "medium",
            "scope_reason": "Architectural drawing terms detected; full-project concept BOQ can be generated with assumptions.",
        }
    return {
        "drawing_discipline": (analysis or {}).get("drawing_discipline") or "architectural",
        "estimate_scope": (analysis or {}).get("estimate_scope") or "full_project",
        "scope_confidence": "low",
        "scope_reason": "Drawing discipline was not confidently detected; using the selected project type and conservative assumptions.",
    }

def extract_hvac_takeoff(text):
    equipment = []
    total_tr = 0.0
    total_cfm = 0.0
    if not text:
        return {"equipment": [], "total_tr": 0, "total_cfm": 0}
    pattern = re.compile(r"(?:(\d+)\s*#\s*)?(\d+(?:\.\d+)?)\s*HP\s*([^\n]{0,80})", re.I)
    for match in pattern.finditer(text):
        qty = int(match.group(1) or 1)
        hp = safe_float(match.group(2), 0, 0)
        label = " ".join((match.group(3) or "").split())[:80]
        context = text[match.start(): min(len(text), match.end() + 180)]
        tr_match = re.search(r"(\d+(?:\.\d+)?)\s*TR", context, re.I)
        cfm_match = re.search(r"(\d+(?:,\d+)?(?:\.\d+)?)\s*CFM", context, re.I)
        tr = safe_float(tr_match.group(1), 0, 0) if tr_match else round(hp * 0.82, 2)
        cfm = safe_float(cfm_match.group(1).replace(",", ""), 0, 0) if cfm_match else 0
        lowered = label.lower()
        eq_type = "outdoor unit" if "odu" in lowered else "ductable unit" if "duct" in lowered else "hi-wall unit" if "wall" in lowered else "cassette unit" if "cassette" in lowered else "indoor unit"
        if eq_type == "outdoor unit":
            tr = 0
            cfm = 0
        equipment.append({"type": eq_type, "qty": qty, "hp": hp, "tr": tr, "cfm": cfm, "notes": label or eq_type})
        total_tr += qty * tr
        total_cfm += qty * cfm
    return {"equipment": equipment[:40], "total_tr": round(total_tr, 2), "total_cfm": round(total_cfm, 2)}

def enrich_analysis_scope(analysis, project_row=None):
    project_type = normalize_project_type((analysis or {}).get("project_type") or (project_row["project_type"] if project_row and "project_type" in project_row.keys() else "residential_tower"))
    analysis["project_type"] = project_type
    analysis["building_type"] = analysis.get("building_type") or property_profile(project_type)["label"]
    file_path = project_row["file_path"] if project_row and "file_path" in project_row.keys() else None
    file_mime = project_row["file_mime"] if project_row and "file_mime" in project_row.keys() else None
    file_name = project_row["file_name"] if project_row and "file_name" in project_row.keys() else ""
    text = extract_file_text(file_path, file_mime)
    scope = classify_drawing_scope(file_name, text, analysis)
    analysis.update(scope)
    if scope["drawing_discipline"] == "hvac":
        hvac = extract_hvac_takeoff(text)
        if hvac["equipment"]:
            analysis["discipline_takeoff"] = hvac
            analysis["hvac_units"] = [{"type": e.get("type"), "qty": e.get("qty"), "hp_rating": e.get("hp"), "tr": e.get("tr"), "cfm": e.get("cfm"), "notes": e.get("notes")} for e in hvac["equipment"]]
            analysis.setdefault("drawing_review", {}).setdefault("assumptions", [])
            analysis["drawing_review"]["assumptions"].append("HVAC equipment list was read from visible HP/TR/CFM tags where available.")
    return analysis

def safe_filename(filename):
    base = os.path.basename(filename or "drawing")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    return base or "drawing"

def project_upload_path(project_id, filename):
    project_dir = os.path.join(UPLOAD_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)
    ext = os.path.splitext(filename.lower())[1] or ".bin"
    return os.path.join(project_dir, f"source{ext}")

def cleanup_project_artifacts(project_id):
    for root in [os.path.join(UPLOAD_DIR, project_id), os.path.join(PAGE_RENDER_DIR, project_id)]:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root, topdown=False):
            for filename in filenames:
                try:
                    os.remove(os.path.join(dirpath, filename))
                except OSError:
                    pass
            try:
                os.rmdir(dirpath)
            except OSError:
                pass

def write_project_file(project_id, filename, data):
    path = project_upload_path(project_id, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path

def project_file_bytes(row):
    path = row["file_path"] if "file_path" in row.keys() else None
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return row["file_data"]

def project_page_dir(project_id):
    path = os.path.join(PAGE_RENDER_DIR, project_id)
    os.makedirs(path, exist_ok=True)
    return path

def make_page_manifest(project_id, file_name, file_mime, file_size=0, page_count=1, rendered=False, error=None):
    pages = []
    for page in range(1, max(int(page_count or 1), 1) + 1):
        pages.append({
            "page": page,
            "label": f"Page {page}",
            "image_path": os.path.join(project_page_dir(project_id), f"page-{page}.png"),
            "image_url": f"/api/projects/{project_id}/pages/{page}.png",
            "rendered": bool(rendered),
        })
    return {
        "file_name": file_name,
        "file_mime": file_mime,
        "file_size": file_size,
        "page_count": len(pages),
        "rendered": bool(rendered),
        "render_error": error,
        "pages": pages,
        "updated_at": now(),
    }

def render_project_pages(project_id, file_path, file_mime, file_name, file_size=0):
    if not file_path or not os.path.exists(file_path):
        return make_page_manifest(project_id, file_name, file_mime, file_size, 1, False, "Source file is not on disk yet.")
    if (file_mime or "").startswith("image/"):
        ext = os.path.splitext(file_path)[1] or ".png"
        target = os.path.join(project_page_dir(project_id), f"page-1{ext}")
        with open(file_path, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        manifest = make_page_manifest(project_id, file_name, file_mime, file_size, 1, True)
        manifest["pages"][0]["image_path"] = target
        return manifest
    if file_mime != "application/pdf":
        return make_page_manifest(project_id, file_name, file_mime, file_size, 1, False, "Unsupported drawing preview type.")
    try:
        import fitz
    except Exception:
        return make_page_manifest(project_id, file_name, file_mime, file_size, 1, False, "PDF page rendering needs PyMuPDF installed on the backend.")
    try:
        doc = fitz.open(file_path)
        page_count = min(len(doc), 30)
        pages = []
        for index in range(page_count):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
            target = os.path.join(project_page_dir(project_id), f"page-{index + 1}.png")
            pix.save(target)
            pages.append({
                "page": index + 1,
                "label": f"Page {index + 1}",
                "width": pix.width,
                "height": pix.height,
                "image_path": target,
                "image_url": f"/api/projects/{project_id}/pages/{index + 1}.png",
                "rendered": True,
            })
        doc.close()
        return {
            "file_name": file_name,
            "file_mime": file_mime,
            "file_size": file_size,
            "page_count": page_count,
            "rendered": True,
            "render_error": None,
            "pages": pages,
            "updated_at": now(),
        }
    except Exception as exc:
        return make_page_manifest(project_id, file_name, file_mime, file_size, 1, False, f"Could not render PDF pages: {exc}")

def get_project_for_file(project_id, user_id):
    return get_db().execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id)
    ).fetchone()

def api_page_url(project_id, page_number):
    return f"/api/projects/{project_id}/pages/{safe_int(page_number, 1, 1)}.png"

def public_page_manifest(manifest, project_id):
    if not manifest:
        return None
    public = copy.deepcopy(manifest)
    for page in public.get("pages", []):
        page.pop("image_path", None)
        page["image_url"] = api_page_url(project_id, page.get("page"))
    return public

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

def parse_json_field(row, key, default):
    try:
        return json.loads(row[key]) if row[key] else copy.deepcopy(default)
    except Exception:
        return copy.deepcopy(default)

def normalize_parcel(data, project):
    address = (data.get("address") or project["address"] or "").strip()
    city = (data.get("city") or "").strip()
    state = (data.get("state") or "Delhi NCR").strip()
    site_area = safe_float(data.get("site_area_sqft"), 0, 0)
    boundary = data.get("boundary_points") if isinstance(data.get("boundary_points"), list) else []
    clean_boundary = []
    for point in boundary[:60]:
        if not isinstance(point, dict):
            continue
        clean_boundary.append({
            "lat": safe_float(point.get("lat"), 0, -90, 90),
            "lng": safe_float(point.get("lng"), 0, -180, 180),
        })
    boundary_area = safe_float(data.get("boundary_area_sqft"), 0, 0)
    if clean_boundary and not boundary_area:
        boundary_area = estimate_boundary_area_sqft(clean_boundary)
    if boundary_area and not site_area:
        site_area = boundary_area
    far = safe_float(data.get("permissible_far"), 0, 0)
    coverage = safe_float(data.get("ground_coverage_pct"), 0, 0, 100)
    q = "+".join(x for x in [address, city, state] if x).replace(" ", "+")
    return {
        "address": address,
        "city": city,
        "state": state,
        "plot_number": (data.get("plot_number") or "").strip(),
        "khasra_number": (data.get("khasra_number") or "").strip(),
        "rera_number": (data.get("rera_number") or "").strip(),
        "authority": (data.get("authority") or "").strip(),
        "latitude": safe_float(data.get("latitude"), 0, -90, 90),
        "longitude": safe_float(data.get("longitude"), 0, -180, 180),
        "site_area_sqft": site_area,
        "boundary_area_sqft": boundary_area,
        "boundary_points": clean_boundary,
        "permissible_far": far,
        "ground_coverage_pct": coverage,
        "land_use": (data.get("land_use") or "Residential").strip(),
        "gis_reference": (data.get("gis_reference") or "").strip(),
        "gis_portal": (data.get("gis_portal") or "").strip(),
        "rera_portal": (data.get("rera_portal") or "").strip(),
        "verification_status": data.get("verification_status") or "self_entered",
        "map_url": data.get("map_url") or (f"https://www.google.com/maps/search/?api=1&query={q}" if q else ""),
        "notes": (data.get("notes") or "").strip(),
    }

def estimate_boundary_area_sqft(points):
    if len(points) < 3:
        return 0
    lat0 = sum(p["lat"] for p in points) / len(points)
    meters = []
    for p in points:
        x = p["lng"] * 111320 * max(0.1, abs(math.cos(math.radians(lat0))))
        y = p["lat"] * 110540
        meters.append((x, y))
    area = 0
    for i, (x1, y1) in enumerate(meters):
        x2, y2 = meters[(i + 1) % len(meters)]
        area += x1 * y2 - x2 * y1
    return round(abs(area) * 0.5 * 10.7639, 2)

def base_rate_rows():
    rows = []
    for category in ("materials", "labour"):
        for item in RATE_LIBRARY.get(category, []):
            rows.append({
                "id": item.get("id") or uid(),
                "category": category,
                "item": item["item"],
                "unit": item["unit"],
                "rate": float(item["rate"]),
                "source": item.get("source") or "Seed",
                "city": item.get("city") or "Delhi NCR",
            })
    estimate_seed = [
        ("boq", "Mobilization, barricading and temporary site office", "sqft BUA", 28),
        ("boq", "Site supervision, safety and statutory coordination", "sqft BUA", 34),
        ("boq", "Survey, setting out and documentation", "sqft BUA", 16),
        ("boq", "Bulk excavation in ordinary soil", "cft", 42),
        ("boq", "Backfilling, compaction and disposal lead", "cft", 38),
        ("boq", "Anti-termite treatment below plinth", "sqft", 18),
        ("boq", "PCC 1:4:8 below foundations", "cum", 6900),
        ("boq", "Centering, shuttering and staging", "sqft", 115),
        ("boq", "Internal partition masonry", "sqft", 112),
        ("boq", "Lintel, sill and minor RCC bands", "sqft", 165),
        ("boq", "Aluminium/uPVC windows with glazing", "sqft", 520),
        ("boq", "Internal plaster and putty base", "sqft", 42),
        ("boq", "Internal painting, primer and finish coats", "sqft", 36),
        ("boq", "External plaster and waterproof putty", "sqft", 68),
        ("boq", "Weatherproof exterior paint", "sqft", 48),
    ]
    for category, name, unit, rate in estimate_seed:
        rows.append({"id": uid(), "category": category, "item": name, "unit": unit, "rate": rate, "source": "CPWD/DSR benchmark seed", "city": "Delhi NCR"})
    return rows

def seed_rate_items(db):
    if db.execute("SELECT COUNT(*) AS c FROM rate_items").fetchone()["c"]:
        return
    for item in base_rate_rows():
        db.execute(
            "INSERT OR IGNORE INTO rate_items (id, category, item, unit, rate, source, city, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], item["category"], item["item"], item["unit"], item["rate"], item["source"], item["city"], now())
        )

def rate_items_by_category():
    rows = get_db().execute("SELECT id, category, item, unit, rate, source, city, updated_at FROM rate_items ORDER BY category, item").fetchall()
    grouped = {"materials": [], "labour": [], "boq": []}
    for row in rows:
        item = dict(row)
        item["rate"] = float(item["rate"])
        grouped.setdefault(item["category"], []).append(item)
    return grouped

def rate_lookup_map():
    try:
        return {row["item"]: float(row["rate"]) for row in get_db().execute("SELECT item, rate FROM rate_items").fetchall()}
    except Exception:
        rates = {}
        for item in base_rate_rows():
            rates[item["item"]] = float(item["rate"])
        return rates

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "product": "Nirman.AI", "version": "1.0.0"})

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "product": "Nirman.AI", "version": "1.0.0"})

@app.route("/api/rates/library", methods=["GET"])
def rates_library():
    grouped = rate_items_by_category()
    library = {
        "materials": grouped.get("materials", []),
        "labour": grouped.get("labour", []),
        "boq": grouped.get("boq", []),
    }
    library["spec_options"] = SPEC_FACTORS
    library["note"] = "Database-backed Delhi NCR seed rate library. Admin can edit these rates; replace with verified supplier/labour quotes before commercial use."
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
    project_type = normalize_project_type(data.get("project_type"))

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
    cleanup_project_artifacts(project_id)
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

    file_path = write_project_file(project_id, file.filename, data)
    manifest = render_project_pages(project_id, file_path, mime, file.filename, len(data))

    db.execute(
        """
        UPDATE projects
        SET file_name = ?, file_mime = ?, file_size = ?, file_data = ?, file_path = ?, page_manifest = ?,
            drawing_sheets = NULL, drawing_regions = NULL, takeoffs = NULL,
            analysis = NULL, estimate = NULL, status = 'uploaded', updated_at = ?
        WHERE id = ?
        """,
        (file.filename, mime, len(data), sqlite3.Binary(data), file_path, json.dumps(manifest), now(), project_id)
    )
    db.commit()

    return jsonify({
        "success": True,
        "message": "Drawing uploaded.",
        "file": {"name": file.filename, "mime": mime, "size": len(data), "page_manifest": public_page_manifest(manifest, project_id)}
    })

@app.route("/api/projects/<project_id>/file", methods=["GET"])
def project_drawing_file(project_id):
    token = request.args.get("token", "")
    user_id = verify_token(token) if token else None
    if not user_id:
        user = get_current_user()
        user_id = user["id"] if user else None
    if not user_id:
        return jsonify({"success": False, "message": "Login required."}), 401

    row = get_db().execute(
        "SELECT file_name, file_mime, file_data, file_path FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id)
    ).fetchone()
    if not row:
        return jsonify({"success": False, "message": "Drawing file not found."}), 404
    data = project_file_bytes(row)
    if not data:
        return jsonify({"success": False, "message": "Drawing file not found."}), 404

    filename = (row["file_name"] or "drawing").replace('"', "")
    return Response(
        data,
        mimetype=row["file_mime"] or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        }
    )

@app.route("/api/projects/<project_id>/pages", methods=["GET"])
@require_auth
def project_pages(project_id):
    row = get_project_for_file(project_id, g.current_user["id"])
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    manifest = parse_json_field(row, "page_manifest", None)
    if not manifest:
        file_path = row["file_path"] if "file_path" in row.keys() else None
        manifest = render_project_pages(project_id, file_path, row["file_mime"], row["file_name"], row["file_size"] or 0)
        get_db().execute("UPDATE projects SET page_manifest = ?, updated_at = ? WHERE id = ?", (json.dumps(manifest), now(), project_id))
        get_db().commit()
    return jsonify({"success": True, "page_manifest": public_page_manifest(manifest, project_id)})

@app.route("/api/projects/<project_id>/pages/<int:page_number>.png", methods=["GET"])
def project_page_image(project_id, page_number):
    token = request.args.get("token", "")
    user_id = verify_token(token) if token else None
    if not user_id:
        user = get_current_user()
        user_id = user["id"] if user else None
    if not user_id:
        return jsonify({"success": False, "message": "Login required."}), 401

    row = get_project_for_file(project_id, user_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    manifest = parse_json_field(row, "page_manifest", {}) or {}
    page = next((p for p in manifest.get("pages", []) if safe_int(p.get("page"), 0, 0) == page_number), None)
    if not page or not page.get("image_path") or not os.path.exists(page["image_path"]):
        file_path = row["file_path"] if "file_path" in row.keys() else None
        manifest = render_project_pages(project_id, file_path, row["file_mime"], row["file_name"], row["file_size"] or 0)
        get_db().execute("UPDATE projects SET page_manifest = ?, updated_at = ? WHERE id = ?", (json.dumps(manifest), now(), project_id))
        get_db().commit()
        page = next((p for p in manifest.get("pages", []) if safe_int(p.get("page"), 0, 0) == page_number), None)
    if not page or not os.path.exists(page.get("image_path", "")):
        return jsonify({"success": False, "message": "Page preview not available."}), 404
    with open(page["image_path"], "rb") as f:
        data = f.read()
    mime = mimetypes.guess_type(page["image_path"])[0] or "image/png"
    return Response(data, mimetype=mime, headers={"Cache-Control": "private, no-store"})

@app.route("/api/projects/<project_id>/parcel", methods=["PUT"])
@require_auth
def update_project_parcel(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    parcel = normalize_parcel(request.get_json() or {}, row)
    db.execute("UPDATE projects SET parcel_data = ?, address = ?, updated_at = ? WHERE id = ?", (json.dumps(parcel), parcel["address"] or row["address"], now(), project_id))
    db.commit()
    return jsonify({"success": True, "parcel_data": parcel})

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

    parcel = parse_json_field(row, "parcel_data", {})
    analysis = enrich_analysis_scope(analyze_drawing_with_ai(row), row)
    sheets = default_sheet_intelligence(analysis)
    regions = default_regions(analysis)
    takeoffs = calculate_takeoffs(analysis, regions, parcel)
    estimate = calculate_estimate(analysis, takeoffs)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, drawing_sheets = ?, drawing_regions = ?, takeoffs = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), json.dumps(sheets), json.dumps(regions), json.dumps(takeoffs), now(), project_id)
    )
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate, "drawing_sheets": sheets, "drawing_regions": regions, "takeoffs": takeoffs})

@app.route("/api/projects/<project_id>/analysis", methods=["PUT"])
@require_auth
def update_project_analysis(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404

    data = request.get_json() or {}
    data["project_type"] = data.get("project_type") or row["project_type"]
    analysis = enrich_analysis_scope(normalize_analysis(data, row["name"]), row)
    analysis["ai_source"] = data.get("ai_source") or "user_reviewed"
    analysis["notes"] = data.get("notes") or "User-reviewed extraction values."
    parcel = parse_json_field(row, "parcel_data", {})
    regions = parse_json_field(row, "drawing_regions", default_regions(analysis))
    takeoffs = calculate_takeoffs(analysis, regions, parcel)
    estimate = calculate_estimate(analysis, takeoffs)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, takeoffs = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), json.dumps(takeoffs), now(), project_id)
    )
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate, "takeoffs": takeoffs})

@app.route("/api/projects/<project_id>/drawing-intelligence", methods=["POST"])
@require_auth
def generate_drawing_intelligence(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["analysis"]:
        return jsonify({"success": False, "message": "Analyze the drawing before generating sheet intelligence."}), 400
    analysis = json.loads(row["analysis"])
    parcel = parse_json_field(row, "parcel_data", {})
    sheets = default_sheet_intelligence(analysis)
    regions = default_regions(analysis)
    takeoffs = calculate_takeoffs(analysis, regions, parcel)
    estimate = calculate_estimate(analysis, takeoffs)
    db.execute(
        "UPDATE projects SET drawing_sheets = ?, drawing_regions = ?, takeoffs = ?, estimate = ?, updated_at = ? WHERE id = ?",
        (json.dumps(sheets), json.dumps(regions), json.dumps(takeoffs), json.dumps(estimate), now(), project_id)
    )
    db.commit()
    return jsonify({"success": True, "drawing_sheets": sheets, "drawing_regions": regions, "takeoffs": takeoffs, "estimate": estimate})

@app.route("/api/projects/<project_id>/drawing-sheets", methods=["PUT"])
@require_auth
def update_drawing_sheets(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    sheets = (request.get_json() or {}).get("drawing_sheets") or []
    clean = []
    for i, sheet in enumerate(sheets):
        clean.append({
            "id": sheet.get("id") or uid(),
            "page": safe_int(sheet.get("page"), i + 1, 1),
            "sheet_type": sheet.get("sheet_type") or "floor_plan",
            "sheet_title": sheet.get("sheet_title") or f"Sheet {i + 1}",
            "floor_name": sheet.get("floor_name") or "",
            "scale": sheet.get("scale") or "",
            "scale_pixels": safe_float(sheet.get("scale_pixels"), 0, 0),
            "scale_real_ft": safe_float(sheet.get("scale_real_ft"), 0, 0),
            "floor_height_ft": safe_float(sheet.get("floor_height_ft"), 0, 0),
            "floor_height_markers": sheet.get("floor_height_markers") if isinstance(sheet.get("floor_height_markers"), list) else [],
            "thumbnail_label": sheet.get("thumbnail_label") or f"Page {safe_int(sheet.get('page'), i + 1, 1)}",
            "north_direction": sheet.get("north_direction") or "",
            "annotations": sheet.get("annotations") or "",
            "detected_labels": sheet.get("detected_labels") if isinstance(sheet.get("detected_labels"), list) else [],
            "missing_fields": sheet.get("missing_fields") if isinstance(sheet.get("missing_fields"), list) else [],
            "confidence": sheet.get("confidence") or "medium",
        })
    db.execute("UPDATE projects SET drawing_sheets = ?, updated_at = ? WHERE id = ?", (json.dumps(clean), now(), project_id))
    db.commit()
    return jsonify({"success": True, "drawing_sheets": clean})

@app.route("/api/projects/<project_id>/drawing-regions", methods=["PUT"])
@require_auth
def update_drawing_regions(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    analysis = json.loads(row["analysis"]) if row["analysis"] else fallback_analysis(row["name"], "No analysis found.")
    parcel = parse_json_field(row, "parcel_data", {})
    regions = (request.get_json() or {}).get("drawing_regions") or []
    clean = []
    for region in regions:
        clean.append({
            "id": region.get("id") or uid(),
            "sheet_page": safe_int(region.get("sheet_page"), 1, 1),
            "region_type": region.get("region_type") or "room_zone",
            "label": region.get("label") or "Region",
            "x": safe_float(region.get("x"), 10, 0, 100),
            "y": safe_float(region.get("y"), 10, 0, 100),
            "w": safe_float(region.get("w"), 20, 1, 100),
            "h": safe_float(region.get("h"), 20, 1, 100),
            "quantity_sqft": safe_float(region.get("quantity_sqft"), 0, 0),
            "length_ft": safe_float(region.get("length_ft"), 0, 0),
            "width_ft": safe_float(region.get("width_ft"), 0, 0),
            "height_ft": safe_float(region.get("height_ft"), 0, 0),
            "material": region.get("material") or "",
            "quantity_hint": region.get("quantity_hint") or "",
            "confidence": region.get("confidence") or "medium",
        })
    takeoffs = calculate_takeoffs(analysis, clean, parcel)
    estimate = calculate_estimate(analysis, takeoffs)
    db.execute("UPDATE projects SET drawing_regions = ?, takeoffs = ?, estimate = ?, updated_at = ? WHERE id = ?", (json.dumps(clean), json.dumps(takeoffs), json.dumps(estimate), now(), project_id))
    db.commit()
    return jsonify({"success": True, "drawing_regions": clean, "takeoffs": takeoffs, "estimate": estimate})

@app.route("/api/projects/<project_id>/takeoffs", methods=["POST", "PUT"])
@require_auth
def project_takeoffs(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if request.method == "PUT":
        takeoffs = (request.get_json() or {}).get("takeoffs") or {}
    else:
        analysis = json.loads(row["analysis"]) if row["analysis"] else fallback_analysis(row["name"], "No analysis found.")
        parcel = parse_json_field(row, "parcel_data", {})
        regions = parse_json_field(row, "drawing_regions", default_regions(analysis))
        takeoffs = calculate_takeoffs(analysis, regions, parcel)
    analysis = json.loads(row["analysis"]) if row["analysis"] else fallback_analysis(row["name"], "No analysis found.")
    estimate = calculate_estimate(analysis, takeoffs)
    db.execute("UPDATE projects SET takeoffs = ?, estimate = ?, updated_at = ? WHERE id = ?", (json.dumps(takeoffs), json.dumps(estimate), now(), project_id))
    db.commit()
    return jsonify({"success": True, "takeoffs": takeoffs, "estimate": estimate})

def default_unit_mix(project_type, total_units):
    project_type = normalize_project_type(project_type)
    if project_type == "villa":
        return [{"type": "Villa", "count": 1, "carpet_area_sqft": 5800}]
    if project_type in ["commercial_office", "mall_retail", "banquet_hall", "industrial_warehouse", "school_institution"]:
        return [{"type": PROPERTY_TYPES[project_type]["label"], "count": 1, "carpet_area_sqft": int(PROPERTY_TYPES[project_type]["default_bua"] * PROPERTY_TYPES[project_type]["default_carpet_factor"])}]
    if project_type == "hotel_hospitality":
        return [{"type": "Guest Room", "count": max(total_units, 1), "carpet_area_sqft": 420}]
    if project_type == "hospital_healthcare":
        return [{"type": "Hospital Bed", "count": max(total_units, 1), "carpet_area_sqft": 760}]
    return [
        {"type": "2BHK", "count": max(total_units * 2 // 3, 1), "carpet_area_sqft": 850},
        {"type": "3BHK", "count": max(total_units // 3, 1), "carpet_area_sqft": 1200},
    ]

def fallback_analysis(project_name, reason, project_type="residential_tower"):
    project_type = normalize_project_type(project_type)
    profile = property_profile(project_type)
    bua = int(profile["default_bua"])
    total_units = int(profile["default_units"])
    return {
        "building_type": profile["label"],
        "project_type": project_type,
        "drawing_discipline": "architectural",
        "estimate_scope": "full_project",
        "scope_reason": "Fallback estimate used selected property type because AI extraction was unavailable.",
        "total_floors": profile["default_floors"],
        "total_units": total_units,
        "unit_types": default_unit_mix(project_type, total_units),
        "total_built_up_area_sqft": bua,
        "total_carpet_area_sqft": int(bua * profile["default_carpet_factor"]),
        "plot_area_sqft": int(bua * profile["default_plot_factor"]),
        "structure_type": "RCC Frame",
        "basement_levels": 0 if project_type in ["villa", "banquet_hall", "industrial_warehouse"] else 1,
        "parking_spaces": max(total_units, 4 if project_type == "villa" else 10),
        "lift_count": profile["default_lift_count"],
        "discipline_takeoff": {"equipment": [], "total_tr": 0, "total_cfm": 0},
        "hvac_units": [],
        "floor_wise_areas": {"basement": 0, "ground": bua if project_type == "villa" else 0, "first": 0, "second": 0, "terrace": 0, "pool_landscape": 0},
        "luxury_amenities": {"swimming_pool": False, "sauna": False, "modular_kitchen": project_type == "villa", "home_automation": False, "pergola": False, "fire_pit": False, "bar": False, "gym": False, "home_theater": False},
        "confidence": "medium",
        "ai_source": "demo_fallback",
        "drawing_review": {
            "summary": "Demo review generated because live AI extraction is not configured yet.",
            "risks": ["Verify built-up area, floor count and unit mix against issued-for-construction drawings."],
            "missing_information": ["Structural drawings", "MEP drawings", "Finishing schedule"],
            "assumptions": [profile["label"], "Delhi NCR seed rates", "Standard finish level"]
        },
        "notes": f"Demo extraction for {project_name}. {reason}"
    }

def default_sheet_intelligence(analysis):
    if isinstance(analysis.get("drawing_sheets"), list) and analysis["drawing_sheets"]:
        sheets = []
        for i, sheet in enumerate(analysis["drawing_sheets"][:24]):
            if not isinstance(sheet, dict):
                continue
            sheets.append({
                "id": sheet.get("id") or uid(),
                "page": safe_int(sheet.get("page"), i + 1, 1),
                "sheet_type": sheet.get("sheet_type") or "floor_plan",
                "sheet_title": sheet.get("sheet_title") or sheet.get("title") or f"Sheet {i + 1}",
                "floor_name": sheet.get("floor_name") or "",
                "scale": sheet.get("scale") or "Not detected",
                "scale_pixels": safe_float(sheet.get("scale_pixels"), 0, 0),
                "scale_real_ft": safe_float(sheet.get("scale_real_ft"), 0, 0),
                "floor_height_ft": safe_float(sheet.get("floor_height_ft"), 0, 0),
                "floor_height_markers": sheet.get("floor_height_markers") if isinstance(sheet.get("floor_height_markers"), list) else [],
                "thumbnail_label": sheet.get("thumbnail_label") or f"Page {safe_int(sheet.get('page'), i + 1, 1)}",
                "north_direction": sheet.get("north_direction") or sheet.get("compass") or "Not detected",
                "annotations": sheet.get("annotations") or sheet.get("notes") or "",
                "detected_labels": sheet.get("detected_labels") if isinstance(sheet.get("detected_labels"), list) else [],
                "missing_fields": sheet.get("missing_fields") if isinstance(sheet.get("missing_fields"), list) else [],
                "confidence": sheet.get("confidence") or "medium",
            })
        if sheets:
            return sheets
    floors = safe_int(analysis.get("total_floors"), 12, 1)
    sheets = [
        {
            "id": uid(),
            "page": 1,
            "sheet_type": "site_plan",
            "sheet_title": "Site Plan",
            "floor_name": "Site",
            "scale": "1:500",
            "scale_pixels": 0,
            "scale_real_ft": 0,
            "floor_height_ft": 0,
            "floor_height_markers": [],
            "thumbnail_label": "Site",
            "north_direction": "Not verified",
            "annotations": "Verify plot boundary, road width and setbacks.",
            "detected_labels": ["plot boundary", "setbacks", "approach road"],
            "missing_fields": ["khasra/plot verification", "authority zoning"],
            "confidence": "medium",
        },
        {
            "id": uid(),
            "page": 2,
            "sheet_type": "floor_plan",
            "sheet_title": "Typical Floor Plan",
            "floor_name": "Typical Floor",
            "scale": "1:100",
            "scale_pixels": 0,
            "scale_real_ft": 0,
            "floor_height_ft": 10,
            "floor_height_markers": [],
            "thumbnail_label": "Plan",
            "north_direction": "Not verified",
            "annotations": "AI assumes typical floor repeats across tower.",
            "detected_labels": ["unit zones", "core", "rooms"],
            "missing_fields": ["room dimensions", "exact CAD scale"],
            "confidence": "medium",
        },
        {
            "id": uid(),
            "page": 3,
            "sheet_type": "elevation",
            "sheet_title": "Front Elevation",
            "floor_name": f"G+{max(floors - 1, 0)} Elevation",
            "scale": "1:100",
            "scale_pixels": 0,
            "scale_real_ft": 0,
            "floor_height_ft": 10,
            "floor_height_markers": [{"label": "Typical floor height", "height_ft": 10}],
            "thumbnail_label": "Elevation",
            "north_direction": "Elevation view",
            "annotations": "Facade zones and glazing areas are approximate until manually verified.",
            "detected_labels": ["facade zone", "glazing band", "floor markers"],
            "missing_fields": ["floor height markers", "material tags"],
            "confidence": "medium",
        },
    ]
    return sheets

def default_regions(analysis):
    if isinstance(analysis.get("drawing_regions"), list) and analysis["drawing_regions"]:
        regions = []
        for region in analysis["drawing_regions"][:80]:
            if not isinstance(region, dict):
                continue
            regions.append({
                "id": region.get("id") or uid(),
                "sheet_page": safe_int(region.get("sheet_page") or region.get("page"), 1, 1),
                "region_type": region.get("region_type") or "room_zone",
                "label": region.get("label") or "Region",
                "x": safe_float(region.get("x"), 10, 0, 100),
                "y": safe_float(region.get("y"), 10, 0, 100),
                "w": safe_float(region.get("w"), 20, 1, 100),
                "h": safe_float(region.get("h"), 20, 1, 100),
                "quantity_sqft": safe_float(region.get("quantity_sqft"), 0, 0),
                "length_ft": safe_float(region.get("length_ft"), 0, 0),
                "width_ft": safe_float(region.get("width_ft"), 0, 0),
                "height_ft": safe_float(region.get("height_ft"), 0, 0),
                "material": region.get("material") or "",
                "quantity_hint": region.get("quantity_hint") or "",
                "confidence": region.get("confidence") or "medium",
            })
        if regions:
            return regions
    return [
        {"id": uid(), "sheet_page": 2, "region_type": "room_zone", "label": "Apartment/unit zones", "x": 8, "y": 14, "w": 38, "h": 34, "quantity_sqft": 0, "length_ft": 0, "width_ft": 0, "height_ft": 0, "material": "flooring", "quantity_hint": "flooring/plaster basis", "confidence": "medium"},
        {"id": uid(), "sheet_page": 2, "region_type": "core", "label": "Lift and staircase core", "x": 52, "y": 18, "w": 18, "h": 28, "quantity_sqft": 0, "length_ft": 0, "width_ft": 0, "height_ft": 0, "material": "rcc_core", "quantity_hint": "vertical circulation", "confidence": "medium"},
        {"id": uid(), "sheet_page": 3, "region_type": "facade_zone", "label": "Main facade zone", "x": 10, "y": 12, "w": 72, "h": 58, "quantity_sqft": 0, "length_ft": 0, "width_ft": 0, "height_ft": 0, "material": "painted_plaster", "quantity_hint": "facade/plaster/paint", "confidence": "medium"},
        {"id": uid(), "sheet_page": 3, "region_type": "opening", "label": "Window/glazing band", "x": 18, "y": 24, "w": 56, "h": 18, "quantity_sqft": 0, "length_ft": 0, "width_ft": 0, "height_ft": 0, "material": "glazing", "quantity_hint": "window/glazing", "confidence": "low"},
    ]

def calculate_takeoffs(analysis, regions=None, parcel=None):
    bua = safe_float(analysis.get("total_built_up_area_sqft"), 75000, 1)
    carpet = safe_float(analysis.get("total_carpet_area_sqft"), bua * 0.72, 1)
    floors = max(safe_int(analysis.get("total_floors"), 12, 1), 1)
    units = max(safe_int(analysis.get("total_units"), 60, 1), 1)
    basement = safe_int(analysis.get("basement_levels"), 0, 0)
    regions = regions or []

    def region_area(*types):
        total = 0
        wanted = set(types)
        for region in regions:
            if region.get("region_type") not in wanted:
                continue
            area = safe_float(region.get("quantity_sqft"), 0, 0)
            if not area:
                length = safe_float(region.get("length_ft"), 0, 0)
                width = safe_float(region.get("width_ft"), 0, 0)
                height = safe_float(region.get("height_ft"), 0, 0)
                if region.get("region_type") in ["wall_zone", "facade_zone", "opening"] and length and height:
                    area = length * height
                elif length and width:
                    area = length * width
            if not area:
                match = re.search(r"(\d+(?:\.\d+)?)", str(region.get("quantity_hint") or "").replace(",", ""))
                area = safe_float(match.group(1), 0, 0) if match else 0
            total += area
        return total

    facade_region_factor = 1 + min(len([r for r in (regions or []) if r.get("region_type") == "facade_zone"]) * 0.03, 0.12)
    glazing_region_factor = 1 + min(len([r for r in (regions or []) if r.get("region_type") == "opening"]) * 0.04, 0.16)
    site_area = safe_float((parcel or {}).get("site_area_sqft"), analysis.get("plot_area_sqft", 0), 0)
    slab_area = region_area("slab", "slab_zone") or round(bua * 1.03, 2)
    flooring_area = region_area("room", "room_zone", "flooring") or round(carpet * 1.08, 2)
    wall_area = region_area("wall", "wall_zone") or round(bua * 1.65, 2)
    plaster_area = region_area("plaster", "paint", "wall", "wall_zone") or round(bua * 2.05, 2)
    facade_area = region_area("facade", "facade_zone", "elevation") or round((bua / floors) * floors * 0.42 * facade_region_factor, 2)
    glazing_area = region_area("opening", "window", "glazing") or round((bua / floors) * floors * 0.115 * glazing_region_factor, 2)
    return {
        "method": "MVP AI-assisted takeoff with editable assumptions",
        "confidence": "medium",
        "quantities": {
            "slab_area_sqft": round(slab_area, 2),
            "flooring_area_sqft": round(flooring_area, 2),
            "wall_area_sqft": round(wall_area, 2),
            "plaster_paint_area_sqft": round(plaster_area, 2),
            "facade_area_sqft": round(facade_area, 2),
            "window_glazing_area_sqft": round(glazing_area, 2),
            "mep_allowance_sqft": round(bua, 2),
            "parking_area_sqft": round(max(units, analysis.get("parking_spaces", units)) * 320, 2),
            "basement_area_sqft": round((bua / floors) * basement, 2),
            "site_development_area_sqft": round(max(site_area - (bua / floors), 0), 2) if site_area else 0,
        },
        "boq_links": {
            "slab_area_sqft": ["04_structure"],
            "wall_area_sqft": ["05_masonry", "07_finishes"],
            "facade_area_sqft": ["08_facade"],
            "window_glazing_area_sqft": ["06_doors_windows"],
            "flooring_area_sqft": ["07_finishes"],
            "plaster_paint_area_sqft": ["07_finishes", "08_facade"],
            "mep_allowance_sqft": ["10_plumbing", "11_electrical", "12_fire", "13_hvac"],
            "site_development_area_sqft": ["15_external"],
        },
        "material_schedule": summarize_region_materials(regions),
        "model_reconstruction": {
            "method": "Associates editable floor-plan and elevation overlays into an approximate massing model.",
            "status": "mvp_editable_not_cad_exact",
            "floors": floors,
            "basement_levels": basement,
            "facade_regions": len([r for r in regions if r.get("region_type") == "facade_zone"]),
            "opening_regions": len([r for r in regions if r.get("region_type") == "opening"]),
        },
        "assumptions": [
            "Exact CAD geometry is not available in MVP; quantities are derived from extracted areas and editable regions.",
            "Facade and glazing quantities improve when elevation regions are verified.",
            "MEP is treated as a rough sqft allowance until MEP drawings are parsed.",
        ],
    }

def summarize_region_materials(regions):
    summary = {}
    for region in regions or []:
        material = (region.get("material") or region.get("region_type") or "unclassified").strip()
        area = safe_float(region.get("quantity_sqft"), 0, 0)
        if not area:
            length = safe_float(region.get("length_ft"), 0, 0)
            width = safe_float(region.get("width_ft"), 0, 0)
            height = safe_float(region.get("height_ft"), 0, 0)
            area = length * height if height and length else length * width
        summary.setdefault(material, {"area_sqft": 0, "regions": 0})
        summary[material]["area_sqft"] = round(summary[material]["area_sqft"] + area, 2)
        summary[material]["regions"] += 1
    return summary

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

    project_type = normalize_project_type(data.get("project_type"))
    profile = property_profile(project_type)
    total_units = positive_int(data.get("total_units"), profile["default_units"])
    bua = positive_int(data.get("total_built_up_area_sqft"), profile["default_bua"])
    carpet = positive_int(data.get("total_carpet_area_sqft"), int(bua * profile["default_carpet_factor"]))

    units = data.get("unit_types")
    if not isinstance(units, list) or not units:
        units = default_unit_mix(project_type, total_units)

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
    discipline = str(data.get("drawing_discipline") or "architectural").lower()
    discipline = discipline if discipline in DRAWING_DISCIPLINES else "architectural"
    estimate_scope = str(data.get("estimate_scope") or "full_project").lower()
    estimate_scope = "discipline_only" if estimate_scope == "discipline_only" else "full_project"
    floor_wise = data.get("floor_wise_areas") if isinstance(data.get("floor_wise_areas"), dict) else {}
    floor_wise_areas = {
        "basement": positive_int(floor_wise.get("basement"), 0),
        "ground": positive_int(floor_wise.get("ground"), 0),
        "first": positive_int(floor_wise.get("first"), 0),
        "second": positive_int(floor_wise.get("second"), 0),
        "terrace": positive_int(floor_wise.get("terrace"), 0),
        "pool_landscape": positive_int(floor_wise.get("pool_landscape"), 0),
    }
    amenities = data.get("luxury_amenities") if isinstance(data.get("luxury_amenities"), dict) else {}
    luxury_amenities = {key: bool(amenities.get(key)) for key in ["swimming_pool", "sauna", "modular_kitchen", "home_automation", "pergola", "fire_pit", "bar", "gym", "home_theater"]}
    hvac_units = data.get("hvac_units") if isinstance(data.get("hvac_units"), list) else []
    result = {
        "building_type": str(data.get("building_type") or profile["label"]),
        "project_type": project_type,
        "drawing_discipline": discipline,
        "estimate_scope": estimate_scope,
        "scope_reason": str(data.get("scope_reason") or "Scope generated from AI extraction and selected project type."),
        "total_floors": positive_int(data.get("total_floors"), profile["default_floors"]),
        "total_units": total_units,
        "unit_types": normalized_units,
        "total_built_up_area_sqft": bua,
        "total_carpet_area_sqft": carpet,
        "plot_area_sqft": positive_int(data.get("plot_area_sqft"), int(bua * profile["default_plot_factor"])),
        "structure_type": str(data.get("structure_type") or "RCC Frame"),
        "basement_levels": positive_int(data.get("basement_levels"), 0),
        "parking_spaces": positive_int(data.get("parking_spaces"), total_units),
        "lift_count": positive_int(data.get("lift_count"), profile["default_lift_count"]),
        "discipline_takeoff": data.get("discipline_takeoff") if isinstance(data.get("discipline_takeoff"), dict) else {"equipment": [], "total_tr": 0, "total_cfm": 0},
        "hvac_units": hvac_units,
        "floor_wise_areas": floor_wise_areas,
        "luxury_amenities": luxury_amenities,
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
    if isinstance(data.get("drawing_sheets"), list):
        result["drawing_sheets"] = data["drawing_sheets"]
    if isinstance(data.get("drawing_regions"), list):
        result["drawing_regions"] = data["drawing_regions"]
    if isinstance(data.get("takeoff_hints"), dict):
        result["takeoff_hints"] = data["takeoff_hints"]
    return result

def analyze_drawing_with_ai(project):
    file_data = project_file_bytes(project)
    if not file_data:
        return fallback_analysis(project["name"], "Drawing file was not available to the AI analyzer.", project["project_type"] if "project_type" in project.keys() else "residential_tower")

    mime = project["file_mime"] or "application/pdf"
    b64 = base64.b64encode(file_data).decode("utf-8")
    provider = AI_PROVIDER or ("gemini" if os.environ.get("GEMINI_API_KEY") else "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "")
    if provider == "gemini":
        return analyze_with_gemini(project, mime, b64)
    if provider == "anthropic":
        return analyze_with_anthropic(project, mime, b64)
    return fallback_analysis(project["name"], "No AI API key is configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in Render.", project["project_type"] if "project_type" in project.keys() else "residential_tower")

def gemini_model_candidates():
    models = []
    if GEMINI_MODEL and GEMINI_MODEL.lower() != "auto":
        models.append(GEMINI_MODEL)
    models.extend([m.strip() for m in GEMINI_MODEL_PREFERENCE.split(",") if m.strip()])
    seen = set()
    unique = []
    for model in models:
        if model not in seen:
            unique.append(model)
            seen.add(model)
    return unique or ["gemini-3.5-flash"]

def analyze_with_gemini(project, mime, b64):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return fallback_analysis(project["name"], "GEMINI_API_KEY is not configured, so the app used a demo fallback.", project["project_type"] if "project_type" in project.keys() else "residential_tower")

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": mime, "data": b64}},
                {"text": f"Selected property type from user: {project['project_type'] if 'project_type' in project.keys() else 'residential_tower'}.\n\n{NIRMAN_EXTRACTION_PROMPT}"},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    errors = []
    try:
        for model in gemini_model_candidates():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"content-type": "application/json", "x-goog-api-key": api_key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts)
                data = parse_ai_json(text)
                data["ai_source"] = "gemini"
                data["ai_model"] = model
                data["project_type"] = data.get("project_type") or (project["project_type"] if "project_type" in project.keys() else "residential_tower")
                return normalize_analysis(data, project["name"])
            except urllib.error.HTTPError as exc:
                errors.append(f"{model}: HTTP {exc.code}")
                if exc.code not in (400, 403, 404, 429):
                    raise
            except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError, IndexError) as exc:
                errors.append(f"{model}: {exc}")
                continue
        raise RuntimeError("; ".join(errors))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError, IndexError) as exc:
        return fallback_analysis(project["name"], f"Gemini analysis failed: {exc}", project["project_type"] if "project_type" in project.keys() else "residential_tower")
    except RuntimeError as exc:
        return fallback_analysis(project["name"], f"Gemini analysis failed for all configured models: {exc}", project["project_type"] if "project_type" in project.keys() else "residential_tower")

def analyze_with_anthropic(project, mime, b64):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return fallback_analysis(project["name"], "ANTHROPIC_API_KEY is not configured, so the app used a demo fallback.", project["project_type"] if "project_type" in project.keys() else "residential_tower")

    if mime == "application/pdf":
        drawing_block = {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    else:
        drawing_block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2200,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                drawing_block,
                {"type": "text", "text": f"Selected property type from user: {project['project_type'] if 'project_type' in project.keys() else 'residential_tower'}.\n\n{NIRMAN_EXTRACTION_PROMPT}"},
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
        data["project_type"] = data.get("project_type") or (project["project_type"] if "project_type" in project.keys() else "residential_tower")
        return normalize_analysis(data, project["name"])
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as exc:
        return fallback_analysis(project["name"], f"Claude analysis failed: {exc}", project["project_type"] if "project_type" in project.keys() else "residential_tower")

def calculate_discipline_estimate(analysis, takeoffs=None):
    discipline = analysis.get("drawing_discipline") or "hvac"
    q = (takeoffs or {}).get("quantities") or {}

    def line(desc, qty, unit, rate, gst_rate=18, source="Discipline-specific seed rate"):
        qty = round(float(qty or 0), 2)
        rate = round(float(rate or 0), 2)
        return {"desc": desc, "qty": qty, "unit": unit, "rate": rate, "gst_rate": gst_rate, "amount": int(qty * rate), "source": source}

    if discipline == "hvac":
        hvac = analysis.get("discipline_takeoff") if isinstance(analysis.get("discipline_takeoff"), dict) else {}
        equipment = hvac.get("equipment") if isinstance(hvac.get("equipment"), list) else []
        if not equipment and isinstance(analysis.get("hvac_units"), list):
            equipment = [{"type": u.get("type") or "indoor unit", "qty": u.get("qty") or 1, "hp": u.get("hp_rating") or u.get("hp") or 0, "tr": u.get("tr") or 0, "cfm": u.get("cfm") or 0, "notes": u.get("notes") or u.get("room") or ""} for u in analysis["hvac_units"] if isinstance(u, dict)]
        total_tr = safe_float(hvac.get("total_tr"), 0, 0)
        total_cfm = safe_float(hvac.get("total_cfm"), 0, 0)
        if not total_tr:
            total_tr = sum(safe_int(e.get("qty"), 1, 1) * safe_float(e.get("tr"), 0, 0) for e in equipment)
        if not total_cfm:
            total_cfm = sum(safe_int(e.get("qty"), 1, 1) * safe_float(e.get("cfm"), 0, 0) for e in equipment)
        cassette_qty = sum(safe_int(e.get("qty"), 1, 1) for e in equipment if "cassette" in str(e.get("type", "")).lower())
        ductable_qty = sum(safe_int(e.get("qty"), 1, 1) for e in equipment if "duct" in str(e.get("type", "")).lower())
        hiwall_qty = sum(safe_int(e.get("qty"), 1, 1) for e in equipment if "wall" in str(e.get("type", "")).lower())
        indoor_qty = max(cassette_qty + ductable_qty + hiwall_qty, len(equipment) or 1)
        total_tr = total_tr or max(indoor_qty * 1.65, 1.65)
        divisions = {
            "13_hvac": {
                "name": "HVAC Works",
                "items": [
                    line("VRF/ductable indoor units supply and installation", indoor_qty, "each", 85000),
                    line("Outdoor units / condenser allowance", max(1, round(total_tr / 15, 2)), "set", 650000),
                    line("Copper piping, insulation and refrigerant", total_tr, "TR", 18500),
                    line("Drain piping, supports and sleeves", indoor_qty, "point", 8500),
                    line("Ducting, grilles and diffusers allowance", max(total_cfm, total_tr * 350), "CFM", 68),
                    line("Testing, balancing and commissioning", total_tr, "TR", 6500),
                ],
            },
            "16_overheads": {
                "name": "Professional Fees, Contingency and Overheads",
                "items": [],
            },
        }
    elif discipline == "electrical":
        bua = analysis.get("total_built_up_area_sqft", 10000)
        divisions = {"11_electrical": {"name": "Electrical Works", "items": [line("Electrical conduiting and wiring", bua, "sqft", 95, 18), line("DBs, switches and point wiring allowance", bua, "sqft", 80, 18), line("Testing and commissioning", 1, "lump sum", max(75000, bua * 8), 18)]}, "16_overheads": {"name": "Professional Fees, Contingency and Overheads", "items": []}}
    elif discipline == "plumbing":
        bua = analysis.get("total_built_up_area_sqft", 10000)
        divisions = {"10_plumbing": {"name": "Plumbing and Sanitary", "items": [line("Water supply and drainage piping", bua, "sqft", 75, 18), line("Fixtures and CP fittings allowance", max(analysis.get("total_units", 1), 1), "unit", 45000, 18), line("Testing and commissioning", 1, "lump sum", max(60000, bua * 6), 18)]}, "16_overheads": {"name": "Professional Fees, Contingency and Overheads", "items": []}}
    else:
        bua = analysis.get("total_built_up_area_sqft", 10000)
        divisions = {"13_special_discipline": {"name": DRAWING_DISCIPLINES.get(discipline, "Discipline Works"), "items": [line("Discipline scope allowance", bua, "sqft", 150, 18), line("Testing and commissioning", 1, "lump sum", max(50000, bua * 5), 18)]}, "16_overheads": {"name": "Professional Fees, Contingency and Overheads", "items": []}}

    direct_total = sum(sum(i["amount"] for i in div["items"]) for key, div in divisions.items() if key != "16_overheads")
    divisions["16_overheads"]["items"] = [
        line("Design coordination and shop drawings", 1, "lump sum", direct_total * 0.035, 18),
        line("Contractor overheads and contingency", 1, "lump sum", direct_total * 0.085, 18),
    ]
    subtotal = sum(sum(i["amount"] for i in div["items"]) for div in divisions.values())
    for div_key, div in divisions.items():
        for index, item in enumerate(div["items"], start=1):
            item.setdefault("code", f"NIR-{discipline.upper()}-{div_key.split('_')[0]}-{index:02d}")
        div["amount"] = sum(i["amount"] for i in div["items"])
    gst = int(subtotal * 0.18)
    return {
        "currency": "INR",
        "built_up_area": analysis.get("total_built_up_area_sqft", 0),
        "cost_per_sqft": int(subtotal / max(analysis.get("total_built_up_area_sqft", 1), 1)),
        "subtotal": subtotal,
        "gst_12pct": gst,
        "gst_breakup": {"taxable_value": subtotal, "cgst_6pct": 0, "sgst_6pct": 0, "igst_12pct": gst, "total_gst": gst},
        "total_with_gst": subtotal + gst,
        "divisions": divisions,
        "rates_source": "Discipline-specific Delhi NCR seed rates",
        "disclaimer": f"Discipline-only {DRAWING_DISCIPLINES.get(discipline, discipline)} estimate. This is not a full building BOQ.",
    }

def calculate_estimate(analysis, takeoffs=None):
    if analysis.get("estimate_scope") == "discipline_only":
        return calculate_discipline_estimate(analysis, takeoffs)

    project_type = normalize_project_type(analysis.get("project_type"))
    category = cost_profile(project_type)
    is_villa = project_type == "villa" or "villa" in str(analysis.get("building_type", "")).lower() or "bungalow" in str(analysis.get("building_type", "")).lower()
    floor_wise = analysis.get("floor_wise_areas") if isinstance(analysis.get("floor_wise_areas"), dict) else {}
    physical_bua = safe_float(analysis.get("total_built_up_area_sqft"), 75000, 1)
    basement_area = safe_float(floor_wise.get("basement"), 0, 0)
    ground_area = safe_float(floor_wise.get("ground"), 0, 0)
    first_area = safe_float(floor_wise.get("first"), 0, 0)
    second_area = safe_float(floor_wise.get("second"), 0, 0)
    terrace_area = safe_float(floor_wise.get("terrace"), 0, 0)
    villa_floor_area = basement_area + ground_area + first_area + second_area + terrace_area
    if is_villa and villa_floor_area > 0:
        physical_bua = villa_floor_area
        bua = basement_area * 1.3 + ground_area + first_area + second_area + terrace_area * 0.35
    else:
        bua = physical_bua
    units = analysis.get("total_units", 60)
    lifts = analysis.get("lift_count", 3)
    parking = analysis.get("parking_spaces", 60)
    q = (takeoffs or {}).get("quantities") or {}
    rates = rate_lookup_map()
    rcc_factor = category["rcc_factor"]
    steel_factor = category["steel_factor"]
    mep_electrical_rate = category["electrical_rate"]
    plumbing_per_unit = category.get("plumbing_per_unit", 23500)
    plumbing_sqft_rate = category.get("plumbing_sqft_rate", 0)
    fire_rate = category["fire_rate"]
    facade_factor = category["facade_factor"]
    glazing_factor = category["glazing_factor"]
    flooring_factor = category["flooring_factor"]
    finish_multiplier = category["finish_multiplier"]
    door_qty = units * category.get("door_factor", 8) if category.get("door_factor") else max(6, int(physical_bua / category.get("door_area_divisor", 2200)))
    sanitary_qty = units * category.get("sanitary_factor", 2.4) if category.get("sanitary_factor") else max(2, int(physical_bua / category.get("sanitary_area_divisor", 2200)))
    plumbing_qty = units if plumbing_per_unit else physical_bua
    plumbing_rate = plumbing_per_unit if plumbing_per_unit else plumbing_sqft_rate
    lift_qty = lifts if not is_villa else max(lifts, 0)
    wet_area_waterproofing = units * 95 if category.get("sanitary_factor") else physical_bua * 0.04
    basement_levels = safe_int(analysis.get("basement_levels"), 0, 0)

    def item(desc, qty, unit, rate, gst_rate=12):
        rate = rates.get(ESTIMATE_RATE_ALIASES.get(desc, desc), rate)
        qty = round(float(qty), 2)
        rate = round(float(rate), 2)
        return {"desc": desc, "qty": qty, "unit": unit, "rate": rate, "gst_rate": gst_rate, "amount": int(qty * rate)}

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
                item("RCC columns, beams and slabs", (q.get("slab_area_sqft") or bua) * rcc_factor, "cum", 8400),
                item("TMT reinforcement Fe500D", bua * steel_factor, "kg", 82),
                item("Centering, shuttering and staging", bua * 1.08, "sqft", 115),
            ],
        },
        "05_masonry": {
            "name": "Masonry and Blockwork",
            "items": [
                item("AAC/block masonry external walls", q.get("wall_area_sqft") or bua * 0.32, "sqft", 145),
                item("Internal partition masonry", (q.get("wall_area_sqft") or bua * 0.46) * 0.72, "sqft", 112),
                item("Lintel, sill and minor RCC bands", bua * 0.05, "sqft", 165),
            ],
        },
        "06_doors_windows": {
            "name": "Doors, Windows and Glazing",
            "items": [
                item("Flush doors with hardware", door_qty, "each", 11800),
                item("Aluminium/uPVC windows with glazing", q.get("window_glazing_area_sqft") or bua * glazing_factor, "sqft", 520),
                item("Common area fire-rated and service doors", max(1, door_qty * 0.15), "each", 18500),
            ],
        },
        "07_finishes": {
            "name": "Interior Finishes",
            "items": [
                item("Internal plaster and putty base", q.get("plaster_paint_area_sqft") or bua * 1.8, "sqft", 42 * finish_multiplier),
                item("Vitrified tile flooring with skirting", q.get("flooring_area_sqft") or bua * flooring_factor, "sqft", 165 * finish_multiplier),
                item("Internal painting, primer and finish coats", q.get("plaster_paint_area_sqft") or bua * 1.75, "sqft", 36 * finish_multiplier),
            ],
        },
        "08_facade": {
            "name": "Exterior Finishes and Facade",
            "items": [
                item("External plaster and waterproof putty", q.get("facade_area_sqft") or bua * facade_factor, "sqft", 68),
                item("Weatherproof exterior paint", q.get("facade_area_sqft") or bua * facade_factor, "sqft", 48),
                item("Balcony railing and facade features", units * 70, "rft", 950),
            ],
        },
        "09_waterproofing": {
            "name": "Waterproofing and Insulation",
            "items": [
                item("Toilet and wet area waterproofing", wet_area_waterproofing, "sqft", 95),
                item("Terrace waterproofing treatment", bua * 0.085, "sqft", 130),
                item("Basement retaining wall waterproofing", bua * 0.035, "sqft", 210),
            ],
        },
        "10_plumbing": {
            "name": "Plumbing and Sanitary",
            "items": [
                item("CPVC/UPVC water supply and soil piping", plumbing_qty, "unit" if plumbing_per_unit else "sqft BUA", plumbing_rate),
                item("Sanitary fixtures and CP fittings", sanitary_qty, "toilet/fixture", 28500),
                item("UG tanks, pumps and terrace tanks", bua, "sqft BUA", 42),
            ],
        },
        "11_electrical": {
            "name": "Electrical Works",
            "items": [
                item("Conduiting, wiring and DBs", bua, "sqft BUA", mep_electrical_rate),
                item("Switches, fixtures and apartment panels", units, "unit", 36000),
                item("Transformer, DG integration and LT panels", bua, "sqft BUA", 48),
            ],
        },
        "12_fire": {
            "name": "Fire Fighting and Life Safety",
            "items": [
                item("Hydrant, sprinkler and fire piping", bua, "sqft BUA", fire_rate),
                item("Fire detection and alarm system", bua, "sqft BUA", 24),
                item("Staircase pressurization and signage", analysis.get("total_floors", 15), "floor", 85000),
            ],
        },
        "13_hvac": {
            "name": "Ventilation and Mechanical Services",
            "items": [
                item("Basement ventilation and jet fans", basement_levels, "level", 850000),
                item("Shaft ventilation and exhaust systems", units, "unit", 4200),
                item("Common services mechanical supports", bua, "sqft BUA", category["hvac_support_rate"]),
            ],
        },
        "14_lifts": {
            "name": "Lifts and Vertical Transportation",
            "items": [
                item("Passenger lift including installation", lift_qty, "each", 1250000),
                item("Lift civil interface and electrical provisions", lift_qty, "each", 180000),
                item("Annual testing and commissioning allowance", lift_qty, "each", 65000),
            ],
        },
        "15_external": {
            "name": "External Development and Parking",
            "items": [
                item("Driveways, paving and hardscape", q.get("site_development_area_sqft") or bua * 0.18, "sqft", 145),
                item("Boundary wall, gate and landscape works", bua * 0.09, "sqft", 165),
                item("Parking marking, EV provisions and signage", parking, "bay", 42000),
            ],
        },
        "17_luxury_amenities": {
            "name": "Special Amenities",
            "items": [],
        },
        "18_property_specific": {
            "name": "Property Type Specific Scope",
            "items": [],
        },
        "16_overheads": {
            "name": "Professional Fees, Contingency and Overheads",
            "items": [],
        },
    }

    if project_type == "industrial_warehouse":
        divisions["04_structure"]["items"] = [
            item("PEB primary steel structure design and supply", physical_bua, "sqft BUA", 420, 18),
            item("Foundation for PEB columns (isolated footings)", physical_bua * 0.012, "cum", 7800),
        ]
        divisions.pop("05_masonry", None)
        divisions["08_facade"]["items"] = [
            item("Ridge, gutter, flashing and rainwater accessories", physical_bua, "sqft BUA", 42, 18),
        ]

    if is_villa:
        amenities = analysis.get("luxury_amenities") if isinstance(analysis.get("luxury_amenities"), dict) else {}
        pool_area = safe_float(floor_wise.get("pool_landscape"), 0, 0)
        amenity_items = []
        if amenities.get("swimming_pool") or pool_area:
            amenity_items.append(item("Swimming pool civil, filtration and waterproofing", max(pool_area, 350), "sqft", 2850, 18))
        if amenities.get("sauna"):
            amenity_items.append(item("Sauna cabin and steam equipment", 1, "set", 650000, 18))
        if amenities.get("modular_kitchen"):
            amenity_items.append(item("Premium modular kitchen and appliances allowance", 1, "set", 1200000, 18))
        if amenities.get("home_automation"):
            amenity_items.append(item("Home automation, security and AV control", physical_bua, "sqft BUA", 180, 18))
        if amenities.get("pergola"):
            amenity_items.append(item("Pergola / outdoor covered seating", 1, "set", 450000, 18))
        if amenities.get("fire_pit"):
            amenity_items.append(item("Outdoor fire pit and seating feature", 1, "set", 220000, 18))
        if amenities.get("bar"):
            amenity_items.append(item("Bar counter, back bar and services", 1, "set", 550000, 18))
        if amenities.get("gym"):
            amenity_items.append(item("Home gym fit-out allowance", 1, "set", 500000, 18))
        if amenities.get("home_theater"):
            amenity_items.append(item("Home theater acoustic and AV allowance", 1, "set", 900000, 18))
        divisions["17_luxury_amenities"]["items"] = amenity_items
    if not divisions["17_luxury_amenities"]["items"]:
        divisions.pop("17_luxury_amenities", None)

    category_items = []
    if project_type == "group_housing":
        category_items = [
            item("Clubhouse and common amenity allowance", max(3000, physical_bua * 0.025), "sqft", 2200, 18),
            item("STP, water treatment and pump room systems", physical_bua, "sqft BUA", 38, 18),
            item("Internal roads, security gate and society services", physical_bua, "sqft BUA", 52, 18),
        ]
    elif project_type == "commercial_office":
        category_items = [
            item("Central HVAC plant and fresh air system allowance", physical_bua, "sqft BUA", 210, 18),
            item("Fire command, BMS and access control", physical_bua, "sqft BUA", 95, 18),
            item("Office lobby, common toilets and core finishes", max(physical_bua * 0.12, 2500), "sqft", 1850, 18),
        ]
    elif project_type == "mall_retail":
        category_items = [
            item("Escalators and travelator allowance", max(2, int(physical_bua / 45000)), "each", 4200000, 18),
            item("Food court, public toilets and retail back-of-house", max(physical_bua * 0.10, 6000), "sqft", 2400, 18),
            item("Mall atrium, signage, wayfinding and common lighting", physical_bua, "sqft BUA", 165, 18),
        ]
    elif project_type == "banquet_hall":
        category_items = [
            item("Banquet acoustic ceiling and decorative lighting", max(physical_bua * 0.55, 8000), "sqft", 1250, 18),
            item("Commercial kitchen and service back-of-house", max(physical_bua * 0.12, 2500), "sqft", 3200, 18),
            item("Stage, AV, sound and event power systems", 1, "lump sum", max(1800000, physical_bua * 85), 18),
        ]
    elif project_type == "hotel_hospitality":
        category_items = [
            item("Guest room interior fit-out allowance", max(units, 1), "key", 520000, 18),
            item("Commercial kitchen, laundry and BOH services", physical_bua, "sqft BUA", 115, 18),
            item("Reception, restaurant and public area finishes", max(physical_bua * 0.16, 5000), "sqft", 2600, 18),
        ]
    elif project_type == "industrial_warehouse":
        category_items = [
            item("PEB/warehouse roofing and wall cladding allowance", physical_bua, "sqft BUA", 380, 18),
            item("Dock levellers, shutters and loading bays", max(2, int(physical_bua / 25000)), "bay", 850000, 18),
            item("Heavy duty FM2/VDF industrial floor finish", physical_bua, "sqft BUA", 210, 18),
        ]
    elif project_type == "school_institution":
        category_items = [
            item("Classroom, laboratory and library fit-out allowance", max(physical_bua * 0.62, 12000), "sqft", 950, 18),
            item("Assembly, sports and multipurpose area allowance", max(physical_bua * 0.10, 3500), "sqft", 1250, 18),
            item("Campus safety, access control and public address systems", physical_bua, "sqft BUA", 48, 18),
        ]
    elif project_type == "hospital_healthcare":
        category_items = [
            item("Medical gas pipeline and nurse call allowance", max(units, 1), "bed", 72000, 18),
            item("OT, ICU, isolation and clinical services allowance", max(physical_bua * 0.18, 12000), "sqft", 2850, 18),
            item("Hospital HVAC filtration, BMS and backup systems", physical_bua, "sqft BUA", 210, 18),
        ]
    divisions["18_property_specific"]["items"] = category_items
    if not divisions["18_property_specific"]["items"]:
        divisions.pop("18_property_specific", None)

    direct_total = sum(sum(i["amount"] for i in div["items"]) for key, div in divisions.items() if key != "16_overheads")
    divisions["16_overheads"]["items"] = [
        item("Architectural, structural and MEP design fees", 1, "lump sum", direct_total * 0.055),
        item("Contractor overheads and profit", 1, "lump sum", direct_total * 0.105),
        item("Construction contingency allowance", 1, "lump sum", direct_total * 0.065),
    ]

    subtotal = sum(sum(i["amount"] for i in div["items"]) for div in divisions.values())
    for div_key, div in divisions.items():
        for index, line in enumerate(div.get("items", []), start=1):
            line.setdefault("code", f"NIR-CPWD-{div_key.split('_')[0]}-{index:02d}")
            line.setdefault("source", "CPWD/DSR benchmark + Delhi NCR seed")
            line.setdefault("gst_rate", 12)
        div["amount"] = sum(i["amount"] for i in div["items"])
    total = subtotal
    gst = int(sum(sum(i["amount"] * (i.get("gst_rate", 12) / 100) for i in div["items"]) for div in divisions.values()))

    return {
        "currency": "INR",
        "built_up_area": physical_bua,
        "cost_per_sqft": int(total / max(physical_bua, 1)),
        "subtotal": subtotal,
        "gst_12pct": gst,
        "gst_breakup": {
            "taxable_value": subtotal,
            "cgst_6pct": int(gst / 2),
            "sgst_6pct": int(gst / 2),
            "igst_12pct": 0,
            "total_gst": gst,
        },
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
    "wall_system": "aac_block",
    "window_glazing": "standard_upvc",
    "electrical_spec": "standard",
    "plumbing_spec": "standard",
    "floor_height_ft": 10,
    "forecast_months": 0,
    "total_floors": None,
    "basement_levels": None,
    "lift_count": None,
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
    normalized["wall_system"] = normalized["wall_system"] if normalized["wall_system"] in SPEC_FACTORS["wall_system"] else "aac_block"
    normalized["window_glazing"] = normalized["window_glazing"] if normalized["window_glazing"] in SPEC_FACTORS["window_glazing"] else "standard_upvc"
    normalized["electrical_spec"] = normalized["electrical_spec"] if normalized["electrical_spec"] in SPEC_FACTORS["electrical_spec"] else "standard"
    normalized["plumbing_spec"] = normalized["plumbing_spec"] if normalized["plumbing_spec"] in SPEC_FACTORS["plumbing_spec"] else "standard"
    normalized["steel_rate"] = safe_float(normalized.get("steel_rate"), 82, 45, 160)
    normalized["floor_height_ft"] = safe_float(normalized.get("floor_height_ft"), 10, 8, 16)
    normalized["forecast_months"] = safe_int(normalized.get("forecast_months"), 0, 0, 24)
    normalized["total_floors"] = safe_int(normalized.get("total_floors"), analysis.get("total_floors", 15), 1, 80)
    normalized["basement_levels"] = safe_int(normalized.get("basement_levels"), analysis.get("basement_levels", 0), 0, 8)
    normalized["lift_count"] = safe_int(normalized.get("lift_count"), analysis.get("lift_count", 2), 0, 24)
    return normalized

def recalc_estimate_totals(estimate):
    subtotal = 0
    gst = 0
    for div_key, div in estimate["divisions"].items():
        div_total = 0
        for index, item in enumerate(div.get("items", []), start=1):
            item["rate"] = round(float(item.get("rate", 0)), 2)
            item["amount"] = int(float(item.get("qty", 0)) * item["rate"])
            item.setdefault("gst_rate", 12)
            item.setdefault("code", f"NIR-CPWD-{div_key.split('_')[0]}-{index:02d}")
            item.setdefault("source", "User-edited BOQ and seed rate library")
            div_total += item["amount"]
            gst += item["amount"] * (safe_float(item.get("gst_rate"), 12, 0, 28) / 100)
        div["amount"] = div_total
        subtotal += div_total
    gst = int(gst)
    bua = max(safe_int(estimate.get("built_up_area"), 1, 1), 1)
    estimate["subtotal"] = subtotal
    estimate["gst_12pct"] = gst
    estimate["gst_breakup"] = {
        "taxable_value": subtotal,
        "cgst_6pct": int(gst / 2),
        "sgst_6pct": int(gst / 2),
        "igst_12pct": 0,
        "total_gst": gst,
    }
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

def apply_forecast_factor(estimate, months, affected):
    if months <= 0:
        return
    factor = 1 + min(months, 24) * 0.006
    for key, div in estimate["divisions"].items():
        if key == "16_overheads":
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
    apply_factor_to_divisions(estimate, ["05_masonry"], SPEC_FACTORS["wall_system"][options["wall_system"]], affected)
    apply_factor_to_divisions(estimate, ["06_doors_windows"], SPEC_FACTORS["window_glazing"][options["window_glazing"]], affected)
    apply_factor_to_divisions(estimate, ["11_electrical"], SPEC_FACTORS["electrical_spec"][options["electrical_spec"]], affected)
    apply_factor_to_divisions(estimate, ["10_plumbing"], SPEC_FACTORS["plumbing_spec"][options["plumbing_spec"]], affected)

    height_factor = 1 + max(options["floor_height_ft"] - 10, 0) * 0.025
    apply_factor_to_divisions(estimate, ["04_structure", "05_masonry", "08_facade", "10_plumbing", "11_electrical"], height_factor, affected)
    apply_forecast_factor(estimate, options["forecast_months"], affected)

    return recalc_estimate_totals(estimate), sorted(affected)

def scenario_line_item_impacts(base_estimate, revised_estimate, max_items=8):
    impacts = []
    for div_key, revised_div in (revised_estimate.get("divisions") or {}).items():
        base_div = (base_estimate.get("divisions") or {}).get(div_key, {})
        base_items = base_div.get("items", [])
        for index, revised_item in enumerate(revised_div.get("items", [])):
            base_item = base_items[index] if index < len(base_items) else {}
            base_amount = safe_float(base_item.get("amount"), 0, 0)
            revised_amount = safe_float(revised_item.get("amount"), 0, 0)
            delta = revised_amount - base_amount
            if abs(delta) < 1:
                continue
            impacts.append({
                "division": revised_div.get("name"),
                "code": revised_item.get("code") or f"NIR-{div_key}-{index + 1}",
                "desc": revised_item.get("desc"),
                "base_amount": int(base_amount),
                "revised_amount": int(revised_amount),
                "delta": int(delta),
            })
    impacts.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return impacts[:max_items]

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
        "line_item_impacts": scenario_line_item_impacts(base_estimate, revised_estimate),
        "summary": build_scenario_summary(options, delta, percent),
    }

def build_scenario_summary(options, delta, percent):
    direction = "increases" if delta >= 0 else "reduces"
    return (
        f"{options['name']} {direction} total cost by {abs(percent)}% using "
        f"{options['concrete_grade']} RCC, {options['cement_type']} cement, "
        f"{options['finish_level']} finishes, {options['facade']} facade, "
        f"{options['wall_system']} walls and {options['forecast_months']}-month price timing."
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
    analysis = project.get("analysis") or {}
    estimate = project.get("estimate") or {}
    parcel = project.get("parcel_data") or {}
    takeoffs = project.get("takeoffs") or {}
    quantities = takeoffs.get("quantities") or {}
    review = analysis.get("drawing_review") or {}
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
    bua = safe_float(analysis.get("total_built_up_area_sqft"), 0, 0)
    carpet = safe_float(analysis.get("total_carpet_area_sqft"), 0, 0)
    site_area = safe_float(parcel.get("site_area_sqft"), analysis.get("plot_area_sqft", 0), 0)
    total_cost = safe_float(estimate.get("total_with_gst"), 0, 0)
    subtotal = safe_float(estimate.get("subtotal"), 0, 0)
    gst = estimate.get("gst_breakup") or {}
    efficiency = round((carpet / bua) * 100, 2) if bua else 0
    far_used = round(bua / site_area, 2) if site_area else 0
    contingency = 0
    overhead = (estimate.get("divisions") or {}).get("16_overheads") or {}
    for item in overhead.get("items", []):
        if "contingency" in (item.get("desc") or "").lower():
            contingency += safe_float(item.get("amount"), 0, 0)
    metrics = {
        "gross_construction_area_sqft": bua,
        "carpet_area_sqft": carpet,
        "efficiency_pct": efficiency,
        "site_area_sqft": site_area,
        "far_used": far_used,
        "permissible_far": parcel.get("permissible_far") or 0,
        "total_cost_with_gst": total_cost,
        "subtotal": subtotal,
        "gst_total": gst.get("total_gst", estimate.get("gst_12pct", 0)),
        "cgst_6pct": gst.get("cgst_6pct", 0),
        "sgst_6pct": gst.get("sgst_6pct", 0),
        "cost_per_sqft": estimate.get("cost_per_sqft", 0),
        "contingency": int(contingency),
        "facade_area_sqft": quantities.get("facade_area_sqft", 0),
        "glazing_area_sqft": quantities.get("window_glazing_area_sqft", 0),
        "flooring_area_sqft": quantities.get("flooring_area_sqft", 0),
        "parking_spaces": analysis.get("parking_spaces", 0),
        "floors": analysis.get("total_floors", 0),
        "units": analysis.get("total_units", 0),
    }
    sections = {
        "project_overview": {
            "name": project.get("name"),
            "address": project.get("address"),
            "building_type": analysis.get("building_type"),
            "structure_type": analysis.get("structure_type"),
            "status": project.get("status"),
        },
        "land_rera": {
            "authority": parcel.get("authority"),
            "rera_number": parcel.get("rera_number"),
            "plot_number": parcel.get("plot_number"),
            "khasra_number": parcel.get("khasra_number"),
            "land_use": parcel.get("land_use"),
            "gis_reference": parcel.get("gis_reference"),
            "verification_status": parcel.get("verification_status"),
            "boundary_area_sqft": parcel.get("boundary_area_sqft"),
        },
        "unit_mix": analysis.get("unit_types") or [],
        "takeoffs": quantities,
        "material_schedule": takeoffs.get("material_schedule") or {},
        "drawing_intelligence": {
            "sheets": project.get("drawing_sheets") or [],
            "regions": project.get("drawing_regions") or [],
            "model_reconstruction": takeoffs.get("model_reconstruction") or {},
        },
        "cost": {
            "divisions": estimate.get("divisions") or {},
            "gst_breakup": gst,
            "rates_source": estimate.get("rates_source"),
        },
        "risks": review.get("risks") or [],
        "missing_information": review.get("missing_information") or [],
        "assumptions": review.get("assumptions") or [],
    }
    return {
        "generated_at": now(),
        "project": project,
        "metrics": metrics,
        "sections": sections,
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
    writer.writerow(["Taxable Value", estimate.get("subtotal")])
    writer.writerow(["CGST 6%", (estimate.get("gst_breakup") or {}).get("cgst_6pct")])
    writer.writerow(["SGST 6%", (estimate.get("gst_breakup") or {}).get("sgst_6pct")])
    writer.writerow(["IGST", (estimate.get("gst_breakup") or {}).get("igst_12pct")])
    writer.writerow(["Total GST", (estimate.get("gst_breakup") or {}).get("total_gst")])
    writer.writerow(["Total With GST", estimate.get("total_with_gst")])
    writer.writerow(["Cost Per Sqft", estimate.get("cost_per_sqft")])
    writer.writerow([])
    writer.writerow(["Division", "BOQ Code", "Description", "Qty", "Unit", "Rate", "GST %", "Amount", "Source"])
    for key, div in (estimate.get("divisions") or {}).items():
        for item in div.get("items", []):
            writer.writerow([div.get("name"), item.get("code"), item.get("desc"), item.get("qty"), item.get("unit"), item.get("rate"), item.get("gst_rate", 12), item.get("amount"), item.get("source", "")])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=nirman_report_{project_id}.csv"}
    )

@app.route("/api/projects/<project_id>/investor-report.csv", methods=["GET"])
@require_auth
def project_investor_report_csv(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before exporting a report."}), 400
    report = project_report_payload(row)
    project = report["project"]
    metrics = report["metrics"]
    sections = report["sections"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nirman.AI Bank / Investor Report"])
    writer.writerow(["Generated At", report["generated_at"]])
    writer.writerow([])
    writer.writerow(["Project Overview"])
    for key, value in sections["project_overview"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Land / RERA Summary"])
    for key, value in sections["land_rera"].items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Key Metrics"])
    for key, value in metrics.items():
        writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Unit Mix"])
    writer.writerow(["type", "count", "carpet_area_sqft"])
    for unit in sections["unit_mix"]:
        writer.writerow([unit.get("type"), unit.get("count"), unit.get("carpet_area_sqft")])
    writer.writerow([])
    writer.writerow(["Takeoff Quantities"])
    for key, value in sections["takeoffs"].items():
        writer.writerow([key, value, "sqft"])
    writer.writerow([])
    writer.writerow(["Risks"])
    for item in sections["risks"]:
        writer.writerow([item])
    writer.writerow([])
    writer.writerow(["Missing Information"])
    for item in sections["missing_information"]:
        writer.writerow([item])
    writer.writerow([])
    writer.writerow(["Saved Scenarios"])
    writer.writerow(["name", "base_total", "revised_total", "delta", "delta_percent"])
    for scenario in report["scenarios"]:
        result = scenario.get("result") or {}
        writer.writerow([scenario.get("name"), result.get("base_total"), result.get("revised_total"), result.get("delta"), result.get("delta_percent")])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=nirman_investor_report_{project_id}.csv"}
    )

@app.route("/api/projects/<project_id>/takeoffs.csv", methods=["GET"])
@require_auth
def project_takeoffs_csv(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["takeoffs"]:
        return jsonify({"success": False, "message": "Generate takeoffs before exporting."}), 400
    takeoffs = json.loads(row["takeoffs"])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nirman.AI Automated Takeoffs"])
    writer.writerow(["Project", row["name"]])
    writer.writerow(["Generated At", now()])
    writer.writerow(["Method", takeoffs.get("method")])
    writer.writerow([])
    writer.writerow(["Quantity", "Value", "Unit"])
    for key, value in (takeoffs.get("quantities") or {}).items():
        writer.writerow([key, value, "sqft"])
    writer.writerow([])
    writer.writerow(["Assumptions"])
    for item in takeoffs.get("assumptions") or []:
        writer.writerow([item])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=nirman_takeoffs_{project_id}.csv"}
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
    rates = db.execute("SELECT COUNT(*) FROM rate_items").fetchone()[0]

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
            "rate_items": rates,
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

@app.route("/api/admin/rates", methods=["GET", "PUT"])
def admin_rates():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    db = get_db()
    if request.method == "GET":
        return jsonify({"success": True, "rates": rate_items_by_category()})

    body = request.get_json() or {}
    rates = body.get("rates") or []
    if not isinstance(rates, list):
        return jsonify({"success": False, "message": "Rates must be a list."}), 400

    saved = []
    for raw in rates[:300]:
        if not isinstance(raw, dict):
            continue
        item = (raw.get("item") or "").strip()
        if not item:
            continue
        rate_id = raw.get("id") or uid()
        category = raw.get("category") if raw.get("category") in ["materials", "labour", "boq"] else "boq"
        unit = (raw.get("unit") or "unit").strip()
        rate = safe_float(raw.get("rate"), 0, 0)
        source = (raw.get("source") or "Admin edited").strip()
        city = (raw.get("city") or "Delhi NCR").strip()
        db.execute(
            """
            INSERT INTO rate_items (id, category, item, unit, rate, source, city, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item) DO UPDATE SET
                category = excluded.category,
                unit = excluded.unit,
                rate = excluded.rate,
                source = excluded.source,
                city = excluded.city,
                updated_at = excluded.updated_at
            """,
            (rate_id, category, item, unit, rate, source, city, now())
        )
        saved.append(item)
    db.commit()
    return jsonify({"success": True, "message": f"Saved {len(saved)} rates.", "rates": rate_items_by_category()})

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Nirman.AI running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
