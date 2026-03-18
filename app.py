from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, abort, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from report_generator import generate_incident_report
import os
import sqlite3
import pytz

# ✅ NEW IMPORTS (ADDED ONLY)
from sqlalchemy import func
from collections import defaultdict

app = Flask(__name__)

# ----------------------
# CONFIGURATION
# ----------------------

app.config['SECRET_KEY'] = 'adminsecret'

app.config['UPLOAD_FOLDER'] = os.path.join('static', 'images')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///incidents.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

PH_TIMEZONE = pytz.timezone("Asia/Manila")

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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(PH_TIMEZONE))
    status = db.Column(db.String(20), default="ongoing")
    address = db.Column(db.String(300))


# ----------------------
# DATABASE FIX FUNCTION
# ----------------------

def fix_database():

    conn = sqlite3.connect("incidents.db")
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
# PUBLIC PAGE
# ----------------------

@app.route('/')
def home():
    return redirect(url_for('report'))


# ----------------------
# REPORT INCIDENT
# ----------------------

@app.route('/report', methods=['GET','POST'])
def report():

    if request.method == "POST":

        type = request.form.get('type')
        description = request.form.get('description')

        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')

        address = request.form.get('address')

        if not latitude or not longitude:
            return redirect(url_for('report'))

        latitude = float(latitude)
        longitude = float(longitude)

        photo = request.files.get('photo')

        if not photo or photo.filename == "":
            flash("Photo evidence is required. False reports are punishable by law.", "danger")
            return redirect(url_for('report'))

        time_limit = datetime.now(PH_TIMEZONE) - timedelta(minutes=30)

        recent_reports = Incident.query.filter(
            Incident.created_at >= time_limit
        ).count()

        if recent_reports >= 4:
            flash("Maximum of 4 incidents every 30 minutes reached. Please wait.", "danger")
            return redirect(url_for('report'))

        filename = ""

        if photo and photo.filename != "":
            filename = secure_filename(photo.filename)
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(photo_path)

        incident = Incident(
            type=type,
            description=description,
            latitude=latitude,
            longitude=longitude,
            photo=filename,
            created_at=datetime.now(PH_TIMEZONE),
            status="ongoing",
            address=address
        )

        db.session.add(incident)
        db.session.commit()

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

    return render_template("login.html")


# ----------------------
# ADMIN DASHBOARD
# ----------------------

@app.route('/dashboard')
def dashboard():

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incidents = Incident.query.filter_by(status="ongoing")\
        .order_by(Incident.created_at.desc()).all()

    incident_list = []

    for i in incidents:

        time_value = ""

        if i.created_at:
            time_value = i.created_at.strftime("%Y-%m-%d %H:%M:%S")

        incident_list.append({
            "id": i.id,
            "type": i.type,
            "description": i.description,
            "latitude": i.latitude,
            "longitude": i.longitude,
            "photo": i.photo,
            "address": i.address,
            "time": time_value
        })

    return render_template("dashboard.html", incidents=incident_list)


# ----------------------
# DELETE INCIDENT
# ----------------------

@app.route('/delete_incident/<int:id>', methods=['POST'])
def delete_incident(id):

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incident = Incident.query.get_or_404(id)

    if incident.photo:
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], incident.photo)
        if os.path.exists(photo_path):
            os.remove(photo_path)

    db.session.delete(incident)
    db.session.commit()

    flash("Incident deleted successfully.", "success")

    return redirect(request.referrer or url_for('dashboard'))


# ----------------------
# LIVE INCIDENT API
# ----------------------

@app.route('/api/incidents')
def api_incidents():

    incidents = Incident.query.filter_by(status="ongoing")\
        .order_by(Incident.created_at.desc()).all()

    data = []

    for i in incidents:

        time_value = ""

        if i.created_at:
            time_value = i.created_at.strftime("%Y-%m-%d %H:%M:%S")

        data.append({
            "id": i.id,
            "type": i.type or "",
            "description": i.description or "",
            "latitude": i.latitude,
            "longitude": i.longitude,
            "photo": i.photo or "",
            "address": i.address or "",
            "time": time_value
        })

    return jsonify(data)


# ----------------------
# DOWNLOAD INCIDENT REPORT
# ----------------------

@app.route('/download-report/<int:id>')
def download_report(id):

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incident = Incident.query.get_or_404(id)

    filepath = generate_incident_report(
        incident,
        app.config['UPLOAD_FOLDER']
    )

    return send_file(
        filepath,
        as_attachment=True,
        download_name=f"incident_report_{incident.id}.pdf"
    )


# ----------------------
# RESOLVE INCIDENT
# ----------------------

@app.route('/resolve/<int:id>')
def resolve_incident(id):

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incident = Incident.query.get_or_404(id)

    incident.status = "resolved"
    db.session.commit()

    return redirect(url_for('dashboard'))


# ----------------------
# ARCHIVE (GROUPED BY DATE)
# ----------------------

@app.route('/archive')
def archive():

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    incidents = Incident.query.filter_by(status="resolved")\
        .order_by(Incident.created_at.desc()).all()

    grouped = defaultdict(list)

    for i in incidents:
        date_key = i.created_at.strftime("%B %d, %Y") if i.created_at else "Unknown Date"
        grouped[date_key].append(i)

    return render_template("archive.html", grouped_incidents=grouped)


# ----------------------
# 📊 MONTHLY REPORT (SYNCED WITH ARCHIVE)
# ----------------------

@app.route('/monthly-report')
def monthly_report():

    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    current_month = datetime.now(PH_TIMEZONE).month
    current_year = datetime.now(PH_TIMEZONE).year

    incidents = Incident.query.filter(
        func.extract('month', Incident.created_at) == current_month,
        func.extract('year', Incident.created_at) == current_year
    ).order_by(Incident.created_at.desc()).all()

    # ✅ GROUP LIKE ARCHIVE
    grouped = defaultdict(list)

    for i in incidents:
        date_key = i.created_at.strftime("%B %d, %Y") if i.created_at else "Unknown Date"
        grouped[date_key].append(i)

    # ✅ GRAPH DATA
    summary = db.session.query(
        Incident.type,
        func.count(Incident.id)
    ).filter(
        func.extract('month', Incident.created_at) == current_month,
        func.extract('year', Incident.created_at) == current_year
    ).group_by(Incident.type).all()

    labels = [s[0] for s in summary]
    values = [s[1] for s in summary]

    return render_template(
        "monthly_report.html",
        incidents=incidents,
        grouped_incidents=grouped,  # ✅ KEY SYNC
        labels=labels,
        values=values
    )


# ----------------------
# LOGOUT
# ----------------------

@app.route('/logout')
def logout():

    session.pop('admin', None)
    return redirect(url_for('admin_login'))


# ----------------------
# START APPLICATION
# ----------------------

if __name__ == "__main__":

    with app.app_context():
        db.create_all()
        fix_database()

    app.run(host="0.0.0.0", port=5000, debug=True)