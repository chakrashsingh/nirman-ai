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
import time
import html
import mimetypes
import urllib.error
import urllib.request
import urllib.parse

from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS

try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None

app = Flask(__name__)
CORS(app)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PERSISTENT_DATA_DIR = os.environ.get("NIRMAN_DATA_DIR") or ("/var/data" if os.path.isdir("/var/data") else APP_DIR)
DB_PATH = os.environ.get("NIRMAN_DB_PATH") or os.path.join(PERSISTENT_DATA_DIR, "nirman.db")
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL") or ""
USE_POSTGRES = bool(DATABASE_URL)
UPLOAD_DIR = os.environ.get("NIRMAN_UPLOAD_DIR") or os.path.join(PERSISTENT_DATA_DIR, "uploads")
PAGE_RENDER_DIR = os.environ.get("NIRMAN_PAGE_DIR") or os.path.join(PERSISTENT_DATA_DIR, "pages")
WAITLIST_PUBLIC_BASE = int(os.environ.get("WAITLIST_PUBLIC_BASE", "40"))
for directory in ([UPLOAD_DIR, PAGE_RENDER_DIR] if USE_POSTGRES else [os.path.dirname(DB_PATH), UPLOAD_DIR, PAGE_RENDER_DIR]):
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

LOCATION_COST_FACTORS = [
    (["lutyens", "chanakyapuri", "jor bagh", "prithviraj road"], 1.32, "Lutyens / prime Delhi bungalow market"),
    (["malibu", "golf course", "golf course road", "dlf", "gurugram", "gurgaon"], 1.16, "Premium Gurugram/NCR micro-market"),
    (["south delhi", "vasant", "defence colony", "greater kailash", "saket"], 1.18, "Premium South Delhi micro-market"),
    (["delhi", "new delhi"], 1.08, "Delhi city market"),
    (["noida", "greater noida", "yamuna expressway"], 0.98, "Noida/Greater Noida market"),
    (["faridabad", "ghaziabad"], 0.92, "Peripheral NCR market"),
    (["mumbai", "thane", "navi mumbai"], 1.22, "Mumbai/MMR market"),
    (["bengaluru", "bangalore"], 1.12, "Bengaluru market"),
]

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
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "auto").strip()
GEMINI_MODEL_PREFERENCE = os.environ.get(
    "GEMINI_MODEL_PREFERENCE",
    "gemini-2.5-pro,gemini-2.5-flash,gemini-2.0-flash",
)
AI_PROVIDER = os.environ.get("AI_PROVIDER", "").strip().lower()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_UPLOADS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".dxf": "application/dxf",
    ".dwg": "application/octet-stream",
}
ENABLE_AI_VALIDATION = os.environ.get("ENABLE_AI_VALIDATION", "true").strip().lower() not in ("0", "false", "no")

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
        {"item": "Cement OPC 43", "unit": "bag", "rate": 430, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Cement OPC 53", "unit": "bag", "rate": 450, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "PPC Cement", "unit": "bag", "rate": 405, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "TMT Steel Fe500D", "unit": "kg", "rate": 90, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Ready Mix Concrete M25", "unit": "cum", "rate": 9500, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Ready Mix Concrete M30", "unit": "cum", "rate": 9900, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "AAC/block masonry", "unit": "sqft", "rate": 175, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Vitrified flooring", "unit": "sqft", "rate": 210, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Premium vitrified / large format flooring", "unit": "sqft", "rate": 285, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Granite / marble flooring allowance", "unit": "sqft", "rate": 420, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Aluminium/uPVC windows with glazing", "unit": "sqft", "rate": 650, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Curtain wall glazing", "unit": "sqft", "rate": 1350, "source": "Delhi NCR 2026 calibrated seed"},
    ],
    "labour": [
        {"item": "Mason labour", "unit": "day", "rate": 1150, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Helper labour", "unit": "day", "rate": 800, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Shuttering carpenter", "unit": "day", "rate": 1350, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Steel fixer", "unit": "day", "rate": 1250, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Electrician labour", "unit": "day", "rate": 1200, "source": "Delhi NCR 2026 calibrated seed"},
        {"item": "Plumber labour", "unit": "day", "rate": 1150, "source": "Delhi NCR 2026 calibrated seed"},
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
  "spec_level": "economy|standard|premium|luxury",
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
  "detected_features": [
    {"name":"Indoor gym","category":"amenity","area_sqft":1200,"quantity":1,"unit":"space","confidence":"high","source":"Page 4 label: Indoor Gym","included":true}
  ],
  "field_confidence": {
    "total_built_up_area_sqft": "high|medium|low",
    "plot_area_sqft": "high|medium|low",
    "total_floors": "high|medium|low",
    "floor_wise_areas": "high|medium|low",
    "detected_features": "high|medium|low",
    "discipline_takeoff": "high|medium|low"
  },
  "field_evidence": {
    "total_built_up_area_sqft": "Page 2 area schedule says ...",
    "plot_area_sqft": "Title block/site schedule says ...",
    "total_floors": "Elevation/floor labels show ...",
    "floor_wise_areas": "Area schedule/floor labels show ...",
    "detected_features": "Visible labels include ...",
    "discipline_takeoff": "Equipment schedule or tags show ..."
  },
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
- Prefer visible drawing text, title blocks, schedules, room labels and dimension notes over generic assumptions.
- If a value is visible, prefill it directly. If a value is not visible, infer conservatively and list it under assumptions.
- Read every page, including site plan, floor plans, roof/terrace plans, sections, elevations, schedules and MEP sheets.
- Detect plot/site area from labels such as plot area, site area, land area, khasra area, property area, sq m, sqm, sq.ft, acres or hectares.
- Detect floor count from labels such as basement, lower ground, ground floor, first floor, second floor, terrace, roof, section markers and elevation floor-height markers.
- Detect floor-wise areas from area schedules, title blocks, room schedules and plan labels. For villas, fill basement, ground, first, second, terrace and pool_landscape where visible.
- Detect specification level from drawing notes, title blocks, brand notes and visible labels. Use luxury only for high-end villas/hotels/premium projects with evidence; otherwise use standard.
- Detect ALL labelled project spaces, amenities and functional rooms from explicit drawing labels. Do not limit detection to villas.
- Examples: clubhouse, indoor gym, outdoor gym, indoor games, kids play area, creche, party hall, banquet hall, multipurpose hall, society office, guard room, STP, pump room, classrooms, labs, library, auditorium, cafeteria, infirmary, pantry, restaurant, commercial kitchen, laundry, spa, lobby, BOH, anchor store, food court, escalator, atrium, ICU, OT, wards, pharmacy, diagnostic lab, medical gas room, dock bays, PEB shed, VDF flooring and loading area.
- For every detected feature, add an object to detected_features with a concrete source/evidence string such as page number, visible label, schedule row or title-block note.
- For every key numeric field, return field_confidence and field_evidence. Use high only when the drawing visibly states it, medium when inferred from visible labels/dimensions, and low when guessed.
- Set luxury_amenities booleans for backward compatibility only when those exact amenities are visible. The broader detected_features array is the primary source for project-specific estimate additions.
- If the sheet is HVAC, electrical, plumbing, fire, structural, or interior-only, set estimate_scope to "discipline_only" and do not generate full-project assumptions.
- If the selected/building type is villa or independent house, do not assume tower-style lifts, basements or apartment unit mixes.
- If the project is a standalone villa/bungalow, set total_units = 1, building_type = "Villa", estimate floor_wise_areas, auto-select visible amenities such as pool/sauna/bar/gym/home theater/pergola/fire pit, and list HVAC units with hp_rating when visible.
- In drawing_review.assumptions, include short evidence notes for each auto-selected amenity and each inferred area/floor value.
- Use school_institution for schools, colleges and educational campuses. Use hospital_healthcare for hospitals, clinics and healthcare buildings.
- Never include markdown, commentary or code fences.
"""

NIRMAN_VALIDATION_PROMPT = """
You are Nirman.AI's senior Indian quantity surveyor validation pass.
Review the extracted drawing data and the engine-generated BOQ estimate.
Return ONLY valid JSON with this shape:
{
  "status": "ok|needs_review",
  "summary": "short plain-language validation summary",
  "flags": [{"severity":"low|medium|high","field":"BUA","message":"what may be wrong","recommendation":"what user should verify"}],
  "missing_scope": [{"item":"Swimming pool filtration","reason":"pool visible but missing service line","suggested_allowance_inr":350000}],
  "quantity_corrections": [{"field":"total_built_up_area_sqft","current":7500,"suggested":12000,"confidence":"medium","evidence":"Page 2 area schedule"}],
  "range_adjustment_pct": 0,
  "user_questions": ["Confirm sanctioned built-up area from area statement."]
}
Rules:
- Do not invent rates.
- Do not rewrite the whole estimate.
- Only flag issues supported by drawing evidence, extracted fields, or obvious construction logic.
- If the drawing is discipline-only, validate that the report clearly says it is not a full-project BOQ.
- For Indian projects, call out GST, CPWD/DSR, RERA/statutory, FAR/FSI, MEP and amenity gaps where relevant.
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

class PostgresDB:
    def __init__(self, conn):
        self.conn = conn

    def _cursor(self):
        # Always use DictCursor so fetchone()["col"] works consistently.
        return self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def execute(self, sql, params=()):
        cur = self._cursor()
        cur.execute(self.convert_sql(sql), params or ())
        return cur

    def executescript(self, script):
        # psycopg2 does not support multiple statements in one execute() call.
        # Split on semicolons and run each non-empty statement individually.
        cur = self._cursor()
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for stmt in statements:
            cur.execute(stmt)
        return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    @staticmethod
    def convert_sql(sql):
        sql = sql.replace("?", "%s")
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        # Convert SQLite ON CONFLICT(col) DO UPDATE SET ... = excluded.col
        # to Postgres syntax (already valid) — no change needed there.
        # Convert "ON CONFLICT(item) DO NOTHING" for Postgres compatibility.
        sql = re.sub(r"ON CONFLICT\((\w+)\) DO NOTHING", r"ON CONFLICT(\1) DO NOTHING", sql)
        return sql

def get_db():
    if "db" not in g:
        if USE_POSTGRES:
            if psycopg2 is None:
                raise RuntimeError("psycopg2-binary is required when DATABASE_URL/SUPABASE_DATABASE_URL is configured.")
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
            g.db = PostgresDB(conn)
        else:
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
        if USE_POSTGRES:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    company TEXT,
                    role TEXT,
                    city TEXT,
                    plan TEXT DEFAULT 'free',
                    usage_month TEXT,
                    usage_count INTEGER DEFAULT 0,
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
                    file_data BYTEA,
                    file_path TEXT,
                    page_manifest TEXT,
                    parcel_data TEXT,
                    drawing_sheets TEXT,
                    drawing_regions TEXT,
                    takeoffs TEXT,
                    analysis TEXT,
                    estimate TEXT,
                    share_token TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS waitlist (
                    id SERIAL PRIMARY KEY,
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
                CREATE TABLE IF NOT EXISTS detected_features (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    user_id TEXT,
                    name TEXT NOT NULL,
                    category TEXT,
                    area_sqft REAL DEFAULT 0,
                    quantity REAL DEFAULT 1,
                    unit TEXT DEFAULT 'item',
                    confidence TEXT DEFAULT 'medium',
                    source TEXT,
                    included BOOLEAN DEFAULT TRUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS historical_boqs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    user_id TEXT,
                    file_name TEXT,
                    file_mime TEXT,
                    file_size INTEGER,
                    file_data BYTEA,
                    parsed_data TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cpwd_items (
                    id TEXT PRIMARY KEY,
                    code TEXT UNIQUE,
                    description TEXT NOT NULL,
                    unit TEXT,
                    rate REAL,
                    source TEXT,
                    city TEXT DEFAULT 'Delhi NCR',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS material_rates (
                    id TEXT PRIMARY KEY,
                    material TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    rate REAL NOT NULL,
                    city TEXT DEFAULT 'Delhi NCR',
                    supplier TEXT,
                    source TEXT,
                    effective_date TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS drawing_files (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    user_id TEXT,
                    file_name TEXT NOT NULL,
                    file_mime TEXT,
                    file_size INTEGER,
                    file_data BYTEA,
                    file_path TEXT,
                    file_kind TEXT DEFAULT 'drawing',
                    parsed_text TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS estimate_feedback (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    user_id TEXT,
                    rating TEXT NOT NULL,
                    comment TEXT,
                    actual_cost REAL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contractor_quotes (
                    id TEXT PRIMARY KEY,
                    material TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    rate REAL NOT NULL,
                    city TEXT DEFAULT 'Delhi NCR',
                    contractor_name TEXT,
                    source TEXT,
                    quote_date TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_corrections (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    user_id TEXT,
                    division TEXT,
                    item TEXT,
                    old_rate REAL,
                    corrected_rate REAL,
                    city TEXT,
                    property_type TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report_deliveries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    user_id TEXT,
                    channel TEXT NOT NULL,
                    recipient TEXT,
                    share_token TEXT,
                    status TEXT DEFAULT 'created',
                    created_at TEXT NOT NULL
                );
            """)
            ensure_schema(db)
            seed_rate_items(db)
            db.commit()
            return
        db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    company TEXT,
                    role TEXT,
                    city TEXT,
                    plan TEXT DEFAULT 'free',
                    usage_month TEXT,
                    usage_count INTEGER DEFAULT 0,
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
                share_token TEXT UNIQUE,
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
            CREATE TABLE IF NOT EXISTS detected_features (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                user_id TEXT,
                name TEXT NOT NULL,
                category TEXT,
                area_sqft REAL DEFAULT 0,
                quantity REAL DEFAULT 1,
                unit TEXT DEFAULT 'item',
                confidence TEXT DEFAULT 'medium',
                source TEXT,
                included INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS historical_boqs (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_id TEXT,
                file_name TEXT,
                file_mime TEXT,
                file_size INTEGER,
                file_data BLOB,
                parsed_data TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cpwd_items (
                id TEXT PRIMARY KEY,
                code TEXT UNIQUE,
                description TEXT NOT NULL,
                unit TEXT,
                rate REAL,
                source TEXT,
                city TEXT DEFAULT 'Delhi NCR',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS material_rates (
                id TEXT PRIMARY KEY,
                material TEXT NOT NULL,
                unit TEXT NOT NULL,
                rate REAL NOT NULL,
                city TEXT DEFAULT 'Delhi NCR',
                supplier TEXT,
                source TEXT,
                effective_date TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS drawing_files (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_id TEXT,
                file_name TEXT NOT NULL,
                file_mime TEXT,
                file_size INTEGER,
                file_data BLOB,
                file_path TEXT,
                file_kind TEXT DEFAULT 'drawing',
                parsed_text TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS estimate_feedback (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_id TEXT,
                rating TEXT NOT NULL,
                comment TEXT,
                actual_cost REAL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contractor_quotes (
                id TEXT PRIMARY KEY,
                material TEXT NOT NULL,
                unit TEXT NOT NULL,
                rate REAL NOT NULL,
                city TEXT DEFAULT 'Delhi NCR',
                contractor_name TEXT,
                source TEXT,
                quote_date TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rate_corrections (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_id TEXT,
                division TEXT,
                item TEXT,
                old_rate REAL,
                corrected_rate REAL,
                city TEXT,
                property_type TEXT,
                comment TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_deliveries (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                user_id TEXT,
                channel TEXT NOT NULL,
                recipient TEXT,
                share_token TEXT,
                status TEXT DEFAULT 'created',
                created_at TEXT NOT NULL
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
            "share_token": "ALTER TABLE projects ADD COLUMN share_token TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing:
                db.execute(sql)
        existing_users = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        user_migrations = {
            "plan": "ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'",
            "usage_month": "ALTER TABLE users ADD COLUMN usage_month TEXT",
            "usage_count": "ALTER TABLE users ADD COLUMN usage_count INTEGER DEFAULT 0",
        }
        for col, sql in user_migrations.items():
            if col not in existing_users:
                db.execute(sql)
        ensure_schema(db)
        seed_rate_items(db)
        db.commit()

def ensure_schema(db):
    if not USE_POSTGRES:
        return
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS usage_month TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE",
    ]
    for sql in migrations:
        db.execute(sql)

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

def record_usage(user_id):
    if not user_id:
        return
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    try:
        row = get_db().execute("SELECT usage_month, usage_count FROM users WHERE id = ?", (user_id,)).fetchone()
        current_month = row["usage_month"] if row and "usage_month" in row.keys() else None
        current_count = safe_int(row["usage_count"], 0, 0) if row and "usage_count" in row.keys() else 0
        next_count = current_count + 1 if current_month == month else 1
        get_db().execute("UPDATE users SET usage_month = ?, usage_count = ? WHERE id = ?", (month, next_count, user_id))
    except Exception:
        pass

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

def save_detected_features(db, project_id, user_id, features):
    db.execute("DELETE FROM detected_features WHERE project_id = ?", (project_id,))
    for feature in features if isinstance(features, list) else []:
        if not isinstance(feature, dict) or not feature.get("name"):
            continue
        db.execute(
            """
            INSERT INTO detected_features
            (id, project_id, user_id, name, category, area_sqft, quantity, unit, confidence, source, included, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid(),
                project_id,
                user_id,
                str(feature.get("name") or "")[:80],
                str(feature.get("category") or "detected_space")[:60],
                safe_float(feature.get("area_sqft"), 0, 0),
                safe_float(feature.get("quantity"), 1, 0),
                str(feature.get("unit") or "space")[:30],
                str(feature.get("confidence") or "medium")[:20],
                str(feature.get("source") or "")[:240],
                bool(feature.get("included", True)),
                now(),
            )
        )

def count_actual_waitlist():
    return get_db().execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]

def db_blob(data):
    if USE_POSTGRES and psycopg2 is not None:
        return psycopg2.Binary(data)
    return sqlite3.Binary(data)

def require_admin_key():
    return request.args.get("key") == ADMIN_KEY or request.headers.get("X-Admin-Key") == ADMIN_KEY

def validate_upload(file):
    filename = (file.filename or "").strip()
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_UPLOADS:
        return None, None, "Only PDF, PNG, JPG, JPEG, DXF and DWG drawings are supported."
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
    if file_mime == "application/dxf" or file_path.lower().endswith(".dxf"):
        try:
            import ezdxf
            doc = ezdxf.readfile(file_path)
            labels = []
            for entity in doc.modelspace():
                dxftype = entity.dxftype()
                if dxftype in ("TEXT", "MTEXT"):
                    labels.append(getattr(entity, "plain_text", lambda: entity.dxf.text)())
                elif dxftype in ("LINE", "LWPOLYLINE", "POLYLINE", "INSERT", "DIMENSION"):
                    labels.append(dxftype)
                if len(labels) > 2000:
                    break
            return "\n".join(str(item) for item in labels)[:12000]
        except Exception as exc:
            return f"DXF parsing unavailable or failed: {exc}"
    if file_path.lower().endswith(".dwg"):
        return "DWG uploaded. Convert to DXF for exact CAD geometry extraction; Claude will still inspect exported PDF/image drawings."
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
    outdoor_sets = 0
    if not text:
        return {"equipment": [], "total_tr": 0, "total_cfm": 0, "outdoor_unit_sets": 0}
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
            outdoor_sets += qty
        equipment.append({"type": eq_type, "qty": qty, "hp": hp, "tr": tr, "cfm": cfm, "notes": label or eq_type})
        total_tr += qty * tr
        total_cfm += qty * cfm
    if not outdoor_sets:
        circuit_matches = re.findall(r"\b(?:CKT|CIRCUIT)\s*[-:]?\s*\d+\b[^\n]{0,100}?\bODU\b|\bODU\b[^\n]{0,100}?\b(?:CKT|CIRCUIT)\s*[-:]?\s*\d+\b", text, re.I)
        outdoor_sets = len(circuit_matches)
    if not outdoor_sets:
        outdoor_sets = len(re.findall(r"\bODU\b", text, re.I))
    return {"equipment": equipment[:40], "total_tr": round(total_tr, 2), "total_cfm": round(total_cfm, 2), "outdoor_unit_sets": int(outdoor_sets)}

VISIBLE_AMENITY_PATTERNS = {
    "swimming_pool": [r"\bswimming\s+pool\b", r"\bpool\b", r"\bjacuzzi\b"],
    "sauna": [r"\bsauna\b", r"\bsteam\s+room\b", r"\bsteam\b"],
    "modular_kitchen": [r"\bmodular\s+kitchen\b", r"\bkitchen\b", r"\bshow\s+kitchen\b"],
    "home_automation": [r"\bhome\s+automation\b", r"\bsmart\s+home\b", r"\bautomation\b", r"\bsecurity\s+control\b", r"\bav\s+control\b"],
    "pergola": [r"\bpergola\b", r"\bcovered\s+sitting\b", r"\bcovered\s+seating\b"],
    "fire_pit": [r"\bfire\s*pit\b", r"\bbonfire\b"],
    "bar": [r"\bbar\b", r"\blounge\s+bar\b"],
    "gym": [r"\bgym\b", r"\bfitness\b"],
    "home_theater": [r"\bhome\s+theat(?:er|re)\b", r"\btheat(?:er|re)\b", r"\bmedia\s+room\b"],
}

VISIBLE_FEATURE_PATTERNS = {
    "Indoor gym": ("amenity", [r"\bindoor\s+gym\b", r"\bgym\b", r"\bfitness\b"]),
    "Indoor games room": ("amenity", [r"\bindoor\s+games?\b", r"\bgames?\s+room\b"]),
    "Kids play area": ("amenity", [r"\bkids?\s+play\b", r"\bchildren'?s?\s+play\b", r"\btoddler\s+play\b"]),
    "Clubhouse": ("amenity", [r"\bclub\s*house\b", r"\bclubhouse\b"]),
    "Party hall": ("amenity", [r"\bparty\s+hall\b", r"\bmultipurpose\s+hall\b", r"\bcommunity\s+hall\b"]),
    "Banquet hall": ("amenity", [r"\bbanquet\b", r"\bevent\s+hall\b"]),
    "Creche": ("amenity", [r"\bcreche\b", r"\bday\s*care\b"]),
    "Society office": ("support", [r"\bsociety\s+office\b", r"\bassociation\s+office\b"]),
    "Guard room": ("security", [r"\bguard\s+room\b", r"\bsecurity\s+room\b"]),
    "STP": ("services", [r"\bstp\b", r"\bsewage\s+treatment\b"]),
    "Pump room": ("services", [r"\bpump\s+room\b"]),
    "Classroom": ("education", [r"\bclass\s*room\b", r"\bclassroom\b"]),
    "Laboratory": ("education", [r"\blab(?:oratory)?\b", r"\bphysics\s+lab\b", r"\bchemistry\s+lab\b", r"\bbiology\s+lab\b", r"\bcomputer\s+lab\b"]),
    "Library": ("education", [r"\blibrary\b"]),
    "Auditorium": ("education", [r"\bauditorium\b"]),
    "Cafeteria": ("food_service", [r"\bcafeteria\b", r"\bcanteen\b"]),
    "Infirmary": ("healthcare", [r"\binfirmary\b", r"\bfirst\s+aid\b"]),
    "Pantry": ("food_service", [r"\bpantry\b"]),
    "Restaurant": ("food_service", [r"\brestaurant\b", r"\bdining\b"]),
    "Commercial kitchen": ("food_service", [r"\bcommercial\s+kitchen\b", r"\bkitchen\b"]),
    "Laundry": ("hospitality", [r"\blaundry\b"]),
    "Spa": ("hospitality", [r"\bspa\b", r"\bmassage\b"]),
    "Lobby": ("hospitality", [r"\blobby\b", r"\breception\b"]),
    "Back of house": ("hospitality", [r"\bboh\b", r"\bback\s+of\s+house\b", r"\bservice\s+corridor\b"]),
    "Food court": ("retail", [r"\bfood\s+court\b"]),
    "Anchor store": ("retail", [r"\banchor\s+store\b", r"\bhypermarket\b"]),
    "Escalator": ("vertical_transport", [r"\bescalator\b"]),
    "Atrium": ("retail", [r"\batrium\b"]),
    "ICU": ("healthcare", [r"\bicu\b", r"\bintensive\s+care\b"]),
    "Operation theatre": ("healthcare", [r"\bot\b", r"\boperation\s+theat(?:er|re)\b"]),
    "Ward": ("healthcare", [r"\bward\b", r"\bpatient\s+room\b"]),
    "Pharmacy": ("healthcare", [r"\bpharmacy\b"]),
    "Diagnostic lab": ("healthcare", [r"\bdiagnostic\b", r"\bpathology\b", r"\bradiology\b"]),
    "Medical gas room": ("healthcare", [r"\bmedical\s+gas\b", r"\bmgps\b"]),
    "Dock bay": ("warehouse", [r"\bdock\s+bay\b", r"\bloading\s+dock\b"]),
    "Loading area": ("warehouse", [r"\bloading\s+area\b", r"\bloading\b"]),
    "PEB shed": ("warehouse", [r"\bpeb\b", r"\bpre[-\s]?engineered\b"]),
    "VDF flooring": ("warehouse", [r"\bvdf\b", r"\bvacuum\s+dewatered\b"]),
}

FEATURE_RATE_RULES = [
    (["gym", "games", "clubhouse", "party hall", "banquet", "auditorium"], "sqft", 2200),
    (["kids play", "creche", "society office", "guard room", "library", "classroom", "lobby", "reception"], "sqft", 1600),
    (["lab", "laboratory", "diagnostic", "pharmacy", "icu", "operation theatre", "medical gas"], "sqft", 3200),
    (["kitchen", "pantry", "restaurant", "cafeteria", "canteen", "food court"], "sqft", 2800),
    (["laundry", "spa", "boh", "back of house"], "sqft", 2400),
    (["stp", "pump room"], "set", 850000),
    (["escalator"], "unit", 2800000),
    (["dock", "loading", "peb", "vdf"], "sqft", 650),
]

def feature_rate(name, category=""):
    haystack = f"{name} {category}".lower()
    for keywords, unit, rate in FEATURE_RATE_RULES:
        if any(keyword in haystack for keyword in keywords):
            return unit, rate
    return "sqft", 1500

def sqm_to_sqft(value):
    return safe_float(value, 0, 0) * 10.7639

def extract_labeled_area_sqft(text, labels):
    if not text:
        return 0
    label_pattern = "|".join(re.escape(label) for label in labels)
    patterns = [
        rf"(?:{label_pattern})\s*(?:area)?\s*[:=\-]?\s*(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|sqm|m2|m²)",
        rf"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|sqm|m2|m²)\s*(?:{label_pattern})",
        rf"(?:{label_pattern})\s*(?:area)?\s*[:=\-]?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|sft|ft2|ft²)",
        rf"(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|sft|ft2|ft²)\s*(?:{label_pattern})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        value = safe_float(raw, 0, 0)
        if not value:
            continue
        return round(sqm_to_sqft(value) if re.search(r"(sq\.?\s*m|sqm|m2|m²)", match.group(0), re.I) else value, 2)
    return 0

def enrich_visible_features_from_text(analysis, text):
    if not text:
        return analysis
    review = analysis.setdefault("drawing_review", {})
    assumptions = review.setdefault("assumptions", [])
    amenities = analysis.setdefault("luxury_amenities", {})
    existing_features = analysis.get("detected_features") if isinstance(analysis.get("detected_features"), list) else []
    features = [f for f in existing_features if isinstance(f, dict)]
    feature_names = {str(f.get("name") or "").strip().lower() for f in features}
    detected = []
    for key, patterns in VISIBLE_AMENITY_PATTERNS.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            if not amenities.get(key):
                amenities[key] = True
            detected.append(key.replace("_", " "))
    if detected:
        assumptions.append("Auto-selected visible amenities from drawing labels: " + ", ".join(sorted(set(detected))) + ".")

    detected_feature_names = []
    for feature_name, (category, patterns) in VISIBLE_FEATURE_PATTERNS.items():
        evidence = ""
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                start = max(0, match.start() - 45)
                end = min(len(text), match.end() + 75)
                evidence = re.sub(r"\s+", " ", text[start:end]).strip()
                break
        if not evidence or feature_name.lower() in feature_names:
            continue
        area = extract_labeled_area_sqft(text, [feature_name, feature_name.lower()])
        features.append({
            "name": feature_name,
            "category": category,
            "area_sqft": int(area) if area else 0,
            "quantity": 1,
            "unit": "space",
            "confidence": "medium",
            "source": f"visible_pdf_text: {evidence[:160]}",
            "included": True,
        })
        feature_names.add(feature_name.lower())
        detected_feature_names.append(feature_name)
    if detected_feature_names:
        assumptions.append("Detected labelled project features from PDF text: " + ", ".join(sorted(set(detected_feature_names))) + ".")
    analysis["detected_features"] = features[:80]

    plot_area = extract_labeled_area_sqft(text, ["plot", "plot area", "site", "site area", "land", "land area", "property area", "khasra area"])
    if plot_area:
        analysis["plot_area_sqft"] = int(plot_area)
        assumptions.append(f"Plot/site area was read from drawing text as approximately {int(plot_area)} sqft.")

    floor_wise = analysis.setdefault("floor_wise_areas", {})
    floor_labels = {
        "basement": ["basement", "basement floor", "lower ground"],
        "ground": ["ground floor", "g floor", "gf"],
        "first": ["first floor", "1st floor", "ff"],
        "second": ["second floor", "2nd floor"],
        "terrace": ["terrace", "roof", "roof plan"],
        "pool_landscape": ["pool deck", "landscape", "landscape area", "pool landscape"],
    }
    floor_hits = []
    for key, labels in floor_labels.items():
        if any(re.search(rf"\b{re.escape(label)}\b", text, re.I) for label in labels):
            floor_hits.append(key)
        area = extract_labeled_area_sqft(text, labels)
        if area:
            floor_wise[key] = int(area)
    if "basement" in floor_hits:
        analysis["basement_levels"] = max(safe_int(analysis.get("basement_levels"), 0, 0), 1)
    above_grade_hits = [k for k in floor_hits if k in ["ground", "first", "second"]]
    if above_grade_hits:
        analysis["total_floors"] = max(safe_int(analysis.get("total_floors"), 1, 1), len(set(above_grade_hits)))
        assumptions.append("Floor labels detected in drawing text: " + ", ".join(sorted(set(floor_hits))) + ".")
    return analysis

def enrich_analysis_scope(analysis, project_row=None):
    project_type = normalize_project_type((analysis or {}).get("project_type") or (project_row["project_type"] if project_row and "project_type" in project_row.keys() else "residential_tower"))
    analysis["project_type"] = project_type
    analysis["building_type"] = analysis.get("building_type") or property_profile(project_type)["label"]
    if project_row:
        if "address" in project_row.keys() and project_row["address"]:
            analysis["address"] = analysis.get("address") or project_row["address"]
        parcel = parse_json_field(project_row, "parcel_data", {})
        if parcel:
            analysis["parcel_data"] = parcel
            analysis["city"] = analysis.get("city") or parcel.get("city")
            if parcel.get("site_area_sqft") and not safe_float(analysis.get("plot_area_sqft"), 0, 0):
                analysis["plot_area_sqft"] = parcel.get("site_area_sqft")
    file_path = project_row["file_path"] if project_row and "file_path" in project_row.keys() else None
    file_mime = project_row["file_mime"] if project_row and "file_mime" in project_row.keys() else None
    file_name = project_row["file_name"] if project_row and "file_name" in project_row.keys() else ""
    text = extract_file_text(file_path, file_mime)
    analysis = enrich_visible_features_from_text(analysis, text)
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
        ("boq", "Mobilization, barricading and temporary site office", "sqft BUA", 36),
        ("boq", "Site supervision, safety and statutory coordination", "sqft BUA", 44),
        ("boq", "Survey, setting out and documentation", "sqft BUA", 20),
        ("boq", "Bulk excavation in ordinary soil", "cft", 52),
        ("boq", "Backfilling, compaction and disposal lead", "cft", 46),
        ("boq", "Anti-termite treatment below plinth", "sqft", 22),
        ("boq", "PCC 1:4:8 below foundations", "cum", 7600),
        ("boq", "Centering, shuttering and staging", "sqft", 135),
        ("boq", "Internal partition masonry", "sqft", 132),
        ("boq", "Lintel, sill and minor RCC bands", "sqft", 190),
        ("boq", "Aluminium/uPVC windows with glazing", "sqft", 650),
        ("boq", "Internal plaster and putty base", "sqft", 52),
        ("boq", "Internal painting, primer and finish coats", "sqft", 46),
        ("boq", "External plaster and waterproof putty", "sqft", 82),
        ("boq", "Weatherproof exterior paint", "sqft", 58),
    ]
    for category, name, unit, rate in estimate_seed:
        rows.append({"id": uid(), "category": category, "item": name, "unit": unit, "rate": rate, "source": "CPWD/DSR benchmark seed", "city": "Delhi NCR"})
    return rows


def seed_rate_items(db):
    row = db.execute("SELECT COUNT(*) AS c FROM rate_items").fetchone()
    try:
        has_rows = bool(row["c"])
    except (TypeError, KeyError, IndexError):
        has_rows = bool(row[0])
    for item in base_rate_rows():
        if USE_POSTGRES:
            db.execute(
                "INSERT INTO rate_items (id, category, item, unit, rate, source, city, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(item) DO NOTHING",
                (item["id"], item["category"], item["item"], item["unit"], item["rate"], item["source"], item["city"], now())
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO rate_items (id, category, item, unit, rate, source, city, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["category"], item["item"], item["unit"], item["rate"], item["source"], item["city"], now())
            )
        if has_rows:
            db.execute(
                """
                UPDATE rate_items
                SET category = ?, unit = ?, rate = ?, source = ?, city = ?, updated_at = ?
                WHERE item = ?
                  AND (LOWER(COALESCE(source, '')) LIKE '%seed%' OR LOWER(COALESCE(source, '')) LIKE '%benchmark%')
                """,
                (item["category"], item["unit"], item["rate"], item["source"], item["city"], now(), item["item"])
            )

def rate_items_by_category():
    rows = get_db().execute("SELECT id, category, item, unit, rate, source, city, updated_at FROM rate_items ORDER BY category, item").fetchall()
    grouped = {"materials": [], "labour": [], "boq": []}
    for row in rows:
        item = dict(row)
        item["rate"] = float(item["rate"])
        grouped.setdefault(item["category"], []).append(item)
    return grouped

def city_from_analysis(analysis):
    haystack = " ".join([
        str(analysis.get("city") or ""),
        str(analysis.get("address") or ""),
        str(analysis.get("location") or ""),
        json.dumps(analysis.get("parcel_data") or {}, default=str),
    ]).lower()
    if "mumbai" in haystack:
        return "Mumbai"
    if "bengaluru" in haystack or "bangalore" in haystack:
        return "Bengaluru"
    if "gurugram" in haystack or "gurgaon" in haystack:
        return "Gurugram"
    if "noida" in haystack:
        return "Noida"
    if "faridabad" in haystack:
        return "Faridabad"
    if "ghaziabad" in haystack:
        return "Ghaziabad"
    if "delhi" in haystack:
        return "Delhi"
    return "Delhi NCR"

def rate_lookup_map(city=None):
    try:
        db = get_db()
        city_norm = (city or "Delhi NCR").strip().lower()
        rates = {}
        rows = db.execute("SELECT item, rate, city FROM rate_items ORDER BY updated_at DESC").fetchall()
        for row in rows:
            row_city = (row["city"] or "Delhi NCR").strip().lower()
            if row_city == city_norm:
                rates[row["item"]] = float(row["rate"])
        for row in rows:
            rates.setdefault(row["item"], float(row["rate"]))
        for row in db.execute("SELECT material, rate, city FROM material_rates ORDER BY updated_at DESC").fetchall():
            row_city = (row["city"] or "Delhi NCR").strip().lower()
            if row_city == city_norm:
                rates[row["material"]] = float(row["rate"])
            else:
                rates.setdefault(row["material"], float(row["rate"]))
        for row in db.execute("SELECT description, rate, city FROM cpwd_items WHERE rate IS NOT NULL ORDER BY updated_at DESC").fetchall():
            row_city = (row["city"] or "Delhi NCR").strip().lower()
            if row_city == city_norm:
                rates[row["description"]] = float(row["rate"])
            else:
                rates.setdefault(row["description"], float(row["rate"]))
        return rates
    except Exception:
        rates = {}
        for item in base_rate_rows():
            rates[item["item"]] = float(item["rate"])
        return rates

def pricing_data_signal():
    signal = {"material_rate_count": 0, "cpwd_item_count": 0, "historical_boq_count": 0}
    try:
        db = get_db()
        signal["material_rate_count"] = int(db.execute("SELECT COUNT(*) AS c FROM material_rates").fetchone()["c"])
        signal["cpwd_item_count"] = int(db.execute("SELECT COUNT(*) AS c FROM cpwd_items").fetchone()["c"])
        signal["historical_boq_count"] = int(db.execute("SELECT COUNT(*) AS c FROM historical_boqs").fetchone()["c"])
    except Exception:
        pass
    return signal

def detect_location_factor(analysis):
    haystack = " ".join([
        str(analysis.get("address") or ""),
        str(analysis.get("location") or ""),
        str(analysis.get("city") or ""),
        str(analysis.get("notes") or ""),
        json.dumps(analysis.get("drawing_review") or {}, default=str),
    ]).lower()
    for keywords, factor, label in LOCATION_COST_FACTORS:
        if any(keyword in haystack for keyword in keywords):
            return factor, label
    return 1.0, "Delhi NCR seed market"

def detect_spec_level(analysis):
    explicit = str(analysis.get("spec_level") or "").strip().lower()
    haystack = " ".join([
        explicit,
        str(analysis.get("building_type") or ""),
        str(analysis.get("notes") or ""),
        json.dumps(analysis.get("drawing_review") or {}, default=str),
        json.dumps(analysis.get("detected_features") or [], default=str),
    ]).lower()
    amenities = analysis.get("luxury_amenities") if isinstance(analysis.get("luxury_amenities"), dict) else {}
    amenity_hits = sum(1 for value in amenities.values() if value)
    if explicit in ["luxury", "premium", "economy"]:
        level = explicit
    elif any(word in haystack for word in ["luxury", "premium villa", "high end", "high-end", "malibu", "golf"]):
        level = "luxury"
    elif amenity_hits >= 3 or any(word in haystack for word in ["premium", "marble", "home automation", "vrf", "clubhouse"]):
        level = "premium"
    elif any(word in haystack for word in ["economy", "budget", "basic"]):
        level = "economy"
    else:
        level = "standard"
    return level, SPEC_FACTORS["finish_level"].get(level, 1.0)

def historical_cost_factor(project_type, current_cost_per_sqft):
    if not current_cost_per_sqft:
        return 1.0, 0, 0
    values = []
    try:
        rows = get_db().execute("SELECT parsed_data FROM historical_boqs ORDER BY created_at DESC LIMIT 200").fetchall()
        for row in rows:
            try:
                data = json.loads(row["parsed_data"] or "{}")
            except Exception:
                continue
            if normalize_project_type(data.get("project_type")) != project_type:
                continue
            cpsf = safe_float(data.get("cost_per_sqft") or data.get("cost_psf") or data.get("rate_per_sqft"), 0, 0)
            if cpsf > 500:
                values.append(cpsf)
    except Exception:
        return 1.0, 0, 0
    if len(values) < 3:
        return 1.0, len(values), 0
    avg = sum(values) / len(values)
    factor = max(0.75, min(1.35, avg / current_cost_per_sqft))
    return factor, len(values), int(avg)

def apply_pricing_factor(divisions, factor, source_note, division_keys=None):
    if abs(factor - 1) < 0.005:
        return
    allowed = set(division_keys or [])
    for key, div in divisions.items():
        if key == "16_overheads" or (allowed and key not in allowed):
            continue
        for line in div.get("items", []):
            line["rate"] = round(float(line.get("rate", 0)) * factor, 2)
            line["amount"] = int(float(line.get("qty", 0)) * line["rate"])
            line["source"] = f"{line.get('source') or 'Seed rate'}; {source_note}"

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
        (file.filename, mime, len(data), db_blob(data), file_path, json.dumps(manifest), now(), project_id)
    )
    db.execute(
        """
        INSERT INTO drawing_files
        (id, project_id, user_id, file_name, file_mime, file_size, file_data, file_path, file_kind, parsed_text, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uid(), project_id, g.current_user["id"], file.filename, mime, len(data), db_blob(data), file_path, "drawing", extract_file_text(file_path, mime), now())
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

    if not row["file_data"] and not (("file_path" in row.keys()) and row["file_path"]):
        return jsonify({"success": False, "message": "Upload a drawing before generating an estimate."}), 400

    body = request.get_json(silent=True) or {}
    draft_mode = bool(body.get("draft"))
    parcel = parse_json_field(row, "parcel_data", {})
    raw_analysis = analyze_drawing_with_ai(row)
    if raw_analysis.get("ai_error"):
        return jsonify({
            "success": False,
            "message": raw_analysis.get("ai_error_message") or "AI analysis failed. Please try again.",
            "retryable": True,
        }), 502
    analysis = enrich_analysis_scope(raw_analysis, row)
    sheets = default_sheet_intelligence(analysis)
    regions = default_regions(analysis)
    takeoffs = calculate_takeoffs(analysis, regions, parcel)
    if draft_mode:
        return jsonify({
            "success": True,
            "needs_confirmation": True,
            "analysis": analysis,
            "drawing_sheets": sheets,
            "drawing_regions": regions,
            "takeoffs": takeoffs,
            "message": "AI extraction is ready. Confirm BUA and key fields before running the estimate.",
        })
    estimate = calculate_estimate(analysis, takeoffs)
    estimate = attach_ai_validation(analysis, estimate)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, drawing_sheets = ?, drawing_regions = ?, takeoffs = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), json.dumps(sheets), json.dumps(regions), json.dumps(takeoffs), now(), project_id)
    )
    save_detected_features(db, project_id, g.current_user["id"], analysis.get("detected_features"))
    record_usage(g.current_user["id"])
    db.commit()

    return jsonify({"success": True, "analysis": analysis, "estimate": estimate, "drawing_sheets": sheets, "drawing_regions": regions, "takeoffs": takeoffs})

@app.route("/api/projects/<project_id>/confirm-analysis", methods=["POST"])
@require_auth
def confirm_project_analysis(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    body = request.get_json() or {}
    incoming = body.get("analysis") if isinstance(body.get("analysis"), dict) else body
    incoming["project_type"] = incoming.get("project_type") or row["project_type"]
    analysis = enrich_analysis_scope(normalize_analysis(incoming, row["name"]), row)
    analysis["ai_source"] = incoming.get("ai_source") or analysis.get("ai_source") or "claude_confirmed"
    analysis["user_confirmed_at"] = now()
    parcel = parse_json_field(row, "parcel_data", {})
    sheets = body.get("drawing_sheets") if isinstance(body.get("drawing_sheets"), list) else default_sheet_intelligence(analysis)
    regions = body.get("drawing_regions") if isinstance(body.get("drawing_regions"), list) else default_regions(analysis)
    takeoffs = calculate_takeoffs(analysis, regions, parcel)
    estimate = calculate_estimate(analysis, takeoffs)
    estimate = attach_ai_validation(analysis, estimate)
    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, drawing_sheets = ?, drawing_regions = ?, takeoffs = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), json.dumps(sheets), json.dumps(regions), json.dumps(takeoffs), now(), project_id)
    )
    save_detected_features(db, project_id, g.current_user["id"], analysis.get("detected_features"))
    record_usage(g.current_user["id"])
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
    estimate = attach_ai_validation(analysis, estimate)

    db.execute(
        "UPDATE projects SET analysis = ?, estimate = ?, takeoffs = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(analysis), json.dumps(estimate), json.dumps(takeoffs), now(), project_id)
    )
    save_detected_features(db, project_id, g.current_user["id"], analysis.get("detected_features"))
    record_usage(g.current_user["id"])
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

@app.route("/api/projects/<project_id>/drawings", methods=["GET", "POST"])
@require_auth
def project_drawing_files(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if request.method == "GET":
        files = db.execute(
            "SELECT id, file_name, file_mime, file_size, file_kind, created_at FROM drawing_files WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        return jsonify({"success": True, "files": [dict(f) for f in files]})

    uploaded = request.files.getlist("files") or ([request.files.get("file")] if request.files.get("file") else [])
    saved = []
    for file in uploaded:
        data, mime, error = validate_upload(file)
        if error:
            continue
        file_id = uid()
        file_path = write_project_file(project_id, f"{file_id}_{file.filename}", data)
        parsed_text = extract_file_text(file_path, mime)
        db.execute(
            """
            INSERT INTO drawing_files
            (id, project_id, user_id, file_name, file_mime, file_size, file_data, file_path, file_kind, parsed_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, project_id, g.current_user["id"], file.filename, mime, len(data), db_blob(data), file_path, "drawing", parsed_text, now())
        )
        saved.append({"id": file_id, "file_name": file.filename, "file_mime": mime, "file_size": len(data)})
    db.commit()
    return jsonify({"success": True, "files": saved, "message": f"Uploaded {len(saved)} drawing file(s)."})

def parse_boq_csv_text(text):
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        normalized = {str(k or "").strip().lower(): v for k, v in raw.items()}
        desc = normalized.get("description") or normalized.get("item") or normalized.get("particulars") or normalized.get("name")
        if not desc:
            continue
        rate = safe_float(normalized.get("rate") or normalized.get("unit rate") or normalized.get("unit_rate"), 0, 0)
        qty = safe_float(normalized.get("qty") or normalized.get("quantity"), 0, 0)
        unit = normalized.get("unit") or normalized.get("uom") or "unit"
        amount = safe_float(normalized.get("amount") or normalized.get("total"), qty * rate, 0)
        rows.append({"description": desc, "qty": qty, "unit": unit, "rate": rate, "amount": amount})
    return rows

@app.route("/api/projects/<project_id>/historical-boq", methods=["POST"])
@require_auth
def upload_historical_boq(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "message": "Upload a CSV BOQ file."}), 400
    data = file.read()
    text = data.decode("utf-8", errors="ignore")
    parsed_rows = parse_boq_csv_text(text)
    analysis = parse_json_field(row, "analysis", {}) or {}
    estimate = parse_json_field(row, "estimate", {}) or {}
    parsed = {
        "project_type": normalize_project_type(analysis.get("project_type") or row["project_type"]),
        "city": city_from_analysis(analysis),
        "rows": parsed_rows[:1000],
        "cost_per_sqft": estimate.get("cost_per_sqft") or 0,
    }
    boq_id = uid()
    db.execute(
        "INSERT INTO historical_boqs (id, project_id, user_id, file_name, file_mime, file_size, file_data, parsed_data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (boq_id, project_id, g.current_user["id"], file.filename, file.mimetype or "text/csv", len(data), db_blob(data), json.dumps(parsed), now())
    )
    for item_row in parsed_rows:
        if item_row["rate"] <= 0:
            continue
        material = str(item_row["description"])[:120]
        db.execute(
            "INSERT INTO material_rates (id, material, unit, rate, city, supplier, source, effective_date, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uid(), material, item_row["unit"], item_row["rate"], parsed["city"], "Historical BOQ", f"Uploaded BOQ: {file.filename}", now()[:10], now())
        )
    db.commit()
    return jsonify({"success": True, "boq_id": boq_id, "matched_rows": len(parsed_rows), "message": "Historical BOQ stored for future calibration."})

@app.route("/api/projects/<project_id>/feedback", methods=["POST"])
@require_auth
def project_feedback(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    body = request.get_json() or {}
    rating = (body.get("rating") or "").strip().lower()
    if rating not in ["up", "down", "neutral"]:
        return jsonify({"success": False, "message": "Rating must be up, down or neutral."}), 400
    db.execute(
        "INSERT INTO estimate_feedback (id, project_id, user_id, rating, comment, actual_cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid(), project_id, g.current_user["id"], rating, (body.get("comment") or "")[:1000], safe_float(body.get("actual_cost"), 0, 0), now())
    )
    db.commit()
    return jsonify({"success": True, "message": "Feedback saved. This helps calibrate future estimates."})

@app.route("/api/projects/<project_id>/rate-corrections", methods=["POST"])
@require_auth
def project_rate_correction(project_id):
    db = get_db()
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    body = request.get_json() or {}
    analysis = parse_json_field(row, "analysis", {}) or {}
    db.execute(
        """
        INSERT INTO rate_corrections
        (id, project_id, user_id, division, item, old_rate, corrected_rate, city, property_type, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uid(), project_id, g.current_user["id"], body.get("division"), body.get("item"),
            safe_float(body.get("old_rate"), 0, 0), safe_float(body.get("corrected_rate"), 0, 0),
            city_from_analysis(analysis), normalize_project_type(analysis.get("project_type") or row["project_type"]),
            (body.get("comment") or "")[:1000], now()
        )
    )
    db.commit()
    return jsonify({"success": True, "message": "Rate correction saved."})

@app.route("/api/contractor-quotes", methods=["GET", "POST"])
def contractor_quotes():
    db = get_db()
    if request.method == "GET":
        city = (request.args.get("city") or "").strip()
        params = ()
        sql = "SELECT material, unit, city, COUNT(*) AS quote_count, MIN(rate) AS min_rate, AVG(rate) AS avg_rate, MAX(rate) AS max_rate FROM contractor_quotes"
        if city:
            sql += " WHERE LOWER(city) = LOWER(?)"
            params = (city,)
        sql += " GROUP BY material, unit, city ORDER BY material"
        rows = db.execute(sql, params).fetchall()
        return jsonify({"success": True, "quotes": [dict(r) for r in rows]})
    body = request.get_json() or {}
    material = (body.get("material") or "").strip()
    rate = safe_float(body.get("rate"), 0, 0)
    unit = (body.get("unit") or "unit").strip()
    if not material or rate <= 0:
        return jsonify({"success": False, "message": "Material and rate are required."}), 400
    db.execute(
        "INSERT INTO contractor_quotes (id, material, unit, rate, city, contractor_name, source, quote_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uid(), material, unit, rate, (body.get("city") or "Delhi NCR").strip(), (body.get("contractor_name") or "")[:120], (body.get("source") or "Contractor quote")[:120], body.get("quote_date") or now()[:10], now())
    )
    db.commit()
    return jsonify({"success": True, "message": "Contractor quote saved."}), 201

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
        "spec_level": "standard",
        "basement_levels": 0 if project_type in ["villa", "banquet_hall", "industrial_warehouse"] else 1,
        "parking_spaces": max(total_units, 4 if project_type == "villa" else 10),
        "lift_count": profile["default_lift_count"],
        "discipline_takeoff": {"equipment": [], "total_tr": 0, "total_cfm": 0},
        "hvac_units": [],
        "floor_wise_areas": {"basement": 0, "ground": bua if project_type == "villa" else 0, "first": 0, "second": 0, "terrace": 0, "pool_landscape": 0},
        "luxury_amenities": {"swimming_pool": False, "sauna": False, "modular_kitchen": project_type == "villa", "home_automation": False, "pergola": False, "fire_pit": False, "bar": False, "gym": False, "home_theater": False},
        "detected_features": [],
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
    plot_area_raw = safe_float(data.get("plot_area_sqft"), 0, 0)
    raw_bua = data.get("total_built_up_area_sqft")
    bua_default = profile["default_bua"]
    if project_type == "villa" and not safe_float(raw_bua, 0, 0) and plot_area_raw:
        bua_default = int(max(3500, min(plot_area_raw * 0.85, 22000)))
    bua = positive_int(raw_bua, bua_default)
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
    detected_raw = data.get("detected_features") if isinstance(data.get("detected_features"), list) else []
    detected_features = []
    for feature in detected_raw[:80]:
        if not isinstance(feature, dict):
            continue
        name = str(feature.get("name") or "").strip()
        source = str(feature.get("source") or feature.get("evidence") or "").strip()
        confidence = str(feature.get("confidence") or "medium").lower()
        if not name or (not source and confidence != "high" and not safe_float(feature.get("area_sqft"), 0, 0)):
            continue
        detected_features.append({
            "name": name[:80],
            "category": str(feature.get("category") or "detected_space").strip()[:60],
            "area_sqft": safe_float(feature.get("area_sqft"), 0, 0),
            "quantity": safe_float(feature.get("quantity"), 1, 0),
            "unit": str(feature.get("unit") or "space").strip()[:30],
            "confidence": confidence if confidence in ["high", "medium", "low"] else "medium",
            "source": source[:240],
            "included": bool(feature.get("included", True)),
        })
    hvac_units = data.get("hvac_units") if isinstance(data.get("hvac_units"), list) else []
    field_confidence_raw = data.get("field_confidence") if isinstance(data.get("field_confidence"), dict) else {}
    field_evidence_raw = data.get("field_evidence") if isinstance(data.get("field_evidence"), dict) else {}
    tracked_fields = ["total_built_up_area_sqft", "plot_area_sqft", "total_floors", "floor_wise_areas", "detected_features", "discipline_takeoff"]
    field_confidence = {}
    field_evidence = {}
    for key in tracked_fields:
        conf = str(field_confidence_raw.get(key) or "medium").lower()
        field_confidence[key] = conf if conf in ["high", "medium", "low"] else "medium"
        field_evidence[key] = str(field_evidence_raw.get(key) or "").strip()[:300]
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
        "spec_level": str(data.get("spec_level") or "").lower() if str(data.get("spec_level") or "").lower() in SPEC_FACTORS["finish_level"] else "",
        "basement_levels": positive_int(data.get("basement_levels"), 0),
        "parking_spaces": positive_int(data.get("parking_spaces"), total_units),
        "lift_count": positive_int(data.get("lift_count"), profile["default_lift_count"]),
        "discipline_takeoff": data.get("discipline_takeoff") if isinstance(data.get("discipline_takeoff"), dict) else {"equipment": [], "total_tr": 0, "total_cfm": 0},
        "hvac_units": hvac_units,
        "floor_wise_areas": floor_wise_areas,
        "luxury_amenities": luxury_amenities,
        "detected_features": detected_features,
        "field_confidence": field_confidence,
        "field_evidence": field_evidence,
        "confidence": str(data.get("confidence") or "medium").lower(),
        "ai_source": data.get("ai_source") or "claude",
        "ai_model": data.get("ai_model") or "",
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
        analysis = fallback_analysis(project["name"], "Drawing file was not available to the AI analyzer.", project["project_type"] if "project_type" in project.keys() else "residential_tower")
        analysis["ai_error"] = True
        analysis["ai_error_message"] = "Drawing file was not available to the AI analyzer."
        return analysis

    mime = project["file_mime"] or "application/pdf"
    b64 = base64.b64encode(file_data).decode("utf-8")
    provider = AI_PROVIDER or "anthropic"
    if provider == "anthropic":
        return analyze_with_anthropic(project, mime, b64)
    analysis = fallback_analysis(project["name"], "Claude extraction is required for production. Set ANTHROPIC_API_KEY in Render and keep AI_PROVIDER=anthropic.", project["project_type"] if "project_type" in project.keys() else "residential_tower")
    analysis["ai_error"] = True
    analysis["ai_error_message"] = "Claude extraction is required for production. Set ANTHROPIC_API_KEY in Render and keep AI_PROVIDER=anthropic."
    return analysis

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
    return unique or ["gemini-2.5-pro"]

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
        analysis = fallback_analysis(project["name"], "ANTHROPIC_API_KEY is not configured.", project["project_type"] if "project_type" in project.keys() else "residential_tower")
        analysis["ai_error"] = True
        analysis["ai_error_message"] = "ANTHROPIC_API_KEY is not configured in Render."
        return analysis

    if mime == "application/pdf":
        drawing_block = {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    else:
        drawing_block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 5000,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                drawing_block,
                {"type": "text", "text": f"Selected property type from user: {project['project_type'] if 'project_type' in project.keys() else 'residential_tower'}.\n\n{NIRMAN_EXTRACTION_PROMPT}"},
            ],
        }],
    }
    errors = []
    for attempt in range(3):
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
            data["ai_model"] = ANTHROPIC_MODEL
            data["project_type"] = data.get("project_type") or (project["project_type"] if "project_type" in project.keys() else "residential_tower")
            return normalize_analysis(data, project["name"])
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, KeyError, TimeoutError) as exc:
            errors.append(str(exc))
            if attempt < 2:
                time.sleep(2)
    analysis = fallback_analysis(project["name"], f"Claude analysis failed after 3 attempts: {'; '.join(errors[-2:])}", project["project_type"] if "project_type" in project.keys() else "residential_tower")
    analysis["ai_error"] = True
    analysis["ai_error_message"] = "Claude analysis failed after 3 attempts. Please try again."
    analysis["ai_error_detail"] = "; ".join(errors[-3:])
    return analysis

def validate_with_anthropic(analysis, estimate):
    if not ENABLE_AI_VALIDATION:
        return {"status": "disabled", "summary": "AI validation pass is disabled."}
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {"status": "skipped", "summary": "ANTHROPIC_API_KEY is not configured."}
    slim_estimate = {
        "built_up_area": estimate.get("built_up_area"),
        "cost_per_sqft": estimate.get("cost_per_sqft"),
        "subtotal": estimate.get("subtotal"),
        "gst": estimate.get("gst_breakup"),
        "total_with_gst": estimate.get("total_with_gst"),
        "divisions": {
            key: {
                "name": div.get("name"),
                "amount": div.get("amount"),
                "items": (div.get("items") or [])[:8],
            }
            for key, div in (estimate.get("divisions") or {}).items()
        },
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1600,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [{
                "type": "text",
                "text": NIRMAN_VALIDATION_PROMPT + "\n\nEXTRACTION JSON:\n" + json.dumps(analysis, default=str)[:18000] + "\n\nENGINE ESTIMATE JSON:\n" + json.dumps(slim_estimate, default=str)[:18000],
            }],
        }],
    }
    errors = []
    for attempt in range(2):
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
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            text = "".join(block.get("text", "") for block in raw.get("content", []) if block.get("type") == "text")
            data = parse_ai_json(text)
            data["model"] = ANTHROPIC_MODEL
            return data
        except Exception as exc:
            errors.append(str(exc))
            if attempt == 0:
                time.sleep(1)
    return {"status": "validation_failed", "summary": "Pass 2 validation could not complete.", "errors": errors}

def attach_ai_validation(analysis, estimate):
    validation = validate_with_anthropic(analysis, estimate)
    estimate["ai_validation"] = validation
    if validation.get("status") == "needs_review":
        accuracy = estimate.get("accuracy") or {}
        flags = validation.get("flags") if isinstance(validation.get("flags"), list) else []
        if flags:
            accuracy.setdefault("drivers", []).append({
                "label": "AI validation pass",
                "status": "needs review",
                "impact": "high" if any(f.get("severity") == "high" for f in flags if isinstance(f, dict)) else "medium",
                "detail": validation.get("summary") or "Claude validation found estimate review items.",
            })
            accuracy.setdefault("improvement_actions", []).extend([
                f.get("recommendation") for f in flags if isinstance(f, dict) and f.get("recommendation")
            ][:3])
            estimate["accuracy"] = accuracy
    return estimate

def estimate_accuracy_profile(analysis, takeoffs=None, estimate=None, project_type=None):
    project_type = normalize_project_type(project_type or analysis.get("project_type"))
    takeoffs = takeoffs or {}
    estimate = estimate or {}
    confidence = str(analysis.get("confidence") or "medium").lower()
    score = {"high": 78, "medium": 62, "low": 45}.get(confidence, 58)
    drivers = []
    missing = []
    actions = []

    def add_driver(label, status, impact, detail, delta=0, missing_input=None, action=None):
        nonlocal score
        score += delta
        drivers.append({
            "label": label,
            "status": status,
            "impact": impact,
            "detail": detail,
        })
        if missing_input and missing_input not in missing:
            missing.append(missing_input)
        if action and action not in actions:
            actions.append(action)

    bua = safe_float(analysis.get("total_built_up_area_sqft"), 0, 0)
    plot_area = safe_float(analysis.get("plot_area_sqft"), 0, 0)
    parcel_area = safe_float((analysis.get("parcel_data") or {}).get("site_area_sqft") if isinstance(analysis.get("parcel_data"), dict) else 0, 0, 0)
    floor_wise = analysis.get("floor_wise_areas") if isinstance(analysis.get("floor_wise_areas"), dict) else {}
    floor_wise_total = sum(safe_float(v, 0, 0) for v in floor_wise.values())
    review = analysis.get("drawing_review") if isinstance(analysis.get("drawing_review"), dict) else {}
    field_confidence = analysis.get("field_confidence") if isinstance(analysis.get("field_confidence"), dict) else {}
    field_evidence = analysis.get("field_evidence") if isinstance(analysis.get("field_evidence"), dict) else {}
    missing_info = review.get("missing_information") if isinstance(review.get("missing_information"), list) else []
    regions = analysis.get("drawing_regions") if isinstance(analysis.get("drawing_regions"), list) else []
    sheets = analysis.get("drawing_sheets") if isinstance(analysis.get("drawing_sheets"), list) else []
    quantities = takeoffs.get("quantities") if isinstance(takeoffs.get("quantities"), dict) else {}
    features = [f for f in analysis.get("detected_features", []) if isinstance(f, dict) and f.get("included", True)] if isinstance(analysis.get("detected_features"), list) else []
    sourced_features = [f for f in features if f.get("source") or f.get("evidence") or f.get("page")]
    pricing_context = estimate.get("pricing_context") if isinstance(estimate.get("pricing_context"), dict) else {}
    data_signal = pricing_context.get("data_signal") if isinstance(pricing_context.get("data_signal"), dict) else {}
    verified_rate_count = safe_int(data_signal.get("material_rate_count"), 0, 0) + safe_int(data_signal.get("cpwd_item_count"), 0, 0)
    historical_match_count = safe_int(pricing_context.get("historical_match_count"), 0, 0)

    if bua:
        add_driver("Built-up area", "good", "high", f"Estimate is based on {int(bua):,} sqft BUA.", 6)
    else:
        add_driver("Built-up area", "missing", "high", "BUA is missing, so the estimate falls back to a default area.", -16, "Total built-up area", "Enter total BUA or floor-wise areas before trusting the estimate.")

    if project_type == "villa":
        if floor_wise_total:
            add_driver("Villa floor-wise area", "good", "high", "Basement, floor and terrace areas are separated for villa costing.", 8)
        else:
            add_driver("Villa floor-wise area", "missing", "high", "Villa estimate is using a single BUA instead of basement/ground/first/terrace breakup.", -12, "Villa floor-wise area breakup", "Add basement, ground, upper floor, terrace and pool/landscape areas.")

    if plot_area or parcel_area:
        add_driver("Plot / parcel area", "good", "medium", "Site area is available for FAR, external development and report checks.", 4)
    else:
        add_driver("Plot / parcel area", "warning", "medium", "No plot or parcel area was entered; external works and FAR checks remain approximate.", -5, "Plot or parcel area", "Fill land details or parcel area from the plot document.")

    low_fields = [key for key, value in field_confidence.items() if str(value).lower() == "low"]
    evidence_count = sum(1 for value in field_evidence.values() if str(value).strip())
    if low_fields:
        add_driver("Field-level confidence", "warning", "high", "Low-confidence fields: " + ", ".join(low_fields[:4]) + ".", -min(12, len(low_fields) * 3), "Low-confidence extracted fields", "Review every low-confidence field in AI Approval before generating the final BOQ.")
    elif evidence_count:
        add_driver("Extraction evidence", "good", "medium", f"{evidence_count} key field(s) include source evidence from the drawing.", 4)

    if sheets:
        add_driver("Drawing sheets", "good", "medium", f"{len(sheets)} sheet(s) are classified for page-level review.", 5)
    else:
        add_driver("Drawing sheets", "warning", "medium", "No sheet classification exists yet.", -8, "Drawing sheet classification", "Review page types and scales in the Drawing Pages step.")

    verified_regions = [r for r in regions if safe_float(r.get("quantity_sqft"), 0, 0) or safe_float(r.get("length_ft"), 0, 0)]
    takeoff_values = [safe_float(quantities.get(k), 0, 0) for k in ("wall_area_sqft", "slab_area_sqft", "facade_area_sqft", "window_glazing_area_sqft", "flooring_area_sqft")]
    if verified_regions or any(takeoff_values):
        add_driver("Takeoff quantities", "good", "high", "Quantity data exists for walls/slabs/facade/glazing/finishes.", 9)
    else:
        add_driver("Takeoff quantities", "warning", "high", "Most quantities are still allowance-based, not measured from verified regions.", -14, "Verified takeoff quantities", "Measure or edit takeoff quantities before issuing a BOQ.")

    if features and sourced_features:
        add_driver("Detected spaces and amenities", "good", "medium", f"{len(sourced_features)} special feature(s) have source evidence.", 5)
    elif features:
        add_driver("Detected spaces and amenities", "warning", "medium", "Some special spaces exist but need source/evidence confirmation.", -3, "Feature evidence", "Keep only features visibly present in the drawing and remove uncertain ones.")
    else:
        add_driver("Detected spaces and amenities", "warning", "medium", "No special spaces or amenities were detected.", -4, "Amenity / special space schedule", "Add visible amenities such as labs, kitchen, pool, banquet, gym, plant rooms or other project-specific spaces.")

    if missing_info:
        deduction = min(16, len(missing_info) * 4)
        add_driver("Missing drawing information", "warning", "high", f"{len(missing_info)} missing item(s) were flagged by AI review.", -deduction, "Missing drawing information", "Upload structural, MEP, finish schedule and elevation sheets where available.")
    else:
        add_driver("Missing drawing information", "good", "medium", "AI review did not flag major missing items.", 3)

    if analysis.get("estimate_scope") == "discipline_only":
        add_driver("Estimate scope", "warning", "high", "This is a package estimate only, not a full building BOQ.", -16, "Full architectural/structural set", "Upload full project drawings when you need total construction cost.")

    rates_source = str(estimate.get("rates_source") or "").lower()
    if verified_rate_count or historical_match_count >= 3:
        add_driver("Pricing calibration", "good", "high", f"Using {verified_rate_count} verified rate row(s) and {historical_match_count} historical BOQ match(es).", 10)
    elif "seed" in rates_source or "allowance" in rates_source or not rates_source:
        add_driver("Rate source", "warning", "high", "Rates are still seed/benchmark rates, not verified supplier quotes.", -10, "Verified material and labour rates", "Upload supplier quotes, DSR/CPWD schedule items or your historical BOQ rates.")
    else:
        add_driver("Rate source", "good", "high", "Estimate is using a named rate source.", 6)

    if pricing_context:
        location_label = pricing_context.get("location_label") or "Delhi NCR seed market"
        spec_level = pricing_context.get("spec_level") or "standard"
        add_driver("Market and spec calibration", "good", "medium", f"Applied {location_label} and {spec_level} specification factors.", 4)
        if historical_match_count and historical_match_count < 3:
            add_driver("Historical BOQ calibration", "warning", "medium", f"Only {historical_match_count} matching historical BOQ record(s) found; need at least 3 for calibration.", -2, "More historical BOQs", "Upload at least 3 completed BOQs for each project type to calibrate cost-per-sqft.")

    if analysis.get("ai_source") == "claude":
        add_driver("AI model", "good", "medium", f"Drawing extraction used Claude ({analysis.get('ai_model') or 'configured model'}).", 3)
    elif analysis.get("ai_source"):
        add_driver("AI model", "warning", "medium", f"Drawing extraction used {analysis.get('ai_source')}; review critical values manually.", -2)
    else:
        add_driver("AI model", "warning", "medium", "Estimate may be generated from fallback/demo extraction.", -8, "Live AI extraction", "Configure the production AI key and rerun analysis.")

    if not verified_rate_count and historical_match_count < 3:
        score = min(score, 86)
    if missing_info and not verified_rate_count:
        score = min(score, 78)
    if analysis.get("estimate_scope") == "discipline_only":
        score = min(score, 76)
    score = max(25, min(96, int(round(score))))
    if score >= 88 and verified_rate_count and historical_match_count >= 3:
        grade = "very_high"
        range_percent = 8
    elif score >= 78:
        grade = "high"
        range_percent = 12
    elif score >= 60:
        grade = "medium"
        range_percent = 22
    else:
        grade = "low"
        range_percent = 35
    if analysis.get("estimate_scope") == "discipline_only":
        range_percent = max(range_percent, 25)
    total = safe_float(estimate.get("total_with_gst"), 0, 0)
    range_low = int(total * (1 - range_percent / 100)) if total else 0
    range_high = int(total * (1 + range_percent / 100)) if total else 0
    return {
        "score": score,
        "grade": grade,
        "range_percent": range_percent,
        "range_low": range_low,
        "range_high": range_high,
        "drivers": drivers,
        "missing_inputs": missing,
        "improvement_actions": actions[:8],
        "rate_confidence": "verified_or_calibrated_rates" if verified_rate_count or historical_match_count >= 3 else "seed_rates" if "seed" in rates_source or "allowance" in rates_source or not rates_source else "verified_or_user_rates",
        "basis": {
            "confidence": confidence,
            "project_type": project_type,
            "built_up_area_sqft": bua,
            "plot_area_sqft": plot_area or parcel_area,
            "sheet_count": len(sheets),
            "region_count": len(regions),
            "detected_feature_count": len(features),
            "verified_rate_count": verified_rate_count,
            "historical_match_count": historical_match_count,
        },
    }

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
        outdoor_sets = safe_int(hvac.get("outdoor_unit_sets"), 0, 0)
        if not outdoor_sets:
            outdoor_sets = sum(safe_int(e.get("qty"), 1, 1) for e in equipment if "outdoor" in str(e.get("type", "")).lower() or "odu" in str(e.get("notes", "")).lower())
        outdoor_sets = max(outdoor_sets, math.ceil(total_tr / 15))
        premium_hvac = normalize_project_type(analysis.get("project_type")) == "villa" or "villa" in str(analysis.get("building_type", "")).lower() or any(word in str(analysis.get("notes", "")).lower() for word in ["luxury", "premium", "malibu", "gurugram", "golf"])
        indoor_rate = 120000 if premium_hvac else 85000
        outdoor_rate = 780000 if premium_hvac else 650000
        divisions = {
            "13_hvac": {
                "name": "HVAC Works",
                "items": [
                    line("VRF/ductable indoor units supply and installation", indoor_qty, "each", indoor_rate),
                    line("Outdoor units / condenser allowance", max(1, outdoor_sets), "set", outdoor_rate),
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
    result = {
        "currency": "INR",
        "built_up_area": analysis.get("total_built_up_area_sqft", 0),
        "cost_per_sqft": None,
        "cost_per_sqft_note": "Not applicable for discipline-only package estimates.",
        "subtotal": subtotal,
        "gst_12pct": gst,
        "gst_label": "Applicable GST",
        "gst_breakup": {"taxable_value": subtotal, "cgst_6pct": 0, "sgst_6pct": 0, "igst_18pct": gst, "igst_12pct": 0, "total_gst": gst},
        "total_with_gst": subtotal + gst,
        "divisions": divisions,
        "rates_source": "Discipline-specific Delhi NCR seed rates",
        "disclaimer": f"Discipline-only {DRAWING_DISCIPLINES.get(discipline, discipline)} estimate. This is not a full building BOQ.",
    }
    result["accuracy"] = estimate_accuracy_profile(analysis, takeoffs, result, analysis.get("project_type"))
    return result

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
    rate_city = city_from_analysis(analysis)
    rates = rate_lookup_map(rate_city)
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
    location_factor, location_label = detect_location_factor(analysis)
    spec_level, spec_factor = detect_spec_level(analysis)
    pricing_context = {
        "location_factor": round(location_factor, 3),
        "location_label": location_label,
        "spec_level": spec_level,
        "spec_factor": round(spec_factor, 3),
        "data_signal": pricing_data_signal(),
        "historical_factor": 1.0,
        "historical_match_count": 0,
        "historical_avg_cost_per_sqft": 0,
    }

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
        "19_detected_features": {
            "name": "AI Detected Special Spaces",
            "items": [],
        },
        "20_statutory": {
            "name": "Statutory, RERA and Approval Costs",
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

    detected_items = []
    seen_feature_names = set()
    for feature in analysis.get("detected_features") if isinstance(analysis.get("detected_features"), list) else []:
        if not isinstance(feature, dict) or not feature.get("included", True):
            continue
        name = str(feature.get("name") or "").strip()
        if not name or name.lower() in seen_feature_names:
            continue
        source = str(feature.get("source") or "").strip()
        confidence = str(feature.get("confidence") or "medium").lower()
        area = safe_float(feature.get("area_sqft"), 0, 0)
        qty = safe_float(feature.get("quantity"), 1, 0)
        if confidence == "low" and not source and not area:
            continue
        unit, rate = feature_rate(name, feature.get("category") or "")
        if unit == "sqft":
            quantity = area or max(250, physical_bua * 0.006)
        elif unit == "unit":
            quantity = max(qty, 1)
        else:
            quantity = max(qty, 1)
        detected_items.append(item(f"Detected feature: {name}", quantity, unit, rate, 18))
        detected_items[-1]["source"] = source or "AI detected feature"
        seen_feature_names.add(name.lower())
    divisions["19_detected_features"]["items"] = detected_items
    if not divisions["19_detected_features"]["items"]:
        divisions.pop("19_detected_features", None)

    apply_pricing_factor(divisions, location_factor, location_label)
    spec_divisions = ["06_doors_windows", "07_finishes", "08_facade", "10_plumbing", "11_electrical", "13_hvac", "17_luxury_amenities", "18_property_specific", "19_detected_features"]
    spec_adjustment = max(0.92, min(1.18, spec_factor))
    apply_pricing_factor(divisions, spec_adjustment, f"{spec_level} specification calibration", spec_divisions)

    pre_total = sum(sum(i["amount"] for i in div["items"]) for key, div in divisions.items() if key != "16_overheads")
    pre_cost_per_sqft = int(pre_total / max(physical_bua, 1))
    historical_factor, historical_count, historical_avg = historical_cost_factor(project_type, pre_cost_per_sqft)
    pricing_context["historical_factor"] = round(historical_factor, 3)
    pricing_context["historical_match_count"] = historical_count
    pricing_context["historical_avg_cost_per_sqft"] = historical_avg
    if historical_count >= 3:
        apply_pricing_factor(divisions, historical_factor, f"historical BOQ calibration from {historical_count} matching records")

    direct_total = sum(sum(i["amount"] for i in div["items"]) for key, div in divisions.items() if key not in ["16_overheads", "20_statutory"])
    parcel = analysis.get("parcel_data") if isinstance(analysis.get("parcel_data"), dict) else {}
    authority_text = " ".join([str(parcel.get("authority") or ""), str(parcel.get("rera_number") or ""), str(analysis.get("address") or "")]).lower()
    statutory_rate = 0.006
    if any(word in authority_text for word in ["dtcp", "hrera", "gurugram", "gurgaon"]):
        statutory_rate = 0.010
    elif any(word in authority_text for word in ["dda", "delhi"]):
        statutory_rate = 0.008
    elif any(word in authority_text for word in ["up-rera", "up rera", "noida", "greater noida"]):
        statutory_rate = 0.009
    statutory_items = [
        item("RERA registration, statutory filings and professional liaison", 1, "allowance", max(150000, direct_total * statutory_rate), 18),
        item("Authority approvals, fire NOC and occupancy documentation", 1, "allowance", max(250000, direct_total * 0.0045), 18),
    ]
    if parcel.get("permissible_far") or parcel.get("land_use") or parcel.get("authority"):
        statutory_items.append(item("EDC/IDC/FAR premium placeholder pending authority schedule", 1, "allowance", max(300000, direct_total * 0.012), 18))
    divisions["20_statutory"]["items"] = statutory_items
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

    data_signal = pricing_context.get("data_signal") or {}
    verified_rate_count = safe_int(data_signal.get("material_rate_count"), 0, 0) + safe_int(data_signal.get("cpwd_item_count"), 0, 0)
    rate_source_parts = ["DSR/CPWD benchmark seed rates", rate_city, location_label, f"{spec_level} specification"]
    if verified_rate_count:
        rate_source_parts.append(f"{verified_rate_count} verified rate rows")
    if historical_count >= 3:
        rate_source_parts.append(f"{historical_count} historical BOQ calibration records")

    result = {
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
        "pricing_context": pricing_context,
        "rates_source": " + ".join(rate_source_parts),
        "disclaimer": "Indicative GST-compliant concept estimate. Replace seed rates with verified supplier and labour quotes before tender, bank submission or RERA filing."
    }
    result["accuracy"] = estimate_accuracy_profile(analysis, takeoffs, result, project_type)
    return result

SCENARIO_DEFAULTS = {
    "name": "Scenario",
    "concrete_grade": "M25",
    "cement_type": "OPC 43",
    "steel_rate": 90,
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
    normalized["steel_rate"] = safe_float(normalized.get("steel_rate"), 90, 45, 160)
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
    if estimate.get("cost_per_sqft_note"):
        estimate["cost_per_sqft"] = None
    else:
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

    analysis = json.loads(row["analysis"])
    takeoffs = json.loads(row["takeoffs"]) if row["takeoffs"] else None
    current = json.loads(row["estimate"]) if row["estimate"] else calculate_estimate(analysis, takeoffs)
    current["divisions"] = estimate["divisions"]
    current["built_up_area"] = safe_int(estimate.get("built_up_area"), current.get("built_up_area", 1), 1)
    current = recalc_estimate_totals(current)
    current["rates_source"] = estimate.get("rates_source") or "User-edited BOQ and seed rate library"
    current["disclaimer"] = estimate.get("disclaimer") or current.get("disclaimer", "")
    current["accuracy"] = estimate_accuracy_profile(analysis, takeoffs, current, analysis.get("project_type"))

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
    accuracy = estimate.get("accuracy") or estimate_accuracy_profile(analysis, takeoffs, estimate, analysis.get("project_type"))
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
        "accuracy_score": accuracy.get("score", 0),
        "accuracy_grade": accuracy.get("grade", "medium"),
        "accuracy_range_low": accuracy.get("range_low", 0),
        "accuracy_range_high": accuracy.get("range_high", 0),
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
            "accuracy": accuracy,
            "pricing_context": estimate.get("pricing_context") or {},
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

def render_report_html(report):
    project = report.get("project") or {}
    metrics = report.get("metrics") or {}
    sections = report.get("sections") or {}
    cost = (sections.get("cost") or {})
    divisions = cost.get("divisions") or {}
    rows = []
    for div in divisions.values():
        for line in div.get("items", []):
            rows.append(
                "<tr>"
                f"<td>{html.escape(div.get('name') or '')}</td>"
                f"<td>{html.escape(line.get('code') or '')}</td>"
                f"<td>{html.escape(line.get('desc') or '')}</td>"
                f"<td>{line.get('qty','')}</td>"
                f"<td>{html.escape(str(line.get('unit') or ''))}</td>"
                f"<td>Rs {int(safe_float(line.get('rate'),0,0)):,}</td>"
                f"<td>Rs {int(safe_float(line.get('amount'),0,0)):,}</td>"
                "</tr>"
            )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Nirman.AI Report</title>
<style>
body{{font-family:Arial,sans-serif;color:#111;margin:36px;line-height:1.45}}
h1{{font-size:28px;margin:0 0 6px}} h2{{margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:8px}}
.brand{{font-weight:700;color:#1d6f86;letter-spacing:.08em}} .muted{{color:#666}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}}
.metric{{border:1px solid #ddd;padding:14px}} .metric b{{display:block;font-size:18px;margin-top:5px}}
table{{width:100%;border-collapse:collapse;font-size:11px}} th,td{{border:1px solid #ddd;padding:7px;text-align:left;vertical-align:top}} th{{background:#f2f6f8}}
@page{{size:A4;margin:18mm}}
</style></head><body>
<div class="brand">Nirman.AI Construction Intelligence</div>
<h1>{html.escape(project.get('name') or 'Project Report')}</h1>
<div class="muted">{html.escape(project.get('address') or '')} | Generated {html.escape(report.get('generated_at') or '')}</div>
<div class="metrics">
<div class="metric">Estimate Range<b>Rs {int(metrics.get('accuracy_range_low') or 0):,} - Rs {int(metrics.get('accuracy_range_high') or 0):,}</b></div>
<div class="metric">Total With GST<b>Rs {int(metrics.get('total_cost_with_gst') or 0):,}</b></div>
<div class="metric">Built-up Area<b>{int(metrics.get('gross_construction_area_sqft') or 0):,} sqft</b></div>
<div class="metric">Accuracy<b>{metrics.get('accuracy_score') or 0}/100 {html.escape(str(metrics.get('accuracy_grade') or ''))}</b></div>
<div class="metric">Cost / sqft<b>{metrics.get('cost_per_sqft') or 'NA'}</b></div>
<div class="metric">GST<b>Rs {int(metrics.get('gst_total') or 0):,}</b></div>
</div>
<h2>Project Summary</h2><p>{html.escape(str((sections.get('project_overview') or {})))}</p>
<h2>Land / RERA</h2><p>{html.escape(str(sections.get('land_rera') or {}))}</p>
<h2>AI Extraction Risks and Assumptions</h2>
<p><b>Missing:</b> {html.escape('; '.join(sections.get('missing_information') or []) or 'None listed')}</p>
<p><b>Assumptions:</b> {html.escape('; '.join(sections.get('assumptions') or []) or 'None listed')}</p>
<h2>16-Division BOQ</h2><table><thead><tr><th>Division</th><th>Code</th><th>Description</th><th>Qty</th><th>Unit</th><th>Rate</th><th>Amount</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="muted">Indicative concept estimate. Verify drawings, statutory fees, supplier quotations, GST treatment and market rates before tender, bank or RERA submission.</p>
</body></html>"""

def ensure_share_token(row):
    token = row["share_token"] if "share_token" in row.keys() and row["share_token"] else None
    if token:
        return token
    token = uuid.uuid4().hex
    get_db().execute("UPDATE projects SET share_token = ?, updated_at = ? WHERE id = ?", (token, now(), row["id"]))
    get_db().commit()
    return token

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
    gst_breakup = estimate.get("gst_breakup") or {}
    writer.writerow(["IGST 12%", gst_breakup.get("igst_12pct", 0)])
    writer.writerow(["IGST 18%", gst_breakup.get("igst_18pct", 0)])
    writer.writerow(["Total GST", gst_breakup.get("total_gst")])
    writer.writerow(["Total With GST", estimate.get("total_with_gst")])
    writer.writerow(["Cost Per Sqft", estimate.get("cost_per_sqft") if estimate.get("cost_per_sqft") is not None else estimate.get("cost_per_sqft_note") or "Not applicable"])
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

@app.route("/api/projects/<project_id>/report/pdf", methods=["GET"])
@require_auth
def project_report_pdf(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before exporting a PDF."}), 400
    report = project_report_payload(row)
    report_html = render_report_html(report)
    try:
        from weasyprint import HTML
        pdf = HTML(string=report_html).write_pdf()
        return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=nirman_report_{project_id}.pdf"})
    except Exception:
        return Response(report_html, mimetype="text/html", headers={"Content-Disposition": f"attachment; filename=nirman_report_{project_id}.html"})

@app.route("/api/projects/<project_id>/share", methods=["POST"])
@require_auth
def share_project_report(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    if not row["estimate"]:
        return jsonify({"success": False, "message": "Generate an estimate before sharing."}), 400
    token = ensure_share_token(row)
    base_url = (request.host_url or "").rstrip("/")
    link = f"{base_url}/report/{token}"
    return jsonify({"success": True, "share_token": token, "url": link})

@app.route("/report/<share_token>", methods=["GET"])
def public_report_page(share_token):
    row = get_db().execute("SELECT * FROM projects WHERE share_token = ?", (share_token,)).fetchone()
    if not row or not row["estimate"]:
        return Response("Report not found.", status=404)
    return Response(render_report_html(project_report_payload(row)), mimetype="text/html")

@app.route("/api/report/<share_token>", methods=["GET"])
def public_report_json(share_token):
    row = get_db().execute("SELECT * FROM projects WHERE share_token = ?", (share_token,)).fetchone()
    if not row or not row["estimate"]:
        return jsonify({"success": False, "message": "Report not found."}), 404
    return jsonify({"success": True, "report": project_report_payload(row)})

@app.route("/api/projects/<project_id>/share/email", methods=["POST"])
@require_auth
def share_project_email(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    token = ensure_share_token(row)
    body = request.get_json() or {}
    recipient = (body.get("email") or "").strip()
    link = f"{(request.host_url or '').rstrip('/')}/report/{token}"
    get_db().execute("INSERT INTO report_deliveries (id, project_id, user_id, channel, recipient, share_token, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid(), project_id, g.current_user["id"], "email", recipient, token, "link_created", now()))
    get_db().commit()
    subject = urllib.parse.quote(f"Nirman.AI estimate: {row['name']}")
    mail_body = urllib.parse.quote(f"Open the Nirman.AI project report here: {link}")
    return jsonify({"success": True, "url": link, "mailto": f"mailto:{recipient}?subject={subject}&body={mail_body}"})

@app.route("/api/projects/<project_id>/share/whatsapp", methods=["POST"])
@require_auth
def share_project_whatsapp(project_id):
    row = get_owned_project(project_id)
    if not row:
        return jsonify({"success": False, "message": "Project not found."}), 404
    token = ensure_share_token(row)
    link = f"{(request.host_url or '').rstrip('/')}/report/{token}"
    message = urllib.parse.quote(f"Nirman.AI estimate for {row['name']}: {link}")
    get_db().execute("INSERT INTO report_deliveries (id, project_id, user_id, channel, recipient, share_token, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid(), project_id, g.current_user["id"], "whatsapp", "", token, "link_created", now()))
    get_db().commit()
    return jsonify({"success": True, "url": link, "whatsapp": f"https://wa.me/?text={message}"})

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
        total = WAITLIST_PUBLIC_BASE + db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
        return jsonify({"success": True, "message": "You are on the list.", "total": total}), 201
    except Exception as exc:
        if not (isinstance(exc, sqlite3.IntegrityError) or (USE_POSTGRES and getattr(exc, "pgcode", None) == "23505")):
            raise
        return jsonify({"success": False, "message": "This email is already registered."}), 409

@app.route("/api/waitlist/count", methods=["GET"])
def waitlist_count():
    actual = count_actual_waitlist()
    return jsonify({"total": WAITLIST_PUBLIC_BASE + actual, "actual": actual, "base": WAITLIST_PUBLIC_BASE})

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

@app.route("/api/admin/feedback", methods=["GET"])
def admin_feedback():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        """
        SELECT f.id, f.project_id, p.name AS project_name, u.email AS user_email,
               f.rating, f.comment, f.actual_cost, f.created_at
        FROM estimate_feedback f
        LEFT JOIN projects p ON p.id = f.project_id
        LEFT JOIN users u ON u.id = f.user_id
        ORDER BY f.created_at DESC
        LIMIT 200
        """
    ).fetchall()
    return jsonify({"success": True, "feedback": [dict(r) for r in rows]})

@app.route("/api/admin/rate-corrections", methods=["GET"])
def admin_rate_corrections():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT * FROM rate_corrections ORDER BY created_at DESC LIMIT 300"
    ).fetchall()
    return jsonify({"success": True, "corrections": [dict(r) for r in rows]})

@app.route("/api/admin/contractor-quotes", methods=["GET"])
def admin_contractor_quotes():
    if not require_admin_key():
        return jsonify({"success": False, "message": "Unauthorized."}), 401
    rows = get_db().execute(
        "SELECT * FROM contractor_quotes ORDER BY created_at DESC LIMIT 300"
    ).fetchall()
    return jsonify({"success": True, "quotes": [dict(r) for r in rows]})

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
