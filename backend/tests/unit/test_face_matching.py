"""
Unit tests for face embedding parsing, serialization, and cosine similarity.

Tests the core data transformation functions used by the visitor service
for face matching and identification.
"""

import os
import sys
import json
import math
import pytest

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.visitor_service import (
    parse_embedding_payload,
    serialize_embedding_for_storage,
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity matching the visitor_service implementation."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class TestParseEmbedding:
    def test_parse_from_list(self):
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = parse_embedding_payload(embedding)
        assert result is not None
        assert len(result) == 5
        assert result == [0.1, 0.2, 0.3, 0.4, 0.5]

    def test_parse_from_tuple(self):
        embedding = (0.1, 0.2, 0.3)
        result = parse_embedding_payload(embedding)
        assert result is not None
        assert result == [0.1, 0.2, 0.3]

    def test_parse_from_json_string(self):
        embedding = json.dumps([0.1, 0.2, 0.3])
        result = parse_embedding_payload(embedding)
        assert result is not None
        assert result == [0.1, 0.2, 0.3]

    def test_parse_from_bracket_string(self):
        embedding = "[0.1, 0.2, 0.3]"
        result = parse_embedding_payload(embedding)
        assert result is not None
        assert result == [0.1, 0.2, 0.3]

    def test_parse_none_returns_none(self):
        assert parse_embedding_payload(None) is None

    def test_parse_empty_string_returns_none(self):
        result = parse_embedding_payload("")
        assert result is None

    def test_parse_invalid_string_returns_none(self):
        result = parse_embedding_payload("not-an-embedding")
        assert result is None

    def test_parse_preserves_512_dim(self):
        embedding = [float(i) / 512.0 for i in range(512)]
        result = parse_embedding_payload(embedding)
        assert result is not None
        assert len(result) == 512


class TestSerializeEmbedding:
    def test_serialize_returns_value(self):
        embedding = [0.1, 0.2, 0.3]
        result = serialize_embedding_for_storage(embedding)
        assert result is not None

    def test_serialize_roundtrip(self):
        """Serialized embedding can be parsed back."""
        embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        stored = serialize_embedding_for_storage(embedding)
        recovered = parse_embedding_payload(stored)
        assert recovered is not None
        assert len(recovered) == len(embedding)
        for a, b in zip(embedding, recovered):
            assert abs(a - b) < 1e-6


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_similar_vectors_above_threshold(self):
        a = [0.9, 0.1, 0.0]
        b = [0.85, 0.15, 0.05]
        sim = _cosine_similarity(a, b)
        assert sim > 0.6  # Should be above typical threshold

    def test_dissimilar_vectors_below_threshold(self):
        a = [1.0, 0.0, 0.0, 0.0]
        b = [0.0, 0.0, 0.0, 1.0]
        sim = _cosine_similarity(a, b)
        assert sim < 0.6  # Should be below typical threshold

    def test_zero_vector_returns_zero(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_high_dimensional_similarity(self):
        """512-dim vectors with small perturbation should be very similar."""
        import random
        random.seed(42)
        a = [random.gauss(0, 1) for _ in range(512)]
        # Small perturbation
        b = [x + random.gauss(0, 0.01) for x in a]
        sim = _cosine_similarity(a, b)
        assert sim > 0.99
