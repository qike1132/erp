import pytest
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_health_check_api(client):
    """测试 /api/health 健康检查接口"""
    response = client.get('/api/health')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data is not None
    assert data.get('status') == 'ok'
    assert data.get('db') == 'connected'
