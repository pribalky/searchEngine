"""Lightweight, offline approximation of real JD matching: TF-IDF +
cosine similarity between two texts.

This is a step up from the fixed-keyword-list matching in scoring.py --
it catches paraphrased/partial overlap on frequency-weighted shared
vocabulary (e.g. "established governance controls" vs "define delivery
gate criteria" share no exact PROFILE_KEYWORDS phrase but do share
weighted terms) -- without needing a model download or API calls. It is
NOT real semantic understanding; a synonym-free paraphrase with zero
shared vocabulary still scores near zero. See the scoring-engine
discussion for why a full embeddings/LLM upgrade would go further."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def tfidf_similarity_pct(text_a: str, text_b: str) -> int:
    text_a = (text_a or "").strip()
    text_b = (text_b or "").strip()
    if not text_a or not text_b:
        return 0

    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform([text_a, text_b])
    except ValueError:
        # e.g. both texts reduce to nothing but stopwords once tokenized
        return 0

    if matrix.shape[1] == 0:
        return 0

    similarity = cosine_similarity(matrix[0], matrix[1])[0][0]
    return round(similarity * 100)
