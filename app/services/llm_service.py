"""
LLM Service — handles AWS Bedrock API calls for DWL analysis.
Supports primary + fallback model strategy with structured prompt engineering.
"""
import json
import logging
import time
import requests
from datetime import datetime, timezone
from typing import Optional
from flask import current_app

logger = logging.getLogger(__name__)


def _get_bedrock_headers(app_config: dict, payload_bytes: bytes, endpoint_url: str) -> dict:
    """Build AWS SigV4 signed headers for Bedrock invoke."""
    try:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials

        creds = Credentials(
            access_key=app_config.get('AWS_ACCESS_KEY_ID', ''),
            secret_key=app_config.get('AWS_SECRET_ACCESS_KEY', ''),
        )
        region = app_config.get('AWS_REGION', 'us-east-1')

        aws_request = AWSRequest(
            method='POST',
            url=endpoint_url,
            data=payload_bytes,
            headers={'Content-Type': 'application/json'}
        )
        SigV4Auth(creds, 'bedrock', region).add_auth(aws_request)
        return dict(aws_request.headers)
    except Exception as e:
        logger.warning(f"SigV4 signing failed, using x-api-key fallback: {e}")
        # Fallback: your gateway may use x-api-key instead of SigV4
        return {
            'Content-Type': 'application/json',
            'x-api-key': app_config.get('AWS_SECRET_ACCESS_KEY', ''),
        }


def call_bedrock_model(prompt: str, model_id: str, app_config: dict, max_tokens: int = 4096) -> Optional[str]:
    """
    Call a single Bedrock model. Returns the text response or raises an exception.
    """
    base_url = app_config.get('BEDROCK_ENDPOINT_URL', '').rstrip('/')
    endpoint_url = f"{base_url}/model/{model_id}/invoke"

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    headers = _get_bedrock_headers(app_config, payload_bytes, endpoint_url)

    logger.info(f"Calling Bedrock model: {model_id}")
    start = time.time()

    response = requests.post(endpoint_url, headers=headers, data=payload_bytes, timeout=120)
    elapsed = time.time() - start

    logger.info(f"Bedrock response: status={response.status_code}, time={elapsed:.2f}s, model={model_id}")

    if response.status_code != 200:
        logger.error(f"Bedrock error {response.status_code}: {response.text[:500]}")
        response.raise_for_status()

    data = response.json()
    content_blocks = data.get('content', [])
    text = ''.join(b.get('text', '') for b in content_blocks if b.get('type') == 'text')
    logger.info(f"Bedrock response tokens — input: {data.get('usage', {}).get('input_tokens')}, output: {data.get('usage', {}).get('output_tokens')}")
    return text


def call_llm_with_fallback(prompt: str, app_config: dict, max_tokens: int = 4096) -> tuple[str, str]:
    """
    Try primary model, fall back to secondary on failure.
    Returns (response_text, model_id_used).
    """
    primary = app_config.get('PRIMARY_MODEL', 'us.anthropic.claude-sonnet-4-20250514-v1:0')
    fallback = app_config.get('FALLBACK_MODEL', 'us.anthropic.claude-3-5-sonnet-20241022-v2:0')

    for model_id in [primary, fallback]:
        try:
            text = call_bedrock_model(prompt, model_id, app_config, max_tokens)
            logger.info(f"Successfully got response from {model_id}")
            return text, model_id
        except Exception as e:
            logger.warning(f"Model {model_id} failed: {e}")
            if model_id == fallback:
                raise

    raise RuntimeError("All LLM models failed.")


