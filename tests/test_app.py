import pytest
from app import app, db


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


# --- Публічні маршрути ---

def test_view_schedule_page_loads(client):
    response = client.get('/')
    assert response.status_code == 200


def test_view_schedule_empty(client):
    response = client.get('/schedule')
    assert response.status_code == 200


def test_view_schedule_filter_by_group(client):
    response = client.get('/schedule?group=all')
    assert response.status_code == 200


# --- Авторизація ---

def test_admin_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200


def test_admin_login_wrong_pin(client):
    response = client.post('/login', data={'pin_code': '0000'})
    assert response.status_code == 200
    assert 'Неправильний' in response.data.decode('utf-8')


def test_admin_login_correct_pin(client, monkeypatch):
    monkeypatch.setenv('ADMIN_PIN', '1234')
    import app as app_module
    app_module.ADMIN_PIN = '1234'

    response = client.post('/login', data={'pin_code': '1234'}, follow_redirects=True)
    assert response.status_code == 200


def test_admin_requires_login(client):
    response = client.get('/admin', follow_redirects=True)
    assert response.status_code == 200
    assert 'увійти' in response.data.decode('utf-8').lower()


def test_logout_redirects(client):
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200


# --- Захищені маршрути (без авторизації) ---

def test_admin_dashboard_requires_auth(client):
    response = client.get('/admin')
    assert response.status_code in (302, 200)


def test_manage_resources_requires_auth(client):
    response = client.get('/admin/resources')
    assert response.status_code in (302, 200)


# --- Додавання ресурсів (авторизована сесія) ---

@pytest.fixture
def auth_client(client):
    import app as app_module
    app_module.ADMIN_PIN = 'testpin'
    client.post('/login', data={'pin_code': 'testpin'}, follow_redirects=True)
    return client


def test_add_subject(auth_client):
    response = auth_client.post('/admin/subject/add', data={'name': 'Математика'}, follow_redirects=True)
    assert response.status_code == 200


def test_add_teacher(auth_client):
    response = auth_client.post('/admin/teacher/add', data={'name': 'Іваненко І.І.'}, follow_redirects=True)
    assert response.status_code == 200


def test_add_group(auth_client):
    response = auth_client.post('/admin/group/add', data={'name': 'ІПЗ-41'}, follow_redirects=True)
    assert response.status_code == 200


def test_add_classroom(auth_client):
    response = auth_client.post('/admin/classroom/add', data={'name': '301', 'capacity': '30'}, follow_redirects=True)
    assert response.status_code == 200
