# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import math
import uuid
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bookmycomplaint_secret_key_2024')

# Configuration — fix postgres:// to postgresql:// for SQLAlchemy compatibility
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max for videos
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}

# Create upload folder if not exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Database Models
class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    location_lat = db.Column(db.Float, nullable=False)
    location_lng = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(500))
    video_filename = db.Column(db.String(500))
    is_anonymous = db.Column(db.Boolean, default=False)
    user_phone = db.Column(db.String(15))
    user_email = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Pending')
    assigned_to = db.Column(db.String(100))
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PoliceStation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location_lat = db.Column(db.Float, nullable=False)
    location_lng = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(500))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    jurisdiction = db.Column(db.String(200))

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    station_id = db.Column(db.Integer, db.ForeignKey('police_station.id'))
    role = db.Column(db.String(50), default='admin')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to find nearest police station
def find_nearest_station(lat, lng):
    stations = PoliceStation.query.all()
    if not stations:
        return None
    
    def calculate_distance(lat1, lng1, lat2, lng2):
        R = 6371  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
    
    nearest = min(stations, key=lambda s: calculate_distance(lat, lng, s.location_lat, s.location_lng))
    return nearest

# Routes
@app.route('/')
def index():
    # Dashboard stats
    total_complaints = Complaint.query.count()
    pending_complaints = Complaint.query.filter_by(status='Pending').count()
    resolved_complaints = Complaint.query.filter_by(status='Resolved').count()
    in_investigation = Complaint.query.filter_by(status='Under Investigation').count()
    
    recent_complaints = Complaint.query.order_by(Complaint.created_at.desc()).limit(5).all()
    
    return render_template('index.html', 
                         total_complaints=total_complaints,
                         pending_complaints=pending_complaints,
                         resolved_complaints=resolved_complaints,
                         in_investigation=in_investigation,
                         recent_complaints=recent_complaints)

@app.route('/complaint-form')
def complaint_form():
    return render_template('complaint_form.html')

@app.route('/submit-complaint', methods=['POST'])
def submit_complaint():
    try:
        complaint_id = f"BMC{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4]}"
        
        category = request.form.get('category')
        description = request.form.get('description')
        location_lat = request.form.get('location_lat')
        location_lng = request.form.get('location_lng')
        address = request.form.get('address')
        is_anonymous = request.form.get('is_anonymous') == 'on'
        user_phone = request.form.get('user_phone') if not is_anonymous else None
        user_email = request.form.get('user_email') if not is_anonymous else None
        
        # Validate inputs
        if not category or not description or not location_lat or not location_lng:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Handle video upload
        video_filename = None
        if 'video' in request.files:
            video = request.files['video']
            if video and video.filename and allowed_file(video.filename):
                filename = f"{complaint_id}_{secure_filename(video.filename)}"
                video.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                video_filename = filename
        
        # Assign to nearest police station
        nearest_station = find_nearest_station(float(location_lat), float(location_lng))
        assigned_to = nearest_station.name if nearest_station else 'Headquarters'
        
        complaint = Complaint(
            complaint_id=complaint_id,
            category=category,
            description=description,
            location_lat=float(location_lat),
            location_lng=float(location_lng),
            address=address,
            video_filename=video_filename,
            is_anonymous=is_anonymous,
            user_phone=user_phone,
            user_email=user_email,
            assigned_to=assigned_to,
            status='Pending'
        )
        
        db.session.add(complaint)
        db.session.commit()
        
        return jsonify({'success': True, 'complaint_id': complaint_id, 'assigned_to': assigned_to})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/track-complaint', methods=['GET', 'POST'])
def track_complaint():
    if request.method == 'POST':
        complaint_id = request.form.get('complaint_id')
        complaint = Complaint.query.filter_by(complaint_id=complaint_id).first()
        if complaint:
            return render_template('track_result.html', complaint=complaint)
        else:
            return render_template('track.html', error='Complaint ID not found')
    return render_template('track.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username, password=password).first()
        if admin:
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            session['admin_role'] = admin.role
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error='Invalid credentials')
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
    total = len(complaints)
    pending = Complaint.query.filter_by(status='Pending').count()
    in_investigation = Complaint.query.filter_by(status='Under Investigation').count()
    resolved = Complaint.query.filter_by(status='Resolved').count()
    
    # Category wise counts
    emergency_count = Complaint.query.filter_by(category='Emergency').count()
    traffic_count = Complaint.query.filter_by(category='Traffic').count()
    civil_count = Complaint.query.filter_by(category='Civil').count()
    
    return render_template('admin_dashboard.html', 
                         complaints=complaints,
                         total=total,
                         pending=pending,
                         in_investigation=in_investigation,
                         resolved=resolved,
                         emergency=emergency_count,
                         traffic=traffic_count,
                         civil=civil_count)

@app.route('/admin/complaint/<int:complaint_id>')
@login_required
def view_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    return render_template('admin_view_complaint.html', complaint=complaint)

@app.route('/admin/update-status', methods=['POST'])
@login_required
def update_status():
    complaint_id = request.form.get('complaint_id')
    status = request.form.get('status')
    remarks = request.form.get('remarks')
    
    complaint = Complaint.query.get_or_404(complaint_id)
    complaint.status = status
    complaint.remarks = remarks
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

