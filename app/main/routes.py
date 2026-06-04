import logging
from flask import render_template, redirect, url_for, jsonify, request
from flask_login import login_required, current_user
from . import main
from ..extensions import db
from ..models import Project, DWLEntry, MappingResult

logger = logging.getLogger(__name__)


@main.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    return redirect(url_for('auth.login'))


@main.route('/home')
@login_required
def home():
    try:
        projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.updated_at.desc()).all()
        return render_template('main/home.html', projects=projects, user=current_user)
    except Exception as e:
        logger.error(f"Home page error for user {current_user.id}: {e}", exc_info=True)
        return render_template('main/home.html', projects=[], user=current_user)


@main.route('/project/new', methods=['GET', 'POST'])
@login_required
def new_project():
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            name        = (data.get('name') or '').strip()
            description = (data.get('description') or '').strip()

            if not name:
                return jsonify({'success': False, 'message': 'Project name is required.'}), 400

            # Check uniqueness per user
            existing = Project.query.filter_by(user_id=current_user.id, name=name).first()
            if existing:
                return jsonify({'success': False, 'message': f'A project named "{name}" already exists in your account.'}), 409

            # Limit description to ~100 words
            if description:
                words = description.split()
                if len(words) > 100:
                    description = ' '.join(words[:100])

            project = Project(name=name, description=description, user_id=current_user.id)
            db.session.add(project)
            db.session.commit()
            logger.info(f"New project created: '{name}' by user {current_user.id}")
            return jsonify({'success': True, 'project_id': project.id, 'redirect': url_for('main.project_detail', project_id=project.id)})

        except Exception as e:
            db.session.rollback()
            logger.error(f"New project error: {e}", exc_info=True)
            return jsonify({'success': False, 'message': 'Failed to create project. Please try again.'}), 500

    return render_template('main/new_project.html', user=current_user)


@main.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    try:
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        dwls = DWLEntry.query.filter_by(project_id=project_id).order_by(DWLEntry.sequence_number).all()
        results = MappingResult.query.filter_by(project_id=project_id).order_by(MappingResult.created_at.desc()).all()
        return render_template('main/project.html', project=project, dwls=dwls, results=results, user=current_user)
    except Exception as e:
        logger.error(f"Project detail error for project {project_id}: {e}", exc_info=True)
        return redirect(url_for('main.home'))


@main.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    try:
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        db.session.delete(project)
        db.session.commit()
        logger.info(f"Project {project_id} deleted by user {current_user.id}")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete project error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to delete project.'}), 500
