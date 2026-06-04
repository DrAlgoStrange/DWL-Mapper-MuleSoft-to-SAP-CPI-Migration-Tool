# DWL Mapper — MuleSoft to SAP CPI Migration Tool

A production-grade Flask application that uses AI (AWS Bedrock / Claude) to analyse MuleSoft DataWeave (DWL) scripts and generate professional CPI Mapping Sheets (.xlsx) for SAP CPI Graphical Mapping.

---

## Project Structure

```
dwl_mapper/
├── app/
│   ├── __init__.py             # Application factory
│   ├── config.py               # Dev / Prod / Test configs
│   ├── extensions.py           # DB, Login, Bcrypt instances
│   ├── models.py               # SQLAlchemy models
│   ├── auth/                   # Authentication blueprint
│   ├── main/                   # Core pages blueprint
│   ├── api/                    # REST API blueprint
│   ├── services/
│   │   ├── llm_service.py      # AWS Bedrock LLM calls
│   │   └── excel_service.py    # .xlsx generation (openpyxl)
│   ├── templates/
│   │   ├── base.html
│   │   ├── auth/login.html
│   │   └── main/
│   └── static/
├── tests/
├── .env                        # ← fill this in (not committed)
├── .flaskenv
├── requirements.txt
└── run.py
```

---

## Quick Start

### 1. Clone / unzip and install

```bash
cd dwl_mapper
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

Edit `.env` with your actual values:

```env
SECRET_KEY=your-very-secret-random-key

# AWS Bedrock gateway
BEDROCK_ENDPOINT_URL=https://your-bedrock-gateway.com
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
```

> **Note:** The app uses `x-api-key` header by default (matching your working Bruno setup).  
> If your gateway uses AWS SigV4, it will auto-sign using botocore.

### 3. Run

```bash
flask run
# or
python run.py
```

Open [http://localhost:5000](http://localhost:5000)

---

## How It Works

1. **Register** with your `@its.jnj.com` email.
2. **Create a Project** for each migration interface.
3. **Add DWL Scripts** — paste each DataWeave step, upload source/target XSD/WSDL schemas, and optionally provide sample input/output payloads.
4. **Generate** — the AI analyses all DWL steps together and produces a unified CPI mapping sheet.
5. **Download** the `.xlsx` file and use it to build your SAP CPI Graphical Mapping.

---

## Generated Excel Sheet

The output `.xlsx` contains 3 sheets:

| Sheet | Contents |
|-------|----------|
| **CPI Mapping Sheet** | All field-level mappings with colour-coded types |
| **Config Parameters** | Externalized CPI config properties |
| **CPI Implementation Notes** | Practical guidance for building in CPI |

### Mapping Type Colour Legend

| Colour | Type |
|--------|------|
| 🟢 Green | Direct Pass-Through (1:1 copy) |
| 🟡 Yellow | Fixed/Hardcoded Value |
| 🟠 Orange | Transformation / Logic |
| ⚙️ Blue | Config Property (externalized) |
| ⚠️ Purple | Conditional / Complex Logic |

---


## Running Tests

```bash
pytest tests/ -v
```

---

## Logs

All operations are logged to `logs/app.log` (rotating, 10MB max, 5 backups).  
Check this file if any operation fails — every API call, LLM request, and DB operation is logged.

---

## Security

- Passwords: bcrypt hashed, 8+ chars, uppercase + special char enforced
- Sessions: Flask-Login with secure secret key
- All file uploads validated by extension
- SQL injection protected via SQLAlchemy ORM

---

## Production Deployment

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

Set in `.env`:
```env
FLASK_ENV=production
SECRET_KEY=<very-long-random-string>
DATABASE_URL=postgresql://user:pass@host/dbname   # optional: use PostgreSQL
```
