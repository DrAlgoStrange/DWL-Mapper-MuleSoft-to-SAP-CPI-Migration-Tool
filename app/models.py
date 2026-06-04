import json
import logging
from datetime import datetime
from flask_login import UserMixin
from .extensions import db, login_manager

logger = logging.getLogger(__name__)

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    project_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    wwid = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active_account = db.Column(db.Boolean, default=True)

    projects = db.relationship('Project', backref='owner', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.email}>'


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(50), default='draft')  # draft, processing, completed, error

    # XSD/WSDL schemas stored once at project level —
    # source = CPI mapping input structure, target = CPI mapping output structure
    source_schema_filename = db.Column(db.String(255), nullable=True)
    source_schema_content = db.Column(db.Text, nullable=True)
    target_schema_filename = db.Column(db.String(255), nullable=True)
    target_schema_content = db.Column(db.Text, nullable=True)

    dwls = db.relationship('DWLEntry', backref='project', lazy=True, cascade='all, delete-orphan')
    mapping_results = db.relationship('MappingResult', backref='project', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Project {self.name}>'


class DWLEntry(db.Model):
    __tablename__ = 'dwl_entries'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    sequence_number = db.Column(db.Integer, nullable=False, default=1)
    dwl_name = db.Column(db.String(200), nullable=True)
    dwl_content = db.Column(db.Text, nullable=False)
    sample_input = db.Column(db.Text, nullable=True)
    sample_output = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DWLEntry {self.id} - Project {self.project_id}>'


class MappingResult(db.Model):
    __tablename__ = 'mapping_results'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    model_used = db.Column(db.String(100), nullable=True)
    raw_llm_response = db.Column(db.Text, nullable=True)
    mapping_data_json = db.Column(db.Text, nullable=True)  # JSON of parsed mapping rows
    xlsx_filename = db.Column(db.String(255), nullable=True)
    xlsx_path = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(50), default='pending')  # pending, success, error
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_mapping_data(self):
        if self.mapping_data_json:
            try:
                return json.loads(self.mapping_data_json)
            except Exception:
                return []
        return []

    def set_mapping_data(self, data):
        self.mapping_data_json = json.dumps(data)

    def __repr__(self):
        return f'<MappingResult {self.id} - Project {self.project_id}>'
