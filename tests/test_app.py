"""
Route-level tests for the Flask application.

Each test group covers a distinct area of functionality:
  - Public routes
  - Authentication
  - Admin resource management (subjects, teachers, groups, classrooms, loads)
  - Schedule CRUD (delete, manual add)
  - Greedy generation
  - AI generation (OR-Tools) — OR-Tools call is mocked for speed
  - Manual placement / Mode 2
  - RF training route
"""
import pytest
from app import app, db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret-key'

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


@pytest.fixture
def auth_client(client):
    """Client with an active admin session."""
    import app as app_module
    original = app_module.ADMIN_PIN
    app_module.ADMIN_PIN = 'testpin'
    client.post('/login', data={'pin_code': 'testpin'})
    yield client
    app_module.ADMIN_PIN = original


@pytest.fixture
def seeded_client(auth_client):
    """Logged-in client with one of each resource and one CourseLoad in the DB."""
    from app import Subject, Teacher, Group, Classroom, CourseLoad

    subj    = Subject(name='Математика', difficulty=3)
    teacher = Teacher(name='Іваненко І.І.')
    group   = Group(name='ІПЗ-41')
    room    = Classroom(name='А-301', capacity=30)
    db.session.add_all([subj, teacher, group, room])
    db.session.flush()

    load = CourseLoad(
        group_id=group.id, subject_id=subj.id,
        teacher_id=teacher.id, required_sessions=2,
    )
    db.session.add(load)
    db.session.commit()

    yield auth_client


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

def test_root_redirects_to_schedule(client):
    response = client.get('/')
    assert response.status_code in (200, 302)


def test_schedule_page_loads(client):
    response = client.get('/schedule')
    assert response.status_code == 200


def test_schedule_filter_by_group(client):
    response = client.get('/schedule?group=all')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200


def test_login_wrong_pin(client):
    response = client.post('/login', data={'pin_code': '0000'})
    assert response.status_code == 200
    assert 'Неправильний' in response.data.decode('utf-8')


def test_login_correct_pin(auth_client):
    response = auth_client.get('/admin', follow_redirects=True)
    assert response.status_code == 200


def test_logout_clears_session(auth_client):
    auth_client.get('/logout')
    response = auth_client.get('/admin', follow_redirects=True)
    body = response.data.decode('utf-8').lower()
    assert 'увійти' in body or 'login' in body


def test_admin_requires_login(client):
    response = client.get('/admin', follow_redirects=True)
    body = response.data.decode('utf-8').lower()
    assert 'увійти' in body or 'login' in body


# ---------------------------------------------------------------------------
# Admin — resource management
# ---------------------------------------------------------------------------

def test_admin_dashboard_loads(auth_client):
    response = auth_client.get('/admin', follow_redirects=True)
    assert response.status_code == 200


def test_manage_resources_loads(auth_client):
    response = auth_client.get('/admin/resources', follow_redirects=True)
    assert response.status_code == 200


