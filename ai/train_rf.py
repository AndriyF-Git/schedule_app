"""
Train Random Forest classifier on schedule features.

Usage (from schedule_app/):
    python ai/train_rf.py

Reads:  data/features.csv   (run extract_features.py first)
Writes: ai/models/recommender.pkl
"""
import pickle
import sys
from pathlib import Path

FEATURE_COLS = [
    'day_idx', 'time_idx', 'is_optimal_time',
    'subject_difficulty',
    'group_pairs_today', 'teacher_pairs_today',
    'group_window', 'teacher_window',
    'is_single_pair_day',
]
TARGET     = 'label_high_quality'
CSV_PATH   = Path('data/features.csv')
MODEL_PATH = Path('ai/models/recommender.pkl')


def train(csv_path=CSV_PATH, model_path=MODEL_PATH, n_estimators=100):
    """
    Train RF and save to model_path.

    Returns dict with metrics:
        rows, accuracy, f1, trees, top_feature
    """
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, f1_score

    csv_path   = Path(csv_path)
    model_path = Path(model_path)

    if not csv_path.exists():
        raise FileNotFoundError(
            f'Features not found: {csv_path}\n'
            'Run: python ai/extract_features.py'
        )

    df = pd.read_csv(csv_path)
    X  = df[FEATURE_COLS].values
    y  = df[TARGET].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    metrics = {
        'rows':        len(df),
        'accuracy':    round(accuracy_score(y_test, y_pred), 3),
        'f1':          round(f1_score(y_test, y_pred, average='weighted'), 3),
        'trees':       n_estimators,
        'top_feature': FEATURE_COLS[clf.feature_importances_.argmax()],
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, 'wb') as f:
        pickle.dump({'model': clf, 'features': FEATURE_COLS}, f)

    return metrics


def main():
    try:
        m = train()
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    print(f'Trained on {m["rows"]:,} rows')
    print(f'  Accuracy : {m["accuracy"]}')
    print(f'  F1 score : {m["f1"]}')
    print(f'  Top feat : {m["top_feature"]}')
    print(f'  Trees    : {m["trees"]}')
    print('Saved -> ai/models/recommender.pkl')


if __name__ == '__main__':
    main()
