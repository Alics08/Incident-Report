import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, abort, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from report_generator import generate_incident_report
import sqlite3
import pytz

from sqlalchemy import func
from collections import defaultdict

app = Flask(__name__)

# ----------------------
# CONFIGURATION (FIXED FOR RENDER)
# ----------------------

app.config['SECRET_KEY'] = 'adminsecret'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'images')
REPORT_FOLDER = os.path.join(BASE_DIR, 'reports')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db_path = os.path.join(BASE_DIR, "incidents.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 🔥 FIX: limit upload size (prevents crash)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

db = SQLAlchemy(app)

PH_TIMEZONE = pytz.timezone("Asia/Manila")

# ----------------------
# 🔥 FIX: RENDER PORT
# ----------------------
PORT = int(os.environ.get("PORT", 5000))

# ----------------------
# AUTO CLEAR FLASH CACHE
# ----------------------

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# ----------------------
# DATABASE MODEL
# ----------------------

class Incident(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(100))
    description = db.Column(db.String(300))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    photo = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    status = db.Column(db.String(20), default="ongoing")
    address = db.Column(db.String(300))

# ----------------------
# DATABASE FIX FUNCTION
# ----------------------

def fix_database():

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incident (
        id INTEGER PRIMARY KEY AUTOINCREMENT
    )
    """)

    cursor.execute("PRAGMA table_info(incident)")
    columns = [column[1] for column in cursor.fetchall()]

    if "type" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN type TEXT")

    if "description" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN description TEXT")

    if "latitude" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN latitude REAL")

    if "longitude" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN longitude REAL")

    if "photo" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN photo TEXT")

    if "created_at" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN created_at DATETIME")

    if "status" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN status TEXT DEFAULT 'ongoing'")

    if "address" not in columns:
        cursor.execute("ALTER TABLE incident ADD COLUMN address TEXT")

    conn.commit()
    conn.close()

# ----------------------
# SAFE TIME FORMATTER
# ----------------------

def format_time(dt):
    try:
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = PH_TIMEZONE.localize(dt)
        return dt.astimezone(PH_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return str(dt)

# ----------------------
# PUBLIC PAGE
# ----------------------

@app.route('/')
def home():
    return redirect(url_for('report'))

# ----------------------
# 🚨 FIXED REPORT INCIDENT (MAIN BUG FIX)
# ----------------------

@app.route('/report', methods=['GET','POST'])
def report():

    if request.method == "POST":

        try:
            type = request.form.get('type')
            description = request.form.get('description')

            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')

            address = request.form.get('address')

            if not latitude or not longitude:
                flash("Location is required.", "danger")
                return redirect(url_for('report'))

            latitude = float(latitude)
            longitude = float(longitude)

            photo = request.files.get('photo')

            if not photo or photo.filename == "":
                flash("Photo evidence is required.", "danger")
                return redirect(url_for('report'))

            time_limit = datetime.utcnow() - timedelta(minutes=30)

            recent_reports = Incident.query.filter(
                Incident.created_at >= time_limit
            ).count()

            if recent_reports >= 4:
                flash("Max 4 incidents per 30 minutes reached.", "danger")
                return redirect(url_for('report'))

            filename = ""

            if photo:
                filename = secure_filename(photo.filename)

                # 🔥 FIX: prevent overwrite crash
                unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)

                photo.save(photo_path)
                filename = unique_name

            incident = Incident(
                type=type,
                description=description,
                latitude=latitude,
                longitude=longitude,
                photo=filename,
                created_at=datetime.utcnow(),
                status="ongoing",
                address=address
            )

            db.session.add(incident)
            db.session.commit()

            flash("Incident submitted.", "success")
            return redirect(url_for('report'))

        except Exception as e:
            print("❌ SUBMIT ERROR:", e)
            flash("Server error. Please try again.", "danger")
            return redirect(url_for('report'))

    return render_template("report.html")

# ----------------------
# ADMIN LOGIN
# ----------------------

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123456"

@app.route('/admin', methods=['GET','POST'])
def admin_login():

    if request.method == "POST":

        username = request.form.get('username')
        password = request.form.get('password')

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('dashboard'))

        flash("Invalid login.", "danger")

    return render_template("login.html")

# ----------------------
# DASHBOARD
# ----------------------

@app.route('/dashboard')
def dashboard():

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    try:
        incidents = Incident.query.filter_by(status="ongoing")\
            .order_by(Incident.created_at.desc()).all()
    except Exception as e:
        print("DB ERROR:", e)
        incidents = []

    incident_list = []

    for i in incidents:
        incident_list.append({
            "id": i.id,
            "type": i.type,
            "description": i.description,
            "latitude": i.latitude,
            "longitude": i.longitude,
            "photo": i.photo,
            "address": i.address,
            "time": format_time(i.created_at)
        })

    return render_template("dashboard.html", incidents=incident_list)

# ----------------------
# DOWNLOAD REPORT
# ----------------------

@app.route('/download-report/<int:id>')
def download_report(id):

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incident = Incident.query.get_or_404(id)

    try:
        filepath = generate_incident_report(
            incident,
            app.config['UPLOAD_FOLDER']
        )
    except Exception as e:
        print("PDF ERROR:", e)
        abort(500)

    return send_file(
        filepath,
        as_attachment=True,
        download_name=f"incident_report_{incident.id}.pdf"
    )

# ----------------------
# START APPLICATION
# ----------------------

if __name__ == "__main__":

    with app.app_context():
        db.create_all()
        fix_database()

    app.run(host="0.0.0.0", port=PORT)