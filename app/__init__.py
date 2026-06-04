import os
import logging
import logging.handlers
from flask import Flask
from .config import config
from .extensions import db, login_manager, bcrypt


def create_app(config_name: str = None) -> Flask:
    """Application Factory."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config.get(config_name, config['default']))

    # ── Ensure required directories exist ──────────────────────────────────
    for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
        os.makedirs(folder, exist_ok=True)

    # ── Logging Setup ──────────────────────────────────────────────────────
    _setup_logging(app)

    # ── Extensions ─────────────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # ── Blueprints ─────────────────────────────────────────────────────────
    from .auth import auth as auth_bp
    from .main import main as main_bp
    from .api import api as api_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    # ── Database init ──────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        app.logger.info("Database tables created / verified.")

    app.logger.info(f"DWL Mapper started | env={config_name}")
    return app


def _setup_logging(app: Flask):
    log_level = logging.DEBUG if app.config.get('DEBUG') else logging.INFO
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s (%(funcName)s:%(lineno)d): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(formatter)

    # File handler (rotating)
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)

    app.logger.info("Logging configured.")
