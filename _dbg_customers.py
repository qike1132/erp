from datetime import timedelta
from fastapi_app.core.auth.token import create_access_token
print(create_access_token({"sub":"23","username":"admin"}, expires_delta=timedelta(hours=1)))