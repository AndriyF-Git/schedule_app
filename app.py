from dotenv import load_dotenv
import os
import logging
from pythonjsonlogger import jsonlogger
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from random import shuffle
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('APP_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///schedule.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
ADMIN_PIN = os.getenv('ADMIN_PIN')

# --- Налаштування JSON логування ---
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger('schedule_app')
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler('logs/app.log')
file_handler.setFormatter(jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
logger.addHandler(file_handler)

@app.after_request
def log_request(response):
    logger.info('request', extra={
        'method': request.method,
        'path': request.path,
        'status': response.status_code,
        'ip': request.remote_addr,
    })
    return response



# Дні тижня та часові слоти для генерації
DAYS = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', 'П’ятниця']
TIMES = ['9:00 - 10:30', '10:45 - 12:15', '12:30 - 14:00', '14:15 - 15:45', '16:00 - 17:30']


# --- 2. Декоратор Авторизації ---

def admin_required(f):
    """Декоратор для захисту адміністративних маршрутів."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('is_admin_logged_in') != True:
            flash('Вам необхідно увійти для доступу до цієї сторінки.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# --- 3. Моделі Бази Даних ---

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    schedule = db.relationship('Schedule', backref='subject', lazy=True)
    load = db.relationship('CourseLoad', backref='subject', lazy=True)

class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    schedule = db.relationship('Schedule', backref='teacher', lazy=True)
    load = db.relationship('CourseLoad', backref='teacher', lazy=True)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    load = db.relationship('CourseLoad', backref='group', lazy=True)

class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    capacity = db.Column(db.Integer, default=30) 

class CourseLoad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    required_sessions = db.Column(db.Integer, nullable=False) 

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(20), nullable=False)
    classroom = db.Column(db.String(50), nullable=False) 
    group_name = db.Column(db.String(50), nullable=False) 

    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)

# Створення таблиць при першому запуску
with app.app_context():
    db.create_all()


# --- 4. Функція Генерації Розкладу (Алгоритм) ---

def run_schedule_generation():
    """Простий жадібний алгоритм для генерації розкладу."""
    
    Schedule.query.delete()
    db.session.commit() # Очищаємо старий розклад одразу
    
    course_loads = CourseLoad.query.all()
    classrooms = Classroom.query.all()
    
    resource_availability = {} 
    
    all_time_slots = []
    for day in DAYS:
        for time in TIMES:
            all_time_slots.append({'day': day, 'time': time})

    new_schedule_entries = []
    unassigned_loads = 0
    
    for load in course_loads:
        for _ in range(load.required_sessions):
            
            shuffle(all_time_slots) 
            assigned = False
            
            for slot in all_time_slots:
                day_time_key = f"{slot['day']}_{slot['time']}"
                
                # Перевірка Обмежень
                teacher_free = load.teacher_id not in resource_availability.get(day_time_key, {}).get('teacher', [])
                group_free = load.group_id not in resource_availability.get(day_time_key, {}).get('group', [])
                
                occupied_room_ids = resource_availability.get(day_time_key, {}).get('classroom', [])
                available_rooms = [r for r in classrooms if r.id not in occupied_room_ids]
                
                if teacher_free and group_free and available_rooms:
                    
                    chosen_room = available_rooms[0]
                    
                    new_entry = Schedule(
                        day=slot['day'],
                        time=slot['time'],
                        classroom=chosen_room.name, 
                        group_name=load.group.name, 
                        subject_id=load.subject_id,
                        teacher_id=load.teacher_id
                    )
                    new_schedule_entries.append(new_entry)
                    
                    if day_time_key not in resource_availability:
                         resource_availability[day_time_key] = {'teacher': [], 'group': [], 'classroom': []}
                         
                    resource_availability[day_time_key]['teacher'].append(load.teacher_id)
                    resource_availability[day_time_key]['group'].append(load.group_id)
                    resource_availability[day_time_key]['classroom'].append(chosen_room.id)
                    
                    assigned = True
                    break 

            if not assigned:
                unassigned_loads += 1
                
    db.session.add_all(new_schedule_entries)
    db.session.commit()
    
    return len(new_schedule_entries), unassigned_loads


# --- 5. Маршрути Клієнтської Частини ---

@app.route('/')
@app.route('/schedule', methods=['GET'])
def view_schedule():
    """Відображення розкладу з можливістю фільтрації за групою, дисципліною або викладачем."""
    
    # 1. Отримання параметрів фільтрації з URL-запиту
    selected_group_name = request.args.get('group')
    selected_subject_name = request.args.get('subject') 
    selected_teacher_name = request.args.get('teacher') # <-- НОВИЙ ПАРАМЕТР

    # 2. Отримання списку всіх ресурсів для випадаючих меню
    all_groups = Group.query.order_by(Group.name).all()
    all_subjects = Subject.query.order_by(Subject.name).all()
    all_teachers = Teacher.query.order_by(Teacher.name).all() # <-- НОВИЙ СПИСОК

    # 3. Формування запиту до бази даних
    query = Schedule.query
    
    if selected_group_name and selected_group_name != 'all':
        query = query.filter(Schedule.group_name == selected_group_name)

    if selected_subject_name and selected_subject_name != 'all':
        subject_obj = Subject.query.filter_by(name=selected_subject_name).first()
        if subject_obj:
            query = query.filter(Schedule.subject_id == subject_obj.id)
        else:
            selected_subject_name = None 

    # 4. ЛОГІКА ФІЛЬТРАЦІЇ ЗА ВИКЛАДАЧЕМ
    if selected_teacher_name and selected_teacher_name != 'all':
        # Знаходимо ID викладача за назвою
        teacher_obj = Teacher.query.filter_by(name=selected_teacher_name).first()
        if teacher_obj:
            query = query.filter(Schedule.teacher_id == teacher_obj.id)
        else:
            selected_teacher_name = None

    # 5. Виконання запиту та сортування
    all_schedule = query.order_by(Schedule.day, Schedule.time).all()
    
    # 6. Групування розкладу за днями
    schedule_by_day = {}
    for entry in all_schedule:
        if entry.day not in schedule_by_day:
            schedule_by_day[entry.day] = []
        schedule_by_day[entry.day].append(entry)
        
    ordered_days = DAYS 

    # 7. Передача даних до шаблону
    return render_template('student/view_schedule.html', 
                           schedule_by_day=schedule_by_day, 
                           ordered_days=ordered_days,
                           all_groups=all_groups,
                           all_subjects=all_subjects,
                           all_teachers=all_teachers, # <-- Передаємо список викладачів
                           selected_group_name=selected_group_name,
                           selected_subject_name=selected_subject_name,
                           selected_teacher_name=selected_teacher_name # <-- Передаємо обраного викладача
                          )


# --- 6. Маршрути Авторизації ---

@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        pin_code = request.form.get('pin_code')
        
        if pin_code == ADMIN_PIN:
            session['is_admin_logged_in'] = True
            flash('Ви успішно увійшли як адміністратор!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Неправильний код підтвердження. Спробуйте ще раз.', 'error')
            
    return render_template('admin/admin_login.html')

@app.route('/logout')
def admin_logout():
    session.pop('is_admin_logged_in', None)
    flash('Ви вийшли з системи.', 'info')
    return redirect(url_for('view_schedule'))


# --- 7. Маршрути Адміністративної Частини (Захищені) ---

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Адміністративна головна сторінка."""
    subjects = Subject.query.all()
    teachers = Teacher.query.all()
    schedule_entries = Schedule.query.order_by(Schedule.day, Schedule.time).all()
    
    return render_template('admin/admin_dashboard.html', 
                           subjects=subjects, 
                           teachers=teachers,
                           schedule_entries=schedule_entries)


@app.route('/admin/resources')
@admin_required
def manage_resources():
    """Сторінка керування Групами, Аудиторіями та Навантаженням."""
    groups = Group.query.all()
    classrooms = Classroom.query.all()
    subjects = Subject.query.all()
    teachers = Teacher.query.all()
    course_loads = CourseLoad.query.all()
    
    return render_template('admin/manage_resources.html',
                           groups=groups,
                           classrooms=classrooms,
                           subjects=subjects,
                           teachers=teachers,
                           course_loads=course_loads)

# --- Маршрути Додавання Ресурсів (Захищені) ---

@app.route('/admin/subject/add', methods=['POST'])
@admin_required
def add_subject():
    name = request.form.get('name')
    if name:
        try:
            db.session.add(Subject(name=name))
            db.session.commit()
            flash(f'Дисципліна "{name}" успішно додана!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Помилка: Дисципліна з такою назвою вже існує.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/teacher/add', methods=['POST'])
@admin_required
def add_teacher():
    name = request.form.get('name')
    if name:
        try:
            db.session.add(Teacher(name=name))
            db.session.commit()
            flash(f'Викладач "{name}" успішно доданий!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Помилка: Викладач з таким іменем вже існує.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/group/add', methods=['POST'])
@admin_required
def add_group():
    name = request.form.get('name')
    if name:
        try:
            db.session.add(Group(name=name))
            db.session.commit()
            flash(f'Група "{name}" успішно додана!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Помилка: Група з такою назвою вже існує.', 'error')
    return redirect(url_for('manage_resources'))

@app.route('/admin/classroom/add', methods=['POST'])
@admin_required
def add_classroom():
    name = request.form.get('name')
    capacity = request.form.get('capacity')
    if name:
        try:
            db.session.add(Classroom(name=name, capacity=capacity))
            db.session.commit()
            flash(f'Аудиторія "{name}" успішно додана!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Помилка: Аудиторія з такою назвою вже існує.', 'error')
    return redirect(url_for('manage_resources'))

@app.route('/admin/load/add', methods=['POST'])
@admin_required
def add_course_load():
    try:
        new_load = CourseLoad(
            group_id=request.form['group_id'],
            subject_id=request.form['subject_id'],
            teacher_id=request.form['teacher_id'],
            required_sessions=request.form['required_sessions']
        )
        db.session.add(new_load)
        db.session.commit()
        flash('Навантаження успішно додано!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Помилка при додаванні навантаження: {e}', 'error')
    return redirect(url_for('manage_resources'))

# --- Маршрути Розкладу (Захищені) ---

@app.route('/admin/schedule/delete/<int:entry_id>', methods=['POST'])
@admin_required
def delete_schedule_entry(entry_id):
    entry = Schedule.query.get_or_404(entry_id)
    try:
        db.session.delete(entry)
        db.session.commit()
        flash('Запис розкладу успішно видалено.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Помилка при видаленні запису: {e}', 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/generate_schedule', methods=['POST'])
@admin_required
def generate_schedule():
    """Запускає алгоритм генерації розкладу."""
    try:
        with app.app_context():
            total_assigned, total_unassigned = run_schedule_generation()

        if total_assigned > 0:
            flash(f'✅ Автоматична генерація завершена. Успішно заплановано {total_assigned} занять.', 'success')
        else:
            flash(f'⚠️ Помилка генерації: Не вдалося запланувати жодного заняття. Перевірте, чи додані ресурси та навантаження.', 'error')
        
        if total_unassigned > 0:
            flash(f'❗ Увага: {total_unassigned} занять НЕ вдалося розмістити через конфлікти ресурсів (час, викладач, аудиторія).', 'warning')

    except Exception as e:
        flash(f'Критична помилка під час генерації: {e}', 'error')
        
    return redirect(url_for('view_schedule'))


# --- 8. Запуск Застосунку ---

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)