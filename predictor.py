"""
Vlog 조회수 예측 모델
"""
import os
import re
import numpy as np
import pickle
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
MODEL_PATH = Path(__file__).parent / "data" / "vlog_model.pkl"


def extract_features(video: dict, subscriber_count: int = 0) -> dict:
    title = video.get("title", "")
    title_len = len(title)
    word_count = len(title.split())
    has_emoji = 1 if re.search(r'[\U0001F300-\U0001F9FF]', title) else 0
    has_number = 1 if re.search(r'\d', title) else 0
    caps_ratio = sum(1 for c in title if c.isupper()) / max(len(title), 1)
    has_question = 1 if '?' in title else 0
    has_exclaim = 1 if '!' in title else 0
    has_hashtag = 1 if '#' in title else 0
    has_korean = 1 if re.search(r'[\uac00-\ud7a3]', title) else 0

    title_lower = title.lower()
    has_vlog = 1 if any(kw in title_lower for kw in ['vlog', '브이로그', '일상']) else 0
    has_study = 1 if any(kw in title_lower for kw in ['study', 'exam', '공부', '시험', '대학', 'uni']) else 0
    has_food = 1 if any(kw in title_lower for kw in ['food', 'eat', 'cafe', 'coffee', '카페', '먹방', '맛집']) else 0
    has_travel = 1 if any(kw in title_lower for kw in ['travel', 'trip', '여행', 'tour']) else 0
    has_routine = 1 if any(kw in title_lower for kw in ['routine', 'morning', 'night', 'day in', 'grwm']) else 0
    has_aesthetic = 1 if any(kw in title_lower for kw in ['aesthetic', 'cozy', 'chill', 'peaceful', 'calm']) else 0
    has_transformation = 1 if any(kw in title_lower for kw in ['before', 'after', 'glow', 'transformation', 'how i']) else 0

    category = video.get("category", "Uncategorized")
    cats = ["daily vlog", "travel", "food", "lifestyle", "tech", "study", "other"]
    cat_features = {f"cat_{c.replace(' ', '_')}": 1 if category == c else 0 for c in cats}

    import math
    log_subscribers = round(math.log10(subscriber_count + 1), 3)

    return {
        "title_len": title_len, "word_count": word_count,
        "has_emoji": has_emoji, "has_number": has_number,
        "caps_ratio": round(caps_ratio, 3),
        "has_question": has_question, "has_exclaim": has_exclaim,
        "has_hashtag": has_hashtag, "has_korean": has_korean,
        "has_vlog": has_vlog, "has_study": has_study,
        "has_food": has_food, "has_travel": has_travel,
        "has_routine": has_routine, "has_aesthetic": has_aesthetic,
        "has_transformation": has_transformation,
        "log_subscribers": log_subscribers,
        **cat_features,
    }


def views_to_tier(views):
    if views >= 1_000_000: return "viral"
    elif views >= 100_000: return "high"
    elif views >= 10_000: return "medium"
    else: return "low"


def tier_to_label(t): return {"low": 0, "medium": 1, "high": 2, "viral": 3}[t]
def label_to_tier(l): return {0: "low", 1: "medium", 2: "high", 3: "viral"}[l]


def train_model():
    from supabase import create_client
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    videos = sb.table("vlog_videos").select("*").eq("hidden", False).execute().data

    if len(videos) < 20:
        print(f"[SKIP] Not enough data ({len(videos)})")
        return None

    feature_names = None
    X_list, y_list = [], []

    for v in videos:
        if v.get("views", 0) == 0:
            continue
        feats = extract_features(v)
        if feature_names is None:
            feature_names = sorted(feats.keys())
        X_list.append([feats[f] for f in feature_names])
        y_list.append(tier_to_label(views_to_tier(v["views"])))

    X = np.array(X_list)
    y = np.array(y_list)

    print(f"[DATA] {len(X)} videos")
    for t in ["low", "medium", "high", "viral"]:
        print(f"  {t}: {sum(1 for l in y if l == tier_to_label(t))}")

    model = GradientBoostingClassifier(n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42)

    if len(X) >= 10:
        scores = cross_val_score(model, X, y, cv=min(5, len(X)//2), scoring="accuracy")
        print(f"[CV] Accuracy: {scores.mean():.2f} (+/- {scores.std():.2f})")

    model.fit(X, y)

    importances = sorted(zip(feature_names, model.feature_importances_), key=lambda x: x[1], reverse=True)
    print("\n[FEATURES] Top 10:")
    for name, imp in importances[:10]:
        print(f"  {name}: {imp:.3f}")

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "feature_names": feature_names}, f)
    print(f"\n[OK] Saved: {MODEL_PATH}")
    return model, feature_names


def predict(title, category="Uncategorized", subscriber_count=0):
    if not MODEL_PATH.exists():
        return {"error": "Model not trained. Run train first."}
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    model, feature_names = data["model"], data["feature_names"]
    feats = extract_features({"title": title, "category": category}, subscriber_count=subscriber_count)
    X = np.array([[feats[f] for f in feature_names]])
    pred = model.predict(X)[0]
    proba = model.predict_proba(X)[0]
    tier_proba = {}
    for i, cls in enumerate(model.classes_):
        tier_proba[label_to_tier(cls)] = round(float(proba[i]) * 100, 1)
    tier = label_to_tier(pred)
    ranges = {"low": "~10K", "medium": "10K~100K", "high": "100K~1M", "viral": "1M+"}
    return {
        "tier": tier, "confidence": round(float(max(proba)) * 100, 1),
        "probabilities": tier_proba, "estimated_range": ranges[tier],
    }


if __name__ == "__main__":
    print("Training vlog view prediction model...")
    result = train_model()
    if result:
        tests = [
            ("서울대생의 하루 일상 브이로그", "study"),
            ("aesthetic korean cafe vlog in seoul", "food"),
            ("간호대생 시험기간 공부 브이로그", "study"),
            ("korean daily vlog | morning routine", "lifestyle"),
        ]
        print("\nTest predictions:")
        for title, cat in tests:
            r = predict(title, cat)
            print(f"  \"{title}\" -> {r['tier']} ({r['confidence']}%) {r['estimated_range']}")
