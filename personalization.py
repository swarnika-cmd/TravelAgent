"""
RAG retriever. Finds similar travelers from the Kaggle Indian Travel Survey
(if you've put travel_survey.csv in data/raw/ and run `python personalization.py build`).

Falls back to hand-written representative personas if the dataset/index aren't there.
"""
import sys
import json
from pathlib import Path
from typing import List
from schemas import Brief, SimilarTraveler

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw" / "travel_survey.csv"
PROC = ROOT / "data" / "cache" / "rag"
PROC.mkdir(parents=True, exist_ok=True)
JSON_PATH = PROC / "survey.json"
INDEX_PATH = PROC / "survey.faiss"

_model = None
_index = None
_corpus = None


_FALLBACK = [
    SimilarTraveler(summary="Solo male, 26, software engineer from Bangalore; loves adventure and nature; budget ~40k",
        chosen=["Manali", "Spiti", "Hampi", "Coorg"], budget_inr=40000, similarity=0.78),
    SimilarTraveler(summary="Couple, late 20s, Mumbai; short curated getaways, comfort-focused",
        chosen=["Goa", "Udaipur", "Andaman", "Munnar"], budget_inr=75000, similarity=0.71),
    SimilarTraveler(summary="Family of 4 from Delhi, heritage + kid-friendly, prefer trains",
        chosen=["Jaipur", "Agra", "Rishikesh", "Shimla"], budget_inr=60000, similarity=0.65),
    SimilarTraveler(summary="Solo female, 31, photographer from Bangalore; avoids crowds, off-beat picks",
        chosen=["Hampi", "Pondicherry", "Spiti", "Gokarna"], budget_inr=50000, similarity=0.69),
    SimilarTraveler(summary="Friend group, mid-20s, Pune; budget-conscious party trips",
        chosen=["Goa", "Lonavala", "Mahabaleshwar"], budget_inr=18000, similarity=0.58),
]


def _brief_to_query(brief: Brief) -> str:
    parts = []
    if brief.origin: parts.append(f"from {brief.origin}")
    if brief.vibe: parts.append(brief.vibe)
    if brief.duration_days: parts.append(f"{brief.duration_days} days")
    if brief.budget_max_inr: parts.append(f"budget {brief.budget_max_inr}")
    if brief.traveller_count > 1: parts.append(f"group of {brief.traveller_count}")
    return ", ".join(parts) or "indian traveler"


def _load_artifacts():
    global _model, _index, _corpus
    if _corpus is not None:
        return
    if not JSON_PATH.exists() or not INDEX_PATH.exists():
        return
    try:
        from sentence_transformers import SentenceTransformer
        import faiss
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _index = faiss.read_index(str(INDEX_PATH))
        _corpus = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[rag] artifact load failed: {e}")
        _corpus = []


def retrieve(brief: Brief, k: int = 3) -> List[SimilarTraveler]:
    _load_artifacts()
    if not _corpus or _model is None or _index is None:
        return _FALLBACK[:k]
    try:
        vec = _model.encode([_brief_to_query(brief)], normalize_embeddings=True)
        scores, idxs = _index.search(vec, k)
        out = []
        for s, i in zip(scores[0], idxs[0]):
            if 0 <= i < len(_corpus):
                row = _corpus[i]
                out.append(SimilarTraveler(
                    summary=row.get("summary", ""),
                    chosen=row.get("destinations", []),
                    budget_inr=row.get("budget_inr"),
                    similarity=float(s),
                ))
        return out or _FALLBACK[:k]
    except Exception:
        return _FALLBACK[:k]


def build_index():
    """Build the FAISS index from data/raw/travel_survey.csv. Run once."""
    if not RAW.exists():
        print(f"[skip] {RAW} not found.")
        return
    try:
        import pandas as pd
        from sentence_transformers import SentenceTransformer
        import faiss
        import numpy as np
    except ImportError as e:
        print(f"[error] {e}"); return

    df = pd.read_csv(RAW).fillna("")
    personas = []
    for _, row in df.iterrows():
        d = row.to_dict()
        age = d.get("Age", "") or d.get("age", "")
        gender = d.get("Gender", "") or d.get("gender", "")
        city = d.get("City", "") or d.get("Hometown", "")
        occ = d.get("Occupation", "")
        prefs = d.get("Preferences", "") or d.get("Activities", "")
        dests = d.get("Destinations", "") or d.get("destination", "")
        budget = "".join(c for c in str(d.get("Budget", "") or d.get("Trip_Cost", "")) if c.isdigit())
        personas.append({
            "summary": f"{gender} {age}, {occ} from {city}. Preferences: {prefs}".strip(),
            "destinations": [x.strip() for x in str(dests).split(",") if x.strip()],
            "budget_inr": int(budget) if budget else None,
        })

    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [p["summary"] for p in personas]
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
    idx = faiss.IndexFlatIP(vecs.shape[1])
    idx.add(np.asarray(vecs, dtype="float32"))
    faiss.write_index(idx, str(INDEX_PATH))
    JSON_PATH.write_text(json.dumps(personas, indent=2), encoding="utf-8")
    print(f"[ok] {len(personas)} personas indexed.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_index()
    else:
        print("usage: python personalization.py build")
