"""
Slot recommender — Mode 2: manual placement + AI slot hints.

Phase 1: look-ahead scoring.
  For each of 25 candidate slots, tentatively add the new entry and
  run score_schedule() on the trial schedule. O(25 × score_schedule).

Phase 2: Random Forest classifier (recommend_slots_ml).
  Falls back to look-ahead until ai/models/recommender.pkl exists.
  Train with: python ai/train_rf.py
"""
import os
import pickle
from collections import defaultdict

from .scoring import score_schedule, DAYS, TIMES

MODEL_PATH   = 'ai/models/recommender.pkl'
OPTIMAL_IDX  = {1, 2}

# Module-level model cache — reloaded when the .pkl file changes
_model_cache = None
_model_mtime = None


def _load_model():
    global _model_cache, _model_mtime
    if not os.path.exists(MODEL_PATH):
        return None
    mtime = os.path.getmtime(MODEL_PATH)
    if _model_cache is None or mtime != _model_mtime:
        with open(MODEL_PATH, 'rb') as f:
            _model_cache = pickle.load(f)
        _model_mtime = mtime
    return _model_cache


def recommend_slots(group_name, subject_id, teacher_id,
                    current_entries, course_loads, subjects,
                    greedy_window_count=None, classroom=None, top_n=5):
    """
    Rank valid time slots for placing one new assignment.

    Args:
        group_name: str — e.g. 'ІПЗ-41'
        subject_id: int
        teacher_id: int
        current_entries: list of dicts {day, time, group_name, teacher_id, subject_id}
        course_loads: list of CourseLoad ORM objects or dicts (for max_achievable)
        subjects: dict {subject_id: difficulty}
        greedy_window_count: int or None — H4 normalization baseline
        classroom: str or None — if given, classroom conflicts are also checked
        top_n: int — how many best slots to return

    Returns:
        list of dicts sorted best→worst:
        [{'day': ..., 'time': ..., 'score': float, 'delta': float}, ...]
        delta = adjusted_score change vs the current schedule (before placement)
    """
    base = score_schedule(current_entries,
                          course_loads=course_loads,
                          greedy_window_count=greedy_window_count,
                          subjects=subjects)
    base_score = base['adjusted_score']

    results = []
    for day in DAYS:
        for time in TIMES:
            if _has_conflict(day, time, group_name, teacher_id, classroom, current_entries):
                continue
            trial = current_entries + [{
                'day': day,
                'time': time,
                'group_name': group_name,
                'teacher_id': teacher_id,
                'subject_id': subject_id,
            }]
            r = score_schedule(trial,
                               course_loads=course_loads,
                               greedy_window_count=greedy_window_count,
                               subjects=subjects)
            results.append({
                'day': day,
                'time': time,
                'score': r['adjusted_score'],
                'delta': round(r['adjusted_score'] - base_score, 1),
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_n]


def recommend_slots_ml(group_name, subject_id, teacher_id,
                       current_entries, course_loads, subjects,
                       greedy_window_count=None, classroom=None, top_n=5):
    """
    RF-based slot recommender. Falls back to look-ahead when model is absent.

    Computes the same 9 features as extract_features.py for each candidate slot,
    then ranks by P(high_quality) from the Random Forest.

    Returns list of dicts — same structure as recommend_slots(), with an extra
    'mode' key: 'ml' or 'lookahead'.
    """
    pkg = _load_model()
    if pkg is None:
        recs = recommend_slots(group_name, subject_id, teacher_id,
                               current_entries, course_loads, subjects,
                               greedy_window_count, classroom, top_n)
        for r in recs:
            r['mode'] = 'lookahead'
        return recs

    clf = pkg['model']

    # Pre-compute current group/teacher time-indices per day
    g_times = defaultdict(lambda: defaultdict(list))
    t_times = defaultdict(lambda: defaultdict(list))
    for e in current_entries:
        ti = TIMES.index(e['time']) if e['time'] in TIMES else 0
        g_times[e['group_name']][e['day']].append(ti)
        t_times[e['teacher_id']][e['day']].append(ti)

    difficulty = subjects.get(subject_id, 2)

    feature_rows = []
    slots = []
    for day in DAYS:
        for time in TIMES:
            if _has_conflict(day, time, group_name, teacher_id, classroom, current_entries):
                continue

            d_idx = DAYS.index(day)
            t_idx = TIMES.index(time)

            # Simulate adding this entry
            gtimes = g_times[group_name][day] + [t_idx]
            ttimes = t_times[teacher_id][day] + [t_idx]

            feature_rows.append([
                d_idx,
                t_idx,
                int(t_idx in OPTIMAL_IDX),
                difficulty,
                len(gtimes),
                len(ttimes),
                int(_has_window(gtimes)),
                int(_has_window(ttimes)),
                int(len(gtimes) == 1),
            ])
            slots.append({'day': day, 'time': time})

    if not slots:
        return []

    proba = clf.predict_proba(feature_rows)[:, 1]   # P(high_quality)

    results = [
        {
            'day':   s['day'],
            'time':  s['time'],
            'score': round(float(p) * 100, 1),  # 0-100 probability scale
            'delta': None,                       # not meaningful for ML ranking
            'mode':  'ml',
        }
        for s, p in zip(slots, proba)
    ]
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _has_window(time_indices):
    s = sorted(set(time_indices))
    return any(s[i + 1] - s[i] > 1 for i in range(len(s) - 1))


def _has_conflict(day, time, group_name, teacher_id, classroom, entries):
    """Return True if placing this entry at (day, time) causes a hard conflict."""
    for e in entries:
        if e['day'] != day or e['time'] != time:
            continue
        if e['group_name'] == group_name or e['teacher_id'] == teacher_id:
            return True
        if classroom and e.get('classroom') == classroom:
            return True
    return False
