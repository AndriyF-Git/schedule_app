"""
Feature extraction: schedules.jsonl → features.csv for scikit-learn.

Usage (from schedule_app/ directory):
    python ai/extract_features.py
    python ai/extract_features.py --input data/schedules.jsonl --output data/features.csv

Requires generate_dataset.py to have been run first.
Each JSONL record (one schedule) expands into N rows — one per schedule entry.

Output CSV columns:
    run_id              — schedule run identifier
    run_score           — overall adjusted score 0-100 (regression target)
    day_idx             — 0 (Mon) to 4 (Fri)
    time_idx            — 0 (9:00) to 4 (16:00)
    is_optimal_time     — 1 if pair 2 or 3 (best for difficult subjects)
    subject_difficulty  — 1 easy / 2 medium / 3 hard
    group_pairs_today   — how many pairs this group has on this day
    teacher_pairs_today — how many pairs this teacher has on this day
    group_window        — 1 if the group has a gap between pairs today
    teacher_window      — 1 if the teacher has a gap between pairs today
    is_single_pair_day  — 1 if this is the only pair for the group today
    label_high_quality  — binary classification target: 1 if run_score >= 40
"""
import json
import csv
import argparse
from pathlib import Path
from collections import defaultdict

DAYS  = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця"]
TIMES = ['9:00 - 10:30', '10:45 - 12:15', '12:30 - 14:00', '14:15 - 15:45', '16:00 - 17:30']
OPTIMAL = {'10:45 - 12:15', '12:30 - 14:00'}

DAY_IDX  = {d: i for i, d in enumerate(DAYS)}
TIME_IDX = {t: i for i, t in enumerate(TIMES)}

HIGH_QUALITY_THRESHOLD = 40

FEATURE_COLS = [
    'run_id', 'run_score',
    'day_idx', 'time_idx', 'is_optimal_time',
    'subject_difficulty',
    'group_pairs_today', 'teacher_pairs_today',
    'group_window', 'teacher_window',
    'is_single_pair_day',
    'label_high_quality',
]


def _has_window(time_indices):
    s = sorted(set(time_indices))
    return any(s[i + 1] - s[i] > 1 for i in range(len(s) - 1))


def _extract_record(record):
    """Yield one feature dict per entry in a JSONL record."""
    run_id    = record['run_id']
    run_score = record['score']
    label     = int(run_score >= HIGH_QUALITY_THRESHOLD)
    entries   = record['entries']

    g_times = defaultdict(lambda: defaultdict(list))
    t_times = defaultdict(lambda: defaultdict(list))
    for e in entries:
        ti = TIME_IDX.get(e['time'], 0)
        g_times[e['group_name']][e['day']].append(ti)
        t_times[e['teacher_id']][e['day']].append(ti)

    for e in entries:
        day, time = e['day'], e['time']
        group, teacher = e['group_name'], e['teacher_id']
        gtimes = g_times[group][day]
        ttimes = t_times[teacher][day]
        yield {
            'run_id':              run_id,
            'run_score':           run_score,
            'day_idx':             DAY_IDX.get(day, 0),
            'time_idx':            TIME_IDX.get(time, 0),
            'is_optimal_time':     int(time in OPTIMAL),
            'subject_difficulty':  e.get('subject_difficulty', 2),
            'group_pairs_today':   len(gtimes),
            'teacher_pairs_today': len(ttimes),
            'group_window':        int(_has_window(gtimes)),
            'teacher_window':      int(_has_window(ttimes)),
            'is_single_pair_day':  int(len(gtimes) == 1),
            'label_high_quality':  label,
        }


def run(in_path='data/schedules.jsonl', out_path='data/features.csv'):
    """Importable entry point — call from Flask routes or other scripts."""
    in_path  = Path(in_path)
    out_path = Path(out_path)

    if not in_path.exists():
        raise FileNotFoundError(f'JSONL not found: {in_path}. Run generate_dataset.py first.')

    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    with open(in_path, encoding='utf-8') as f_in, \
         open(out_path, 'w', newline='', encoding='utf-8') as f_out:

        writer = csv.DictWriter(f_out, fieldnames=FEATURE_COLS)
        writer.writeheader()

        for line in f_in:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for row in _extract_record(record):
                writer.writerow(row)
                total_rows += 1

    return total_rows


def main():
    parser = argparse.ArgumentParser(description='Extract per-entry features from JSONL dataset.')
    parser.add_argument('--input',  default='data/schedules.jsonl', help='Input JSONL file')
    parser.add_argument('--output', default='data/features.csv',    help='Output CSV file')
    args = parser.parse_args()

    in_path  = Path(args.input)
    out_path = Path(args.output)

    try:
        total_rows = run(in_path, out_path)
    except FileNotFoundError as e:
        print(e)
        return

    size_kb = out_path.stat().st_size / 1024
    print(f'Done: {total_rows:,} rows -> {out_path}  ({size_kb:.0f} KB)')
    print(f'  ({total_rows // 1000}K entries from {total_rows // 59} schedules)')


if __name__ == '__main__':
    main()
