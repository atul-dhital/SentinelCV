from services.data_quality_service import DemographicAnalyzer


def test_compute_diversity_index_returns_complete_empty_shape():
    analyzer = DemographicAnalyzer()

    result = analyzer.compute_diversity_index([])

    assert result["overall_diversity"] == 0.0
    assert result["max_demographic_skew"] == 0.0
    assert result["age_distribution"] == {}
    assert result["gender_distribution"] == {}
    assert result["ethnicity_distribution"] == {}