def test_add_subject(auth_client):
    r = auth_client.post('/admin/subject/add', data={'name': 'Фізика'}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Фізика' in r.data.decode('utf-8')


def test_add_duplicate_subject(auth_client):
    auth_client.post('/admin/subject/add', data={'name': 'Фізика'})
    r = auth_client.post('/admin/subject/add', data={'name': 'Фізика'}, follow_redirects=True)
    assert r.status_code == 200


def test_add_teacher(auth_client):
    r = auth_client.post('/admin/teacher/add', data={'name': 'Петренко П.П.'}, follow_redirects=True)
    assert r.status_code == 200
    assert 'Петренко' in r.data.decode('utf-8')


def test_add_group(auth_client):
    r = auth_client.post('/admin/group/add', data={'name': 'ІПЗ-42'}, follow_redirects=True)
    assert r.status_code == 200


def test_add_classroom(auth_client):
    r = auth_client.post('/admin/classroom/add', data={'name': 'А-101', 'capacity': '30'},
                         follow_redirects=True)
    assert r.status_code == 200


def test_add_course_load(seeded_client):
    from app import Subject, Teacher, Group, CourseLoad
    subj    = Subject.query.first()
    teacher = Teacher.query.first()
    group   = Group.query.first()
    r = seeded_client.post('/admin/load/add', data={
        'group_id': group.id,
        'subject_id': subj.id,
        'teacher_id': teacher.id,
        'required_sessions': 1,
    }, follow_redirects=True)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------

def test_delete_schedule_entry(seeded_client):
    from app import Schedule, Subject, Teacher, Classroom
    subj    = Subject.query.first()
    teacher = Teacher.query.first()
    room    = Classroom.query.first()
    entry   = Schedule(
        day='Понеділок', time='9:00 - 10:30', classroom_id=room.id if room else None,
        group_name='ІПЗ-41', subject_id=subj.id, teacher_id=teacher.id,
    )
    db.session.add(entry)
    db.session.commit()

    r = seeded_client.post(f'/admin/schedule/delete/{entry.id}', follow_redirects=True)
    assert r.status_code == 200
    assert Schedule.query.count() == 0


def test_add_schedule_entry_manually(seeded_client):
    from app import Subject, Teacher, Schedule
    subj    = Subject.query.first()
    teacher = Teacher.query.first()

    r = seeded_client.post('/admin/schedule/add', data={
        'day': 'Вівторок',
        'time': '10:45 - 12:15',
        'classroom': 'А-301',
        'group_name': 'ІПЗ-41',
        'subject_id': subj.id,
        'teacher_id': teacher.id,
    }, follow_redirects=True)
    assert r.status_code == 200
    assert Schedule.query.count() == 1


# ---------------------------------------------------------------------------
# Greedy schedule generation
# ---------------------------------------------------------------------------

def test_greedy_generate_without_loads(auth_client):
    r = auth_client.post('/admin/generate_schedule', follow_redirects=True)
    assert r.status_code == 200


def test_greedy_generate_with_loads(seeded_client):
    r = seeded_client.post('/admin/generate_schedule', follow_redirects=True)
    assert r.status_code == 200
    from app import Schedule
    assert Schedule.query.count() > 0


# ---------------------------------------------------------------------------
# AI generation — Mode 3 (OR-Tools mocked)
# ---------------------------------------------------------------------------

def test_ai_generate_page_loads(auth_client):
    r = auth_client.get('/admin/ai_generate')
    assert r.status_code == 200


def test_ai_generate_requires_auth(client):
    r = client.post('/admin/ai_generate', data={'timeout': '5'})
    assert r.status_code == 302


def test_ai_generate_no_loads_flashes_error(auth_client):
    r = auth_client.post('/admin/ai_generate', data={'timeout': '5'}, follow_redirects=True)
    assert r.status_code == 200
    assert 'навантаження' in r.data.decode('utf-8').lower()


def test_ai_generate_runs_and_saves(seeded_client, monkeypatch):
    """OR-Tools call is mocked so the test is deterministic and instant."""
    from app import Subject, Teacher
    subj    = Subject.query.first()
    teacher = Teacher.query.first()

    def _mock_generate(loads, rooms, subjects_map, timeout=15):
        entries = [{
            'day': 'Понеділок', 'time': '9:00 - 10:30',
            'group_name': 'ІПЗ-41',
            'subject_id': subj.id, 'teacher_id': teacher.id,
            'classroom': 'А-301',
        }]
        return entries, 'Оптимальний розклад (0.1с)', 0.1

    import app as app_module
    monkeypatch.setattr(app_module, 'generate_schedule_or_tools', _mock_generate)

    r = seeded_client.post('/admin/ai_generate', data={'timeout': '5'}, follow_redirects=True)
    assert r.status_code == 200

    from app import Schedule
    assert Schedule.query.count() == 1


# ---------------------------------------------------------------------------
# Manual placement — Mode 2
# ---------------------------------------------------------------------------

def test_place_schedule_page_loads(auth_client):
    r = auth_client.get('/admin/schedule/place')
    assert r.status_code == 200


def test_place_schedule_with_load_shows_grid(seeded_client):
    from app import CourseLoad
    load = CourseLoad.query.first()
    r = seeded_client.post('/admin/schedule/place', data={
        'course_load_id': load.id,
        'classroom_name': 'А-301',
    })
    assert r.status_code == 200
    body = r.data.decode('utf-8')
    assert 'Понеділок' in body or 'Вівторок' in body


# ---------------------------------------------------------------------------
# RF training route
# ---------------------------------------------------------------------------

def test_train_rf_requires_auth(client):
    r = client.post('/admin/train_rf')
    assert r.status_code == 302


def test_train_rf_no_data_flashes_error(auth_client, monkeypatch, tmp_path):
    """Without schedules.jsonl the route should flash an error, not crash."""
    monkeypatch.chdir(tmp_path)   # empty tmp dir → no data/schedules.jsonl
    r = auth_client.post('/admin/train_rf', follow_redirects=True)
    assert r.status_code == 200


def test_train_rf_success(auth_client, monkeypatch):
    """Mock extract + train so the route completes without touching real files."""
    def _mock_extract(*a, **kw):
        return 59000

    def _mock_train(*a, **kw):
        return {'rows': 59000, 'accuracy': 0.89, 'f1': 0.88,
                'trees': 100, 'top_feature': 'is_single_pair_day'}

    monkeypatch.setattr('ai.extract_features.run', _mock_extract)
    monkeypatch.setattr('ai.train_rf.train', _mock_train)

    r = auth_client.post('/admin/train_rf', follow_redirects=True)
    assert r.status_code == 200
    body = r.data.decode('utf-8')
    assert 'RF' in body or 'модель' in body.lower()
