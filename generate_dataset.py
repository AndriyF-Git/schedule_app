"""
Generate a JSONL dataset of scored schedules for ML training.

Usage (from schedule_app/ directory):
    python generate_dataset.py
    python generate_dataset.py --runs 500
    python generate_dataset.py --runs 2000 --output data/big_dataset.jsonl

Each JSONL record:
    {
        "run_id": 1,
        "score": 71.2,
        "raw_score": 64,
        "max_achievable": 90,
        "assigned": 59,
        "unassigned": 0,
        "breakdown": {"H1_group_overflow": {"violations": 0, "penalty": 0}, ...},
        "entries": [
            {"day": "Понеділок", "time": "9:00 - 10:30",
             "group_name": "ІПЗ-41", "subject_id": 1, "teacher_id": 2, "classroom": "Ауд. 101"},
            ...
        ]
    }

Database: always uses instance/test.db (never touches schedule.db).
"""
import os
import sys
import json
import argparse
import time
from pathlib import Path

# Set DATABASE_URL before importing app so load_dotenv() inside app.py cannot override it.
os.environ['DATABASE_URL'] = 'sqlite:///test.db'

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, Subject, CourseLoad, Schedule, run_schedule_generation
from ai.scoring import score_schedule


def _entry_to_dict(e, subjects_map=None):
    d = {
        'day': e.day,
        'time': e.time,
        'group_name': e.group_name,
        'subject_id': e.subject_id,
        'teacher_id': e.teacher_id,
        'classroom': e.classroom,
    }
    if subjects_map is not None:
        d['subject_difficulty'] = subjects_map.get(e.subject_id, 2)
    return d


def _ensure_seeded():
    """Seed test.db if it has no data yet."""
    if Subject.query.count() == 0:
        print('test.db is empty — seeding...')
        from seed_data import seed
        seed()
        print()


def _baseline_window_count(subjects_map, course_loads):
    """
    Run greedy once to get the H4 window count used as normalization baseline.
    This count is fixed for all N runs so scores are comparable across runs.
    """
    run_schedule_generation()
    result = score_schedule(
        Schedule.query.all(),
        course_loads=course_loads,
        subjects=subjects_map,
    )
    return result['breakdown']['H4_group_windows']['violations'], result['max_achievable']


def main():
    parser = argparse.ArgumentParser(description='Generate scored schedule dataset (JSONL).')
    parser.add_argument('--runs', type=int, default=1000,
                        help='Number of schedule runs to generate (default: 1000)')
    parser.add_argument('--output', default='data/schedules.jsonl',
                        help='Output file path (default: data/schedules.jsonl)')
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        _ensure_seeded()

        subjects_map = {s.id: s.difficulty for s in Subject.query.all()}
        course_loads = CourseLoad.query.all()

        print('Baseline pass to fix H4 normalization...')
        greedy_window_count, max_achievable = _baseline_window_count(subjects_map, course_loads)
        print(f'  H4 baseline windows : {greedy_window_count}')
        print(f'  max_achievable fixed: {max_achievable}')
        print()

        scores = []
        t_start = time.time()

        print(f'Generating {args.runs} schedules -> {output_path}')
        print('-' * 56)

        with open(output_path, 'w', encoding='utf-8') as f:
            for i in range(1, args.runs + 1):
                assigned, unassigned = run_schedule_generation()
                entries = Schedule.query.all()

                result = score_schedule(
                    entries,
                    course_loads=course_loads,
                    greedy_window_count=greedy_window_count,
                    subjects=subjects_map,
                )

                record = {
                    'run_id': i,
                    'score': result['adjusted_score'],
                    'raw_score': result['raw_score'],
                    'max_achievable': result['max_achievable'],
                    'assigned': assigned,
                    'unassigned': unassigned,
                    'breakdown': result['breakdown'],
                    'entries': [_entry_to_dict(e, subjects_map) for e in entries],
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                scores.append(result['adjusted_score'])

                if i % 100 == 0 or i == args.runs:
                    elapsed = time.time() - t_start
                    avg = sum(scores) / len(scores)
                    rate = i / elapsed if elapsed > 0 else 0
                    print(f'  {i:>5}/{args.runs}  |  avg: {avg:5.1f}  '
                          f'|  last: {result["adjusted_score"]:5.1f}  '
                          f'|  {rate:.0f} runs/s  |  {elapsed:.0f}s')

        print('-' * 56)
        elapsed = time.time() - t_start
        size_kb = output_path.stat().st_size / 1024
        print(f'\nDone in {elapsed:.1f}s')
        print(f'  Records : {args.runs}')
        print(f'  Score   : {min(scores):.1f} – {max(scores):.1f}  (avg {sum(scores)/len(scores):.1f})')
        print(f'  File    : {output_path}  ({size_kb:.0f} KB)')


if __name__ == '__main__':
    main()
