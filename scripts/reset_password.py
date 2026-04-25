import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import create_engine, text
from fastapi_app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as conn:
    new_hash = '$argon2id$v=19$m=65536,t=3,p=4$fP4XNulbeIH2QV5U2qc36A$R9DbLrwzzIDwzN+6nT3hI1NNzO/RTMZdjpiHfUYtYcY'
    result = conn.execute(text('UPDATE "user" SET password = :password WHERE username = :username'), {'password': new_hash, 'username': 'admin'})
    conn.commit()
    print(f'Updated {result.rowcount} rows')
    print('Password reset to: admin123')
