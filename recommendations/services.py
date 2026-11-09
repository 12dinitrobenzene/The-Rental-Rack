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
