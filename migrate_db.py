"""
One-time migration script — adds source/target schema columns to the existing projects table.
Run this ONCE from the project root:  python migrate_db.py
"""
import sqlite3
import os
import glob

# Find the .db file automatically
db_files = glob.glob('*.db') + glob.glob('**/*.db', recursive=True)
db_files = [f for f in db_files if 'venv' not in f and '__pycache__' not in f]

if not db_files:
    print("❌ No .db file found. Make sure you run this from the project root.")
    exit(1)

db_path = db_files[0]
print(f"📂 Found database: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columns_to_add = [
    ("source_schema_filename", "TEXT"),
    ("source_schema_content",  "TEXT"),
    ("target_schema_filename",  "TEXT"),
    ("target_schema_content",   "TEXT"),
]

# Check existing columns
cursor.execute("PRAGMA table_info(projects)")
existing = {row[1] for row in cursor.fetchall()}
print(f"📋 Existing columns: {existing}")

added = []
for col_name, col_type in columns_to_add:
    if col_name not in existing:
        cursor.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}")
        added.append(col_name)
        print(f"  ✅ Added column: {col_name}")
    else:
        print(f"  ⏭️  Already exists: {col_name}")

# Also remove schema columns from dwl_entries if they exist (cleanup)
cursor.execute("PRAGMA table_info(dwl_entries)")
dwl_cols = {row[1] for row in cursor.fetchall()}
dwl_schema_cols = ['source_schema_filename', 'source_schema_content', 'target_schema_filename', 'target_schema_content']
leftover = [c for c in dwl_schema_cols if c in dwl_cols]
if leftover:
    print(f"\n⚠️  Note: dwl_entries still has old schema columns {leftover}")
    print("   SQLite doesn't support DROP COLUMN easily — they'll be ignored by the app.")

conn.commit()
conn.close()

if added:
    print(f"\n✅ Migration complete. Added {len(added)} column(s). Restart Flask now.")
else:
    print("\n✅ Nothing to migrate — all columns already present.")
