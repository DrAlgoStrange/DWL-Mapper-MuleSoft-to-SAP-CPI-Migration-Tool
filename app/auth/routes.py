import re
import logging
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from . import auth
from ..extensions import db, bcrypt
from ..models import User

logger = logging.getLogger(__name__)

PASSWORD_REGEX = re.compile(r'^(?=.*[A-Z])(?=.*[!@#$%^&*?]).{8,}$')
EMAIL_REGEX    = re.compile(r'^[^@]+@its\.jnj\.com$', re.IGNORECASE)
WWID_REGEX     = re.compile(r'^\d+$')


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            email    = (data.get('email') or request.form.get('email', '')).strip().lower()
            password = data.get('password') or request.form.get('password', '')
            remember = data.get('remember', False)

            user = User.query.filter_by(email=email).first()

            if not user or not bcrypt.check_password_hash(user.password_hash, password):
                logger.warning(f"Failed login attempt for email: {email}")
                return jsonify({'success': False, 'message': 'Invalid email or password.'}), 401

            if not user.is_active_account:
                return jsonify({'success': False, 'message': 'Account is disabled.'}), 403

            login_user(user, remember=remember)
            logger.info(f"User logged in: {email}")
            return jsonify({'success': True, 'redirect': url_for('main.home')})

        except Exception as e:
            logger.error(f"Login error: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'An error occurred. Please try again.'}), 500

    return render_template('auth/login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}

            full_name    = (data.get('full_name') or '').strip()
            project_name = (data.get('project_name') or '').strip()
            email        = (data.get('email') or '').strip().lower()
            wwid         = (data.get('wwid') or '').strip()
            password     = data.get('password') or ''
            confirm_pwd  = data.get('confirm_password') or ''

            # Validations
            errors = {}
            if not full_name:
                errors['full_name'] = 'Full name is required.'
            if not project_name:
                errors['project_name'] = 'Project name is required.'
            if not email or not EMAIL_REGEX.match(email):
                errors['email'] = 'Email must be a valid @its.jnj.com address.'
            if wwid and not WWID_REGEX.match(wwid):
                errors['wwid'] = 'WWID must contain numbers only.'
            if not password or not PASSWORD_REGEX.match(password):
                errors['password'] = 'Password must be 8+ chars with at least one uppercase letter and one special character (!@#$%^&*?).'
            if password != confirm_pwd:
                errors['confirm_password'] = 'Passwords do not match.'

            if errors:
                return jsonify({'success': False, 'errors': errors}), 400

            # Check email uniqueness
            if User.query.filter_by(email=email).first():
                return jsonify({'success': False, 'errors': {'email': 'An account with this email already exists.'}}), 409

            hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
            user = User(
                full_name=full_name,
                project_name=project_name,
                email=email,
                wwid=wwid if wwid else None,
                password_hash=hashed_pw,
            )
            db.session.add(user)
            db.session.commit()
            logger.info(f"New user registered: {email}")

            login_user(user)
            return jsonify({'success': True, 'redirect': url_for('main.home')})

        except Exception as e:
            db.session.rollback()
            logger.error(f"Registration error: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Registration failed. Please try again.'}), 500

    return render_template('auth/login.html')


@auth.route('/logout')
@login_required
def logout():
    logger.info(f"User logged out: {current_user.email}")
    logout_user()
    return redirect(url_for('auth.login'))
