# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
NLP tools: spaCy, KeyBERT, scikit-learn, sentence-transformers, FAISS.
"""

import json

try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


class SpaCyNLPTool(BaseTool):
    name: str = 'spaCy (NLP topic tagging)'
    description: str = (
        'Run spaCy NLP on text: tokenization, POS tagging, named entity recognition, '
        'and noun phrase extraction for topic detection.'
    )

    def _run(self, text: str, model: str = 'en_core_web_sm') -> str:
        import spacy

        try:
            nlp = spacy.load(model)
        except OSError:
            import subprocess
            import sys

            subprocess.run([sys.executable, '-m', 'spacy', 'download', model], check=True)
            nlp = spacy.load(model)
        doc = nlp(text[:10000])  # cap input
        entities = [{'text': ent.text, 'label': ent.label_} for ent in doc.ents]
        noun_phrases = list({chunk.text.lower() for chunk in doc.noun_chunks})[:30]
        pos_counts = {}
        for token in doc:
            pos_counts[token.pos_] = pos_counts.get(token.pos_, 0) + 1
        return json.dumps(
            {
                'entities': entities[:50],
                'noun_phrases': noun_phrases,
                'pos_distribution': pos_counts,
                'token_count': len(doc),
                'sentence_count': len(list(doc.sents)),
            }
        )


class KeyBERTTool(BaseTool):
    name: str = 'KeyBERT (keyword extraction)'
    description: str = (
        'Extract top keywords and keyphrases from text using KeyBERT. '
        'Returns ranked list of (keyword, relevance_score) pairs.'
    )

    def _run(self, text: str, top_n: int = 10, keyphrase_ngram_range: str = '1,2', diversity: float = 0.5) -> str:
        from keybert import KeyBERT

        ngram_min, ngram_max = [int(x) for x in keyphrase_ngram_range.split(',')]
        kw_model = KeyBERT()
        keywords = kw_model.extract_keywords(
            text,
            keyphrase_ngram_range=(ngram_min, ngram_max),
            stop_words='english',
            top_n=top_n,
            use_maxsum=diversity > 0,
            diversity=diversity,
        )
        return json.dumps(
            {
                'keywords': [{'keyword': kw, 'score': round(score, 4)} for kw, score in keywords],
                'count': len(keywords),
            }
        )


class TopicClusteringTool(BaseTool):
    name: str = 'Topic Clustering (sklearn)'
    description: str = (
        'Cluster a list of texts into topic groups using TF-IDF vectorization and K-Means. '
        'Input: JSON list of strings. Returns cluster assignments and top terms per cluster.'
    )

    def _run(self, texts_json: str, n_clusters: int = 5, max_features: int = 500) -> str:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans

        texts = json.loads(texts_json) if isinstance(texts_json, str) else texts_json
        if len(texts) < n_clusters:
            n_clusters = max(2, len(texts))
        vectorizer = TfidfVectorizer(max_features=max_features, stop_words='english')
        X = vectorizer.fit_transform(texts)
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        feature_names = vectorizer.get_feature_names_out()
        clusters = {}
        for i in range(n_clusters):
            order = km.cluster_centers_[i].argsort()[::-1]
            top_terms = [feature_names[j] for j in order[:10]]
            members = [texts[k] for k, l in enumerate(labels) if l == i]
            clusters[f'cluster_{i}'] = {
                'top_terms': top_terms,
                'member_count': len(members),
                'sample_members': members[:3],
            }
        return json.dumps(
            {'n_clusters': n_clusters, 'total_texts': len(texts), 'assignments': labels.tolist(), 'clusters': clusters}
        )


class TranscriptSimilarityTool(BaseTool):
    name: str = 'Transcript Similarity (TF-IDF / cosine)'
    description: str = (
        'Compute cosine similarity between two text segments using TF-IDF. Returns similarity score 0.0–1.0.'
    )

    def _run(self, text1: str, text2: str) -> str:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer()
        tfidf = vectorizer.fit_transform([text1, text2])
        score = float(cosine_similarity(tfidf[0], tfidf[1])[0][0])
        return json.dumps({'similarity': round(score, 4), 'text1_len': len(text1), 'text2_len': len(text2)})


class SemanticSimilarityTool(BaseTool):
    name: str = 'Semantic Similarity (Sentence Transformers)'
    description: str = (
        'Compute semantic similarity between two texts using Sentence Transformers embeddings. '
        'Returns cosine similarity score 0.0–1.0.'
    )

    def _run(self, text1: str, text2: str, model_name: str = 'all-MiniLM-L6-v2') -> str:
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer(model_name)
        emb1 = model.encode(text1, convert_to_tensor=True)
        emb2 = model.encode(text2, convert_to_tensor=True)
        score = float(util.cos_sim(emb1, emb2)[0][0])
        return json.dumps({'similarity': round(score, 4), 'model': model_name})


class SentenceTransformerEmbeddingsTool(BaseTool):
    name: str = 'Sentence Transformers (embeddings)'
    description: str = (
        'Generate sentence embeddings for a list of texts using Sentence Transformers. '
        'Input: JSON list of strings. Returns list of embedding vectors.'
    )

    def _run(self, texts_json: str, model_name: str = 'all-MiniLM-L6-v2') -> str:
        from sentence_transformers import SentenceTransformer

        texts = json.loads(texts_json) if isinstance(texts_json, str) else texts_json
        model = SentenceTransformer(model_name)
        embeddings = model.encode(texts)
        return json.dumps(
            {
                'count': len(texts),
                'embedding_dim': int(embeddings.shape[1]),
                'embeddings': embeddings.tolist(),
                'model': model_name,
            }
        )


class FAISSVectorDBTool(BaseTool):
    name: str = 'FAISS / Vector DB'
    description: str = (
        'Build a FAISS index from embedding vectors and perform similarity search. '
        'Input: JSON list of {id, text} objects. Query with a search text to find top-k similar.'
    )

    def _run(self, items_json: str, query: str = '', top_k: int = 5, model_name: str = 'all-MiniLM-L6-v2') -> str:
        import faiss
        from sentence_transformers import SentenceTransformer

        items = json.loads(items_json) if isinstance(items_json, str) else items_json
        model = SentenceTransformer(model_name)
        texts = [item['text'] for item in items]
        embeddings = model.encode(texts).astype('float32')
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        faiss.normalize_L2(embeddings)
        index.add(embeddings)
        if query:
            q_emb = model.encode([query]).astype('float32')
            faiss.normalize_L2(q_emb)
            distances, indices = index.search(q_emb, min(top_k, len(items)))
            results = [
                {'id': items[i]['id'], 'text': items[i]['text'], 'score': float(distances[0][j])}
                for j, i in enumerate(indices[0])
                if i < len(items)
            ]
            return json.dumps({'query': query, 'top_k': top_k, 'results': results, 'index_size': len(items)})
        return json.dumps({'status': 'index built', 'size': len(items), 'dim': dim})


class EmotionLanguageDetectorTool(BaseTool):
    name: str = 'Emotion Language Detector (NLP)'
    description: str = (
        'Detect emotional tone in text (positive/negative/neutral + specific emotions) '
        'using a pre-trained transformers model.'
    )

    def _run(self, text: str, model_name: str = 'j-hartmann/emotion-english-distilroberta-base') -> str:
        from transformers import pipeline

        classifier = pipeline('text-classification', model=model_name, top_k=None, truncation=True, max_length=512)
        results = classifier(text[:1000])
        if isinstance(results, list) and results:
            scores = results[0] if isinstance(results[0], list) else results
            scores_sorted = sorted(scores, key=lambda x: x['score'], reverse=True)
            return json.dumps(
                {
                    'dominant_emotion': scores_sorted[0]['label'],
                    'dominant_score': round(scores_sorted[0]['score'], 4),
                    'all_emotions': [{'label': s['label'], 'score': round(s['score'], 4)} for s in scores_sorted],
                }
            )
        return json.dumps({'error': 'no results', 'raw': str(results)})


class TopicSummarizerTool(BaseTool):
    name: str = 'Topic Summarizer'
    description: str = (
        'Summarize a long text into key topics using a transformer summarization model. '
        'Returns a concise summary paragraph.'
    )

    def _run(
        self, text: str, max_length: int = 150, min_length: int = 40, model_name: str = 'facebook/bart-large-cnn'
    ) -> str:
        from transformers import pipeline

        summarizer = pipeline('summarization', model=model_name, truncation=True)
        # BART handles ~1024 tokens — truncate input
        result = summarizer(text[:3000], max_length=max_length, min_length=min_length, do_sample=False)
        summary = result[0]['summary_text'] if result else ''
        return json.dumps({'summary': summary, 'input_len': len(text), 'model': model_name})


class PatternExtractorTool(BaseTool):
    name: str = 'Pattern Extractor (NLP + stats)'
    description: str = (
        'Extract recurring patterns from a list of texts using NLP noun-phrase extraction '
        'and frequency statistics. Returns top recurring patterns with counts.'
    )

    def _run(self, texts_json: str, top_n: int = 20, min_freq: int = 2) -> str:
        from collections import Counter
        import re

        texts = json.loads(texts_json) if isinstance(texts_json, str) else texts_json
        try:
            import spacy

            nlp = spacy.load('en_core_web_sm')
            phrases = []
            for text in texts:
                doc = nlp(text[:500])
                phrases.extend([chunk.text.lower() for chunk in doc.noun_chunks])
        except Exception:
            # Fallback: simple regex word extraction
            phrases = []
            for text in texts:
                words = re.findall(r'\b[a-z]{4,}\b', text.lower())
                phrases.extend(words)
        counts = Counter(phrases)
        patterns = [{'pattern': p, 'count': c} for p, c in counts.most_common(top_n) if c >= min_freq]
        return json.dumps({'patterns': patterns, 'total_texts': len(texts), 'unique_patterns': len(counts)})


NLP_TOOLS = [
    SpaCyNLPTool(),
    KeyBERTTool(),
    TopicClusteringTool(),
    TranscriptSimilarityTool(),
    SemanticSimilarityTool(),
    SentenceTransformerEmbeddingsTool(),
    FAISSVectorDBTool(),
    EmotionLanguageDetectorTool(),
    TopicSummarizerTool(),
    PatternExtractorTool(),
]

__all__ = [
    'SpaCyNLPTool',
    'KeyBERTTool',
    'TopicClusteringTool',
    'TranscriptSimilarityTool',
    'SemanticSimilarityTool',
    'SentenceTransformerEmbeddingsTool',
    'FAISSVectorDBTool',
    'EmotionLanguageDetectorTool',
    'TopicSummarizerTool',
    'PatternExtractorTool',
    'NLP_TOOLS',
]
