"""
Quantum-Inspired Similarity Search Service (ENH-017)

Implements quantum-inspired classical algorithms for fast similarity search:
- Amplitude encoding simulation for cosine similarity
- Grover's-inspired search with quadratic speedup simulation
- Quantum-inspired clustering (spectral methods)
"""

import math
import logging
import time
import numpy as np
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)


class QuantumSimilarityService:
    """
    Quantum-inspired similarity search using classical simulations
    of quantum algorithms. Useful for academic demonstration of
    quantum computing concepts applied to face recognition.
    """

    def quantum_cosine_similarity(
        self, vec_a: List[float], vec_b: List[float]
    ) -> Dict:
        """
        Quantum-inspired cosine similarity using amplitude encoding.

        In a real quantum computer, vectors would be encoded as amplitudes
        of quantum states, and a SWAP test would estimate overlap.
        This simulates that process classically.
        """
        a = np.array(vec_a, dtype=np.float64)
        b = np.array(vec_b, dtype=np.float64)

        # Normalize (amplitude encoding requires unit vectors)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return {"similarity": 0.0, "method": "quantum_amplitude_encoding", "shots": 0}

        a_normalized = a / norm_a
        b_normalized = b / norm_b

        # Simulate SWAP test: probability of measuring |0> = (1 + |<a|b>|^2) / 2
        inner_product = float(np.dot(a_normalized, b_normalized))
        swap_prob = (1 + inner_product ** 2) / 2

        # Simulate multiple "shots" (measurements)
        n_shots = 1024
        measurements = np.random.binomial(1, swap_prob, n_shots)
        estimated_overlap = 2 * np.mean(measurements) - 1
        estimated_similarity = math.sqrt(max(0, estimated_overlap))

        return {
            "similarity": float(inner_product),  # Exact classical result
            "quantum_estimate": float(estimated_similarity),  # Simulated quantum estimate
            "swap_probability": float(swap_prob),
            "method": "quantum_swap_test_simulation",
            "shots": n_shots,
            "estimation_error": abs(inner_product - estimated_similarity),
        }

    def grover_search(
        self,
        query_embedding: List[float],
        database_embeddings: List[List[float]],
        threshold: float = 0.6,
    ) -> Dict:
        """
        Grover's-inspired search with sqrt(N) speedup simulation.

        In a real quantum computer, Grover's algorithm finds a matching
        item in O(sqrt(N)) queries vs O(N) classically.
        """
        N = len(database_embeddings)
        if N == 0:
            return {"matches": [], "queries_classical": 0, "queries_quantum": 0}

        query = np.array(query_embedding, dtype=np.float64)
        query_norm = np.linalg.norm(query)
        if query_norm > 0:
            query = query / query_norm

        start_time = time.perf_counter()

        # Classical search (for comparison)
        similarities = []
        for i, emb in enumerate(database_embeddings):
            emb_arr = np.array(emb, dtype=np.float64)
            emb_norm = np.linalg.norm(emb_arr)
            if emb_norm > 0:
                sim = float(np.dot(query, emb_arr / emb_norm))
            else:
                sim = 0.0
            similarities.append((i, sim))

        elapsed = time.perf_counter() - start_time

        # Grover's speedup: sqrt(N) iterations instead of N
        classical_queries = N
        quantum_queries = max(1, int(math.sqrt(N) * math.pi / 4))  # Optimal Grover iterations

        # Filter matches above threshold
        matches = [
            {"index": idx, "similarity": round(sim, 6)}
            for idx, sim in sorted(similarities, key=lambda x: x[1], reverse=True)
            if sim >= threshold
        ]

        return {
            "matches": matches[:10],  # Top 10
            "total_matches": len(matches),
            "database_size": N,
            "queries_classical": classical_queries,
            "queries_quantum": quantum_queries,
            "speedup_factor": round(classical_queries / quantum_queries, 2) if quantum_queries > 0 else 0,
            "search_time_ms": round(elapsed * 1000, 2),
            "threshold": threshold,
        }

    def quantum_clustering(
        self, embeddings: List[List[float]], n_clusters: int = 3
    ) -> Dict:
        """
        Quantum-inspired clustering using spectral methods.

        Uses the quantum-inspired idea of constructing a similarity
        graph and finding clusters via eigendecomposition (analogous
        to quantum walk-based clustering).
        """
        if not embeddings:
            return {"clusters": [], "method": "quantum_spectral"}

        data = np.array(embeddings, dtype=np.float64)
        N = data.shape[0]
        n_clusters = min(n_clusters, N)

        # Build similarity matrix (quantum kernel)
        norms = np.linalg.norm(data, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized = data / norms
        similarity = normalized @ normalized.T

        # Construct Laplacian (quantum walk transition matrix analog)
        degree = np.diag(similarity.sum(axis=1))
        laplacian = degree - similarity

        # Eigendecomposition (quantum phase estimation analog)
        eigenvalues, eigenvectors = np.linalg.eigh(laplacian)

        # Use first k eigenvectors for clustering
        features = eigenvectors[:, :n_clusters]

        # Simple k-means on spectral features
        labels = self._simple_kmeans(features, n_clusters)

        # Build cluster info
        clusters = {}
        for i, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(i)

        return {
            "clusters": {str(k): v for k, v in clusters.items()},
            "n_clusters": n_clusters,
            "n_items": N,
            "method": "quantum_spectral_clustering",
            "eigenvalues": eigenvalues[:n_clusters].tolist(),
            "silhouette_approximation": self._silhouette(data, labels),
        }

    def _simple_kmeans(self, data: np.ndarray, k: int, max_iter: int = 100) -> List[int]:
        """Simple k-means implementation."""
        N = data.shape[0]
        if N <= k:
            return list(range(N))

        # Random initialization
        indices = np.random.choice(N, k, replace=False)
        centroids = data[indices].copy()

        labels = np.zeros(N, dtype=int)
        for _ in range(max_iter):
            # Assign
            for i in range(N):
                dists = [np.linalg.norm(data[i] - c) for c in centroids]
                labels[i] = int(np.argmin(dists))
            # Update centroids
            new_centroids = np.zeros_like(centroids)
            for j in range(k):
                members = data[labels == j]
                if len(members) > 0:
                    new_centroids[j] = members.mean(axis=0)
                else:
                    new_centroids[j] = centroids[j]
            if np.allclose(centroids, new_centroids):
                break
            centroids = new_centroids

        return labels.tolist()

    def _silhouette(self, data: np.ndarray, labels: List[int]) -> float:
        """Approximate silhouette score."""
        labels_arr = np.array(labels)
        unique = np.unique(labels_arr)
        if len(unique) < 2:
            return 0.0

        scores = []
        for i in range(min(len(data), 100)):  # Sample for speed
            same = data[labels_arr == labels_arr[i]]
            if len(same) <= 1:
                continue
            a = np.mean([np.linalg.norm(data[i] - s) for s in same if not np.array_equal(data[i], s)] or [0])
            b = float("inf")
            for label in unique:
                if label != labels_arr[i]:
                    other = data[labels_arr == label]
                    if len(other) > 0:
                        b = min(b, np.mean([np.linalg.norm(data[i] - o) for o in other]))
            if max(a, b) > 0:
                scores.append((b - a) / max(a, b))

        return round(float(np.mean(scores)) if scores else 0.0, 4)

    def estimate_speedup(self, n_items: int) -> Dict:
        """Estimate theoretical quantum speedup for various operations."""
        return {
            "database_size": n_items,
            "search": {
                "classical_queries": n_items,
                "quantum_queries": max(1, int(math.sqrt(n_items) * math.pi / 4)),
                "speedup": round(n_items / max(1, math.sqrt(n_items) * math.pi / 4), 2),
                "algorithm": "Grover's Search",
            },
            "similarity": {
                "classical_ops": n_items * 512,  # 512-dim vectors
                "quantum_ops": int(math.log2(max(2, n_items)) * 512),
                "speedup": round(n_items / max(1, math.log2(max(2, n_items))), 2),
                "algorithm": "Quantum Amplitude Estimation",
            },
            "optimization": {
                "classical_time": f"O(N^2) = O({n_items**2})",
                "quantum_time": f"O(N^1.5) = O({int(n_items**1.5)})",
                "speedup": round(n_items ** 0.5, 2),
                "algorithm": "Quantum Annealing",
            },
            "note": "These are theoretical estimates. Actual quantum advantage "
                    "requires fault-tolerant quantum hardware not yet available at scale.",
        }


quantum_similarity_service = QuantumSimilarityService()
