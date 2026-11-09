from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from django.conf import settings


MODEL_PATH = (
    Path(settings.BASE_DIR)
    / "recommendations"
    / "ml"
    / "style_random_forest.joblib"
)

EXPECTED_FEATURES = (
    "silhouette",
    "details",
    "impression",
    "styling_approach",
    "statement_level",
    "palette",
)

EXPECTED_LABELS = {
    "minimalist_clean",
    "classic_polished",
    "urban_streetwear",
    "romantic_expressive",
    "avant_garde_statement",
}

PREDICTED_STYLE_WEIGHT = 100
WISHLIST_WEIGHT = 30
COMPLETED_STYLE_WEIGHT = 10
MAX_COMPLETED_STYLE_SCORE = 30
PRODUCT_VIEW_WEIGHT = 2
MAX_PRODUCT_VIEW_SCORE = 10


class StyleModelError(RuntimeError):
    """Raised when the trusted style model cannot be used."""


@lru_cache(maxsize=1)
def load_style_artifact():
    if not MODEL_PATH.exists():
        raise StyleModelError(
            f"Style model is missing: {MODEL_PATH}"
        )

    try:
        artifact = joblib.load(MODEL_PATH)
    except Exception as error:
        raise StyleModelError(
            "The style model could not be loaded."
        ) from error

    required_keys = {
        "model",
        "features",
        "labels",
        "model_version",
    }

    if not isinstance(artifact, dict) or not required_keys.issubset(artifact):
        raise StyleModelError(
            "The style model artifact is incomplete."
        )

    if tuple(artifact["features"]) != EXPECTED_FEATURES:
        raise StyleModelError(
            "The model feature contract does not match the quiz."
        )

    if set(artifact["labels"]) != EXPECTED_LABELS:
        raise StyleModelError(
            "The model label contract does not match StyleTag."
        )

    return artifact


def predict_style(cleaned_data):
    artifact = load_style_artifact()
    features = artifact["features"]

    missing_features = [
        feature
        for feature in features
        if feature not in cleaned_data
    ]

    if missing_features:
        raise StyleModelError(
            f"Missing quiz features: {missing_features}"
        )

    model_input = pd.DataFrame(
        [
            {
                feature: cleaned_data[feature]
                for feature in features
            }
        ],
        columns=features,
    )

    prediction = str(
        artifact["model"].predict(model_input)[0]
    )

    if prediction not in artifact["labels"]:
        raise StyleModelError(
            "The model returned an unsupported style."
        )

    return {
        "style": prediction,
        "model_version": artifact["model_version"],
    }


def recommendation_score(
    product,
    *,
    predicted_style_id,
    view_count=0,
    completed_style_ids=frozenset(),
    wishlisted=False,
):
    style_ids = {
        style_tag.pk
        for style_tag in product.style_tags.all()
    }
    score = 0

    if predicted_style_id in style_ids:
        score += PREDICTED_STYLE_WEIGHT

    if wishlisted:
        score += WISHLIST_WEIGHT

    completed_matches = len(style_ids & set(completed_style_ids))
    score += min(
        completed_matches * COMPLETED_STYLE_WEIGHT,
        MAX_COMPLETED_STYLE_SCORE,
    )
    score += min(
        view_count * PRODUCT_VIEW_WEIGHT,
        MAX_PRODUCT_VIEW_SCORE,
    )
    return score


def rank_recommended_products(
    products,
    *,
    predicted_style_id,
    view_counts=None,
    completed_style_ids=None,
    wishlist_product_ids=None,
    limit=8,
):
    view_counts = view_counts or {}
    completed_style_ids = set(completed_style_ids or ())
    wishlist_product_ids = set(wishlist_product_ids or ())
    scored_products = []

    for product in products:
        score = recommendation_score(
            product,
            predicted_style_id=predicted_style_id,
            view_count=view_counts.get(product.pk, 0),
            completed_style_ids=completed_style_ids,
            wishlisted=product.pk in wishlist_product_ids,
        )

        if score > 0:
            scored_products.append((score, product))

    scored_products.sort(
        key=lambda entry: (
            entry[0],
            entry[1].created_at,
            entry[1].pk,
        ),
        reverse=True,
    )
    return [product for _, product in scored_products[:limit]]