# API endpoint for emergency
@app.route('/check-emergency')
def check_emergency():
    return jsonify({'emergency': True, 'message': 'For emergency, please call 112 immediately!'})
# ========== ADMIN: ALL COMPLAINTS (with filters) ==========
@app.route('/admin/all-complaints')
@login_required
def admin_all_complaints():
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    
    query = Complaint.query
    if category:
        query = query.filter_by(category=category)
    if status:
        query = query.filter_by(status=status)
    if search:
        query = query.filter(Complaint.complaint_id.contains(search))
    
    complaints = query.order_by(Complaint.created_at.desc()).all()
    return render_template('admin_all_complaints.html', complaints=complaints)

# ========== ADMIN: POLICE STATIONS MANAGEMENT ==========
@app.route('/admin/police-stations')
@login_required
def admin_police_stations():
    stations = PoliceStation.query.all()
    return render_template('admin_police_stations.html', stations=stations)

@app.route('/admin/add-station', methods=['POST'])
@login_required
def add_station():
    data = request.json
    station = PoliceStation(
        name=data['name'],
        location_lat=data['location_lat'],
        location_lng=data['location_lng'],
        address=data.get('address', ''),
        phone=data.get('phone', ''),
        email=data.get('email', '')
    )
    db.session.add(station)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/get-station/<int:id>')
@login_required
def get_station(id):
    station = PoliceStation.query.get_or_404(id)
    return jsonify({
        'id': station.id,
        'name': station.name,
        'location_lat': station.location_lat,
        'location_lng': station.location_lng,
        'address': station.address,
        'phone': station.phone,
        'email': station.email
    })

@app.route('/admin/update-station/<int:id>', methods=['PUT'])
@login_required
def update_station(id):
    station = PoliceStation.query.get_or_404(id)
    data = request.json
    station.name = data['name']
    station.location_lat = data['location_lat']
    station.location_lng = data['location_lng']
    station.address = data.get('address', '')
    station.phone = data.get('phone', '')
    station.email = data.get('email', '')
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/delete-station/<int:id>', methods=['DELETE'])
@login_required
def delete_station(id):
    station = PoliceStation.query.get_or_404(id)
    db.session.delete(station)
    db.session.commit()
    return jsonify({'success': True})

# ========== ADMIN: SETTINGS ==========
@app.route('/admin/settings')
@login_required
def admin_settings():
    total_complaints = Complaint.query.count()
    total_stations = PoliceStation.query.count()
    total_admins = Admin.query.count()
    return render_template('admin_settings.html', 
                         total_complaints=total_complaints,
                         total_stations=total_stations,
                         total_admins=total_admins)

@app.route('/admin/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.json
    admin = Admin.query.get(session['admin_id'])
    if admin.password != data['current_password']:
        return jsonify({'success': False, 'message': 'Current password is incorrect'})
    admin.password = data['new_password']
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/clear-complaints', methods=['DELETE'])
@login_required
def clear_complaints():
    try:
        num_deleted = db.session.query(Complaint).delete()
        db.session.commit()
        return jsonify({'success': True, 'deleted': num_deleted})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/reset-demo', methods=['POST'])
@login_required
def reset_demo():
    # Add sample police stations if none exist
    if PoliceStation.query.count() == 0:
        stations = [
            PoliceStation(name='Koramangala Police Station', location_lat=12.9279, location_lng=77.6271,
                         address='Koramangala, Bangalore', phone='080-25532211'),
            PoliceStation(name='Indiranagar Police Station', location_lat=12.9784, location_lng=77.6408,
                         address='Indiranagar, Bangalore', phone='080-25262211'),
            PoliceStation(name='MG Road Police Station', location_lat=12.9752, location_lng=77.6068,
                         address='MG Road, Bangalore', phone='080-25582211'),
            PoliceStation(name='Whitefield Police Station', location_lat=12.9698, location_lng=77.7499,
                         address='Whitefield, Bangalore', phone='080-28452211'),
        ]
        db.session.add_all(stations)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Demo data added (police stations)'})
    else:
        return jsonify({'success': False, 'message': 'Stations already exist'})
# ✅ This runs on BOTH Render and locally
with app.app_context():
    db.create_all()

    # Add sample police stations if none exist
    if PoliceStation.query.count() == 0:
        stations = [
            PoliceStation(name='Koramangala Police Station', location_lat=12.9279, location_lng=77.6271,
                         address='Koramangala, Bangalore', phone='080-25532211'),
            PoliceStation(name='Indiranagar Police Station', location_lat=12.9784, location_lng=77.6408,
                         address='Indiranagar, Bangalore', phone='080-25262211'),
            PoliceStation(name='MG Road Police Station', location_lat=12.9752, location_lng=77.6068,
                         address='MG Road, Bangalore', phone='080-25582211'),
            PoliceStation(name='Whitefield Police Station', location_lat=12.9698, location_lng=77.7499,
                         address='Whitefield, Bangalore', phone='080-28452211'),
        ]
        db.session.add_all(stations)
        db.session.commit()

    # Add default admin if none exists
    if Admin.query.count() == 0:
        admin = Admin(username='admin', password='admin@123', role='super_admin')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)