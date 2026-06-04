"""
API Routes — handles DWL CRUD, file uploads, and mapping generation.
All operations have full exception handling + logging.
"""
import os
import json
import logging
import uuid
from datetime import datetime
from flask import request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from . import api
from ..extensions import db
from ..models import Project, DWLEntry, MappingResult
from ..services.llm_service import (
    call_llm_with_fallback, build_dwl_analysis_prompt, parse_llm_mapping_response
)
from ..services.excel_service import generate_mapping_xlsx

logger = logging.getLogger(__name__)


# ── DWL Entries ────────────────────────────────────────────────────────────

@api.route('/project/<int:project_id>/dwl', methods=['POST'])
@login_required
def add_dwl(project_id):
    """Add a DWL entry to a project."""
    try:
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()

        dwl_name      = request.form.get('dwl_name', '').strip()
        dwl_content   = request.form.get('dwl_content', '').strip()
        sample_input  = request.form.get('sample_input', '').strip()
        sample_output = request.form.get('sample_output', '').strip()

        if not dwl_content:
            return jsonify({'success': False, 'message': 'DWL content is required.'}), 400

        max_seq = db.session.query(db.func.max(DWLEntry.sequence_number)).filter_by(project_id=project_id).scalar() or 0

        dwl_entry = DWLEntry(
            project_id=project_id,
            sequence_number=max_seq + 1,
            dwl_name=dwl_name or f"DWL Step {max_seq + 1}",
            dwl_content=dwl_content,
            sample_input=sample_input or None,
            sample_output=sample_output or None,
        )
        db.session.add(dwl_entry)
        project.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"DWL entry added to project {project_id}: seq={max_seq + 1}")

        return jsonify({
            'success': True,
            'dwl_id': dwl_entry.id,
            'sequence_number': dwl_entry.sequence_number,
            'dwl_name': dwl_entry.dwl_name,
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Add DWL error for project {project_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Failed to save DWL: {str(e)}'}), 500


@api.route('/project/<int:project_id>/dwl/<int:dwl_id>', methods=['DELETE'])
@login_required
def delete_dwl(project_id, dwl_id):
    """Delete a DWL entry."""
    try:
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        dwl_entry = DWLEntry.query.filter_by(id=dwl_id, project_id=project_id).first_or_404()
        db.session.delete(dwl_entry)
        project.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"DWL {dwl_id} deleted from project {project_id}")
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Delete DWL error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to delete DWL entry.'}), 500


@api.route('/project/<int:project_id>/dwl/<int:dwl_id>', methods=['GET'])
@login_required
def get_dwl(project_id, dwl_id):
    """Get a single DWL entry."""
    try:
        Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        dwl_entry = DWLEntry.query.filter_by(id=dwl_id, project_id=project_id).first_or_404()
        return jsonify({
            'success': True,
            'dwl': {
                'id': dwl_entry.id,
                'sequence_number': dwl_entry.sequence_number,
                'dwl_name': dwl_entry.dwl_name,
                'dwl_content': dwl_entry.dwl_content,
                'sample_input': dwl_entry.sample_input,
                'sample_output': dwl_entry.sample_output,
                'source_schema_filename': dwl_entry.source_schema_filename,
                'target_schema_filename': dwl_entry.target_schema_filename,
            }
        })
    except Exception as e:
        logger.error(f"Get DWL error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to retrieve DWL.'}), 500


@api.route('/project/<int:project_id>/dwls', methods=['GET'])
@login_required
def get_dwls(project_id):
    """Get all DWL entries for a project."""
    try:
        Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        dwls = DWLEntry.query.filter_by(project_id=project_id).order_by(DWLEntry.sequence_number).all()
        return jsonify({
            'success': True,
            'dwls': [{
                'id': d.id,
                'sequence_number': d.sequence_number,
                'dwl_name': d.dwl_name,
                'has_source_schema': bool(d.source_schema_content),
                'has_target_schema': bool(d.target_schema_content),
                'has_sample_input': bool(d.sample_input),
                'has_sample_output': bool(d.sample_output),
            } for d in dwls]
        })
    except Exception as e:
        logger.error(f"Get DWLs error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to retrieve DWLs.'}), 500


# ── Mapping Generation ─────────────────────────────────────────────────────

@api.route('/project/<int:project_id>/generate', methods=['POST'])
@login_required
def generate_mapping(project_id):
    """
    Core endpoint: analyze all DWLs via LLM → generate mapping data → produce XLSX.
    """
    try:
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
        dwls = DWLEntry.query.filter_by(project_id=project_id).order_by(DWLEntry.sequence_number).all()

        if not dwls:
            return jsonify({'success': False, 'message': 'No DWL entries found. Please add at least one DWL before generating.'}), 400

        # Build prompt entries — schemas come from project level, not per-DWL
        dwl_entries = [{
            'dwl_name': d.dwl_name,
            'dwl_content': d.dwl_content,
            'sample_input': d.sample_input,
            'sample_output': d.sample_output,
        } for d in dwls]

        prompt = build_dwl_analysis_prompt(
            dwl_entries,
            source_schema=project.source_schema_content,
            source_schema_filename=project.source_schema_filename,
            target_schema=project.target_schema_content,
            target_schema_filename=project.target_schema_filename,
        )
        logger.info(f"Generating mapping for project {project_id} with {len(dwls)} DWL(s)")

        # Create pending result record
        result = MappingResult(project_id=project_id, status='pending')
        db.session.add(result)
        project.status = 'processing'
        db.session.commit()

        # ── LLM Call ───────────────────────────────────────────────────────
        try:
            app_config = {
                'AWS_ACCESS_KEY_ID': current_app.config.get('AWS_ACCESS_KEY_ID'),
                'AWS_SECRET_ACCESS_KEY': current_app.config.get('AWS_SECRET_ACCESS_KEY'),
                'AWS_REGION': current_app.config.get('AWS_REGION'),
                'BEDROCK_ENDPOINT_URL': current_app.config.get('BEDROCK_ENDPOINT_URL'),
                'PRIMARY_MODEL': current_app.config.get('PRIMARY_MODEL'),
                'FALLBACK_MODEL': current_app.config.get('FALLBACK_MODEL'),
            }
            raw_response, model_used = call_llm_with_fallback(prompt, app_config, max_tokens=4096)
            logger.info(f"LLM response received, model: {model_used}, length: {len(raw_response)}")

        except Exception as llm_error:
            logger.error(f"LLM call failed for project {project_id}: {llm_error}", exc_info=True)
            result.status = 'error'
            result.error_message = f"LLM call failed: {str(llm_error)}"
            project.status = 'error'
            db.session.commit()
            return jsonify({'success': False, 'message': f'LLM generation failed: {str(llm_error)}'}), 500

        # ── Parse LLM Response ─────────────────────────────────────────────
        mapping_data = parse_llm_mapping_response(raw_response)
        result.raw_llm_response = raw_response
        result.model_used = model_used
        result.set_mapping_data(mapping_data)

        # ── Generate XLSX ──────────────────────────────────────────────────
        try:
            filename = f"CPI_Mapping_{project.name.replace(' ', '_')}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            output_dir = current_app.config['OUTPUT_FOLDER']
            output_path = os.path.join(output_dir, filename)

            generate_mapping_xlsx(mapping_data, output_path, project.name)
            logger.info(f"XLSX generated: {output_path}")

            result.xlsx_filename = filename
            result.xlsx_path = output_path
            result.status = 'success'
            project.status = 'completed'
            project.updated_at = datetime.utcnow()
            db.session.commit()

        except Exception as xlsx_error:
            logger.error(f"XLSX generation failed: {xlsx_error}", exc_info=True)
            result.status = 'error'
            result.error_message = f"XLSX generation failed: {str(xlsx_error)}"
            project.status = 'error'
            db.session.commit()
            # Still return the mapping data even if XLSX failed
            return jsonify({
                'success': False,
                'message': f'Mapping analysed but XLSX generation failed: {str(xlsx_error)}',
                'mapping_data': mapping_data,
                'result_id': result.id,
            }), 500

        return jsonify({
            'success': True,
            'result_id': result.id,
            'model_used': model_used,
            'mapping_rows_count': len(mapping_data.get('mapping_rows', [])),
            'config_params_count': len(mapping_data.get('config_parameters', [])),
            'xlsx_filename': filename,
            'download_url': f'/api/result/{result.id}/download',
            'summary': mapping_data.get('summary', ''),
        })

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.error(f"Generate mapping error for project {project_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Generation failed: {str(e)}'}), 500


@api.route('/result/<int:result_id>/download')
@login_required
def download_result(result_id):
    """Download the generated XLSX file."""
    try:
        result = MappingResult.query.get_or_404(result_id)
        project = Project.query.filter_by(id=result.project_id, user_id=current_user.id).first_or_404()

        if not result.xlsx_path or not os.path.exists(result.xlsx_path):
            return jsonify({'success': False, 'message': 'XLSX file not found. Please regenerate.'}), 404

        logger.info(f"Download requested: result {result_id} by user {current_user.id}")
        return send_file(
            result.xlsx_path,
            as_attachment=True,
            download_name=result.xlsx_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        logger.error(f"Download error for result {result_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Download failed.'}), 500


@api.route('/result/<int:result_id>')
@login_required
def get_result(result_id):
    """Get mapping result details."""
    try:
        result = MappingResult.query.get_or_404(result_id)
        Project.query.filter_by(id=result.project_id, user_id=current_user.id).first_or_404()

        mapping_data = result.get_mapping_data()
        return jsonify({
            'success': True,
            'result': {
                'id': result.id,
                'project_id': result.project_id,
                'model_used': result.model_used,
                'status': result.status,
                'error_message': result.error_message,
                'xlsx_filename': result.xlsx_filename,
                'created_at': result.created_at.isoformat(),
                'mapping_rows_count': len(mapping_data.get('mapping_rows', [])),
                'summary': mapping_data.get('summary', ''),
                'mapping_data': mapping_data,
                'download_url': f'/api/result/{result.id}/download' if result.xlsx_filename else None,
            }
        })
    except Exception as e:
        logger.error(f"Get result error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Failed to retrieve result.'}), 500
