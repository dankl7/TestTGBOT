import pytest
from services.normalizer import QueryNormalizer


@pytest.fixture
def normalizer():
    return QueryNormalizer()


def test_iphone_abbreviation_pm(normalizer):
    result = normalizer.normalize("17 PM 256")
    assert result.normalized_query == "iPhone 17 Pro Max 256GB"


def test_iphone_abbreviation_p(normalizer):
    result = normalizer.normalize("16 P 512")
    assert result.normalized_query == "iPhone 16 Pro 512GB"


def test_iphone_typo(normalizer):
    result = normalizer.normalize("iphoe 16")
    assert result.normalized_query == "iPhone 16"


def test_russian_translation(normalizer):
    result = normalizer.normalize("айфон 15 про макс 256")
    assert result.normalized_query == "iPhone 15 Pro Max 256GB"


def test_samsung_abbreviation(normalizer):
    result = normalizer.normalize("s24 ultra 512")
    assert result.normalized_query == "Samsung Galaxy S24 Ultra 512GB"


def test_macbook_abbreviation(normalizer):
    result = normalizer.normalize("mba 512")
    assert result.normalized_query == "MacBook Air 512GB"


def test_iphone_false_positive_prevention(normalizer):
    # '17 чехол' shouldn't become 'iPhone 17 чехол' because there's no phone context
    result = normalizer.normalize("17 чехол")
    assert result.normalized_query == "17 чехол"


def test_iphone_true_positive_context(normalizer):
    # '17' should become 'iPhone 17' because '256' gives it phone storage context
    result = normalizer.normalize("17 256")
    assert result.normalized_query == "iPhone 17 256GB"

    # '17' should become 'iPhone 17' because 'pro' gives it phone context
    result = normalizer.normalize("17 pro")
    assert result.normalized_query == "iPhone 17 Pro"
