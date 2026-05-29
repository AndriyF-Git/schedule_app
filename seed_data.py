# TAG v1.0: Test data seeder for ML training
# Populates the database with a realistic Ukrainian IT-faculty dataset.
# Run from schedule_app/ directory:
#   python seed_data.py
# To re-seed: delete instance/schedule.db first, then run again.

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, Subject, Teacher, Group, Classroom, CourseLoad

SUBJECTS = [
    'Математичний аналіз',
    'Лінійна алгебра',
    'Фізика',
    'Алгоритми та структури даних',
    'Бази даних',
    'Програмування (Python)',
    'Комп\'ютерні мережі',
    'Операційні системи',
    'Дискретна математика',
    'Англійська мова',
]

TEACHERS = [
    'Іваненко О.В.',
    'Петренко І.С.',
    'Сидоренко Л.М.',
    'Коваль М.П.',
    'Шевченко Т.Г.',
    'Бойко В.І.',
    'Мельник О.О.',
    'Ткаченко Р.Д.',
]

GROUPS = [
    'ІПЗ-41',
    'ІПЗ-42',
    'ІПЗ-43',
    'ПМ-31',
    'КН-21',
]

# (name, capacity)
CLASSROOMS = [
    ('Ауд. 101', 35),
    ('Ауд. 205', 60),
    ('Ауд. 308', 25),
    ('Комп. зал 1', 20),
    ('Комп. зал 2', 20),
    ('Ауд. 412', 80),
]

# (group, subject, teacher, required_sessions)
# Notes:
#   - Англійська мова = 1 session → forces H3 violation (unavoidable, tests normalisation)
#   - Шевченко has 4 sessions for КН-21 across two subjects → high teacher load day
#   - Сидоренко teaches two subjects for ПМ-31 → 5 sessions total
LOADS = [
    # ІПЗ-41 — total: 12 sessions
    ('ІПЗ-41', 'Алгоритми та структури даних', 'Іваненко О.В.',  3),
    ('ІПЗ-41', 'Бази даних',                   'Петренко І.С.',  2),
    ('ІПЗ-41', 'Математичний аналіз',           'Сидоренко Л.М.', 2),
    ('ІПЗ-41', 'Комп\'ютерні мережі',           'Шевченко Т.Г.', 2),
    ('ІПЗ-41', 'Програмування (Python)',        'Бойко В.І.',    2),
    ('ІПЗ-41', 'Англійська мова',               'Коваль М.П.',   1),  # forced H3

    # ІПЗ-42 — total: 12 sessions
    ('ІПЗ-42', 'Алгоритми та структури даних', 'Іваненко О.В.',  3),
    ('ІПЗ-42', 'Бази даних',                   'Петренко І.С.',  2),
    ('ІПЗ-42', 'Лінійна алгебра',              'Сидоренко Л.М.', 2),
    ('ІПЗ-42', 'Операційні системи',           'Мельник О.О.',  2),
    ('ІПЗ-42', 'Дискретна математика',         'Ткаченко Р.Д.', 2),
    ('ІПЗ-42', 'Англійська мова',              'Коваль М.П.',   1),  # forced H3

    # ІПЗ-43 — total: 12 sessions
    ('ІПЗ-43', 'Програмування (Python)',        'Бойко В.І.',    3),
    ('ІПЗ-43', 'Дискретна математика',         'Ткаченко Р.Д.', 2),
    ('ІПЗ-43', 'Фізика',                       'Іваненко О.В.', 2),
    ('ІПЗ-43', 'Комп\'ютерні мережі',          'Шевченко Т.Г.', 2),
    ('ІПЗ-43', 'Бази даних',                   'Петренко І.С.', 2),
    ('ІПЗ-43', 'Англійська мова',              'Коваль М.П.',   1),  # forced H3

    # ПМ-31 — total: 11 sessions (Сидоренко: 5 sessions across 2 subjects)
    ('ПМ-31', 'Математичний аналіз',            'Сидоренко Л.М.', 3),
    ('ПМ-31', 'Лінійна алгебра',               'Сидоренко Л.М.', 2),
    ('ПМ-31', 'Фізика',                        'Іваненко О.В.',  2),
    ('ПМ-31', 'Програмування (Python)',         'Мельник О.О.',  2),
    ('ПМ-31', 'Дискретна математика',          'Ткаченко Р.Д.', 2),

    # КН-21 — total: 12 sessions (Шевченко: 4 sessions across 2 subjects)
    ('КН-21', 'Алгоритми та структури даних',  'Іваненко О.В.',  3),
    ('КН-21', 'Операційні системи',            'Мельник О.О.',  2),
    ('КН-21', 'Бази даних',                    'Шевченко Т.Г.', 2),
    ('КН-21', 'Комп\'ютерні мережі',           'Шевченко Т.Г.', 2),
    ('КН-21', 'Лінійна алгебра',               'Ткаченко Р.Д.', 2),
    ('КН-21', 'Англійська мова',               'Коваль М.П.',   1),  # forced H3
]


def seed():
    with app.app_context():
        if Subject.query.count() > 0:
            print('Database already contains data.')
            print('To re-seed: delete instance/schedule.db and run this script again.')
            return

        print('Seeding subjects...')
        subjects = {name: Subject(name=name) for name in SUBJECTS}
        db.session.add_all(subjects.values())

        print('Seeding teachers...')
        teachers = {name: Teacher(name=name) for name in TEACHERS}
        db.session.add_all(teachers.values())

        print('Seeding groups...')
        groups = {name: Group(name=name) for name in GROUPS}
        db.session.add_all(groups.values())

        print('Seeding classrooms...')
        classrooms = [Classroom(name=name, capacity=cap) for name, cap in CLASSROOMS]
        db.session.add_all(classrooms)

        db.session.commit()

        print('Seeding course loads...')
        for group_name, subject_name, teacher_name, sessions in LOADS:
            db.session.add(CourseLoad(
                group_id=groups[group_name].id,
                subject_id=subjects[subject_name].id,
                teacher_id=teachers[teacher_name].id,
                required_sessions=sessions,
            ))

        db.session.commit()

        total_sessions = sum(s for *_, s in LOADS)
        print(f'\nDone! Seeded:')
        print(f'  {len(SUBJECTS)} subjects')
        print(f'  {len(TEACHERS)} teachers')
        print(f'  {len(GROUPS)} groups')
        print(f'  {len(CLASSROOMS)} classrooms')
        print(f'  {len(LOADS)} course loads ({total_sessions} total pairs to schedule)')
        print(f'\nForced H3 violations (1-session English): 4 groups × 1 = 4')
        print('Run the app and use Generate Schedule to populate the schedule table.')


if __name__ == '__main__':
    seed()