def build_dwl_analysis_prompt(
    dwl_entries: list,
    source_schema: str = None,
    source_schema_filename: str = None,
    target_schema: str = None,
    target_schema_filename: str = None,
) -> str:
    """
    Build a structured prompt for the LLM to analyze multiple DWL scripts
    and produce a CPI mapping sheet.
    Schemas are project-level: source = CPI input structure, target = CPI output structure.
    """

    # ── Schema block (once, at the top) ───────────────────────────────────
    schema_block = ""
    if source_schema:
        fname = f" ({source_schema_filename})" if source_schema_filename else ""
        schema_block += f"""
=== CPI MAPPING INPUT STRUCTURE — Source XSD/WSDL{fname} ===
This defines the overall INPUT payload structure that enters the SAP CPI mapping.
{source_schema[:4000]}
"""
    if target_schema:
        fname = f" ({target_schema_filename})" if target_schema_filename else ""
        schema_block += f"""
=== CPI MAPPING OUTPUT STRUCTURE — Target XSD/WSDL{fname} ===
This defines the overall OUTPUT payload structure that exits the SAP CPI mapping.
{target_schema[:4000]}
"""

    # ── DWL sections ──────────────────────────────────────────────────────
    dwl_sections = []
    for i, entry in enumerate(dwl_entries, 1):
        section = f"""
=== DWL Step #{i}: {entry.get('dwl_name', f'Step {i}')} ===

--- DataWeave Script ---
{entry.get('dwl_content', '(not provided)')}
"""
        if entry.get('sample_input'):
            section += f"""
--- Sample Input Payload (Step {i}) ---
{entry.get('sample_input', '')[:2000]}
"""
        if entry.get('sample_output'):
            section += f"""
--- Sample Output Payload (Step {i}) ---
{entry.get('sample_output', '')[:2000]}
"""
        dwl_sections.append(section)

    all_dwls = '\n'.join(dwl_sections)

    prompt = f"""You are an expert SAP CPI integration architect and MuleSoft migration specialist.

TASK: Analyze the following MuleSoft DataWeave (DWL) transformation script(s) and produce a comprehensive CPI Message Mapping Sheet in JSON format.

CONTEXT:
- We are migrating APIs from MuleSoft to SAP CPI (Cloud Platform Integration).
- MuleSoft uses DataWeave (DWL) for payload transformation across multiple steps.
- SAP CPI uses a single Graphical Message Mapping to handle the full transformation.
- ALL DWL steps below must be combined into ONE unified CPI mapping.
- The Source XSD defines the INPUT structure of the CPI mapping (what comes in).
- The Target XSD defines the OUTPUT structure of the CPI mapping (what goes out).
- The DWL scripts describe the intermediate transformation logic to achieve this.

{schema_block}

{all_dwls}

INSTRUCTIONS:
Analyse every field transformation across all DWL steps and produce a complete mapping sheet.
Use the Source XSD as the authoritative reference for source field paths and data types.
Use the Target XSD as the authoritative reference for target field names, segments, and data types.
For EACH target field, identify:
1. The target segment/element path (from Target XSD)
2. The target field name
3. A short field description
4. Data type (CHAR, NUM, DATE, etc.)
5. Max length if determinable from XSD
6. The source field path (from Source XSD, or "—" if hardcoded/config)
7. The mapping logic — one of:
   - "Pass-through" (direct 1:1 copy)
   - "Hardcoded: <value>" (fixed constant)
   - "Config Property" (from config/property file)
   - "Transformation: <clear English description of logic>"
   - "Conditional: <condition description>"
8. Config property key (if applicable, from p('...') calls in DWL)
9. Notes/CPI Guidance — practical notes for implementing in SAP CPI Graphical Mapping

MAPPING TYPE LEGEND:
- 🟡 Fixed/Hardcoded Value
- 🟢 Direct Pass-Through (1:1 copy)
- 🟠 Transformation / Logic
- ⚙️ Config Property (externalized parameter)
- ⚠️ Conditional / Complex Logic

OUTPUT FORMAT:
Return ONLY a valid JSON object — NO markdown, NO code fences, NO explanation outside the JSON.
The JSON must have this exact structure:

{{
  "summary": "Brief description of what this mapping does overall",
  "source_system": "Detected source system name",
  "target_system": "Detected target system name",
  "mapping_rows": [
    {{
      "segment": "Segment or parent element name",
      "target_field": "Field name in target",
      "field_description": "Human-readable description",
      "type": "CHAR|NUM|DATE|BOOL|etc",
      "length": "max length or empty string",
      "source_field": "Source path or —",
      "mapping_logic": "Pass-through|Hardcoded: X|Transformation: ...|Conditional: ...|Config Property",
      "mapping_type": "passthrough|hardcoded|transformation|conditional|config",
      "config_property": "property.key or empty string",
      "notes": "CPI implementation guidance"
    }}
  ],
  "config_parameters": [
    {{
      "mulesoft_key": "property.key",
      "sample_value": "value if visible in DWL",
      "target_field": "target IDoc/element field",
      "cpi_guidance": "how to set this in CPI"
    }}
  ],
  "cpi_implementation_notes": [
    "General note about CPI implementation"
  ]
}}

Be thorough — include EVERY field from the Target XSD that you can identify a mapping for.
Focus on accuracy and practical CPI guidance.
"""
    return prompt


def parse_llm_mapping_response(raw_response: str) -> dict:
    """
    Parse the LLM JSON response into structured mapping data.
    Handles common formatting issues.
    """
    try:
        # Strip markdown code fences if present
        text = raw_response.strip()
        if text.startswith('```'):
            lines = text.split('\n')
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith('```')]
            text = '\n'.join(lines)

        data = json.loads(text)

        # Validate expected keys
        if 'mapping_rows' not in data:
            logger.warning("LLM response missing 'mapping_rows' key")
            data['mapping_rows'] = []
        if 'config_parameters' not in data:
            data['config_parameters'] = []
        if 'cpi_implementation_notes' not in data:
            data['cpi_implementation_notes'] = []

        logger.info(f"Parsed mapping: {len(data['mapping_rows'])} rows, {len(data['config_parameters'])} config params")
        return data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        logger.debug(f"Raw response (first 500 chars): {raw_response[:500]}")
        # Return minimal structure with raw response preserved
        return {
            'summary': 'Parsing error — see raw response',
            'source_system': '',
            'target_system': '',
            'mapping_rows': [],
            'config_parameters': [],
            'cpi_implementation_notes': [f'JSON parse error: {str(e)}'],
            'raw_response': raw_response
        }
