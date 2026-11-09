from pathlib import Path

import joblib
import pandas as pd
import sklearn

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import (
    StratifiedKFold,
    cross_validate,
    cross_val_predict,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


ML_DIR = Path(__file__).resolve().parent
DATA_PATH = ML_DIR / "style_training_data.csv"
MODEL_PATH = ML_DIR / "style_random_forest.joblib"

FEATURES = [
    "silhouette",
    "details",
    "impression",
    "styling_approach",
    "statement_level",
    "palette",
]

TARGET = "target_style"


# --------------------------------------------------
# 1. Load and validate the training data
# --------------------------------------------------

data = pd.read_csv(DATA_PATH)

required_columns = FEATURES + [TARGET]
missing_columns = set(required_columns) - set(data.columns)

if missing_columns:
    raise ValueError(
        f"CSV is missing columns: {sorted(missing_columns)}"
    )

if data[required_columns].isnull().any().any():
    raise ValueError("Training data contains empty values")

if data.duplicated(subset=FEATURES).any():
    raise ValueError("Training data contains duplicate quiz-answer combinations")


X = data[FEATURES]
y = data[TARGET]

print(f"Loaded {len(data)} examples")

print("\nExamples per style:")
print(y.value_counts())


# --------------------------------------------------
# 2. Create the Random Forest pipeline
# --------------------------------------------------

pipeline = Pipeline([
    (
        "encoder",
        OneHotEncoder(handle_unknown="ignore"),
    ),
    (
        "classifier",
        RandomForestClassifier(
            n_estimators=200,
            max_depth=5,
            min_samples_leaf=2,
            max_features="sqrt",
            random_state=42,
            n_jobs=-1,
        ),
    ),
])


# --------------------------------------------------
# 3. Evaluate with five-fold cross-validation
# --------------------------------------------------

cross_validation = StratifiedKFold(
    n_splits=5,
    shuffle=True,
    random_state=42,
)

scores = cross_validate(
    pipeline,
    X,
    y,
    cv=cross_validation,
    scoring={
        "accuracy": "accuracy",
        "macro_f1": "f1_macro",
    },
    return_train_score=True,
)

print("\nCross-validation results:")

print(
    "Validation accuracy:",
    round(scores["test_accuracy"].mean(), 3),
    "+/-",
    round(scores["test_accuracy"].std(), 3),
)

print(
    "Validation macro F1:",
    round(scores["test_macro_f1"].mean(), 3),
    "+/-",
    round(scores["test_macro_f1"].std(), 3),
)

print(
    "Training accuracy:",
    round(scores["train_accuracy"].mean(), 3),
)


# Get one cross-validated prediction for every CSV row
predictions = cross_val_predict(
    pipeline,
    X,
    y,
    cv=cross_validation,
)

labels = sorted(y.unique())

print("\nOverall cross-validated accuracy:")
print(round(accuracy_score(y, predictions), 3))

print("\nOverall cross-validated macro F1:")
print(round(f1_score(y, predictions, average="macro"), 3))

print("\nClassification report:")
print(
    classification_report(
        y,
        predictions,
        labels=labels,
        zero_division=0,
    )
)

print("\nConfusion matrix labels:")
print(labels)

print("\nConfusion matrix:")
print(
    confusion_matrix(
        y,
        predictions,
        labels=labels,
    )
)


# --------------------------------------------------
# 4. Train the final model on all 50 examples
# --------------------------------------------------

pipeline.fit(X, y)


# --------------------------------------------------
# 5. Save the fitted pipeline
# --------------------------------------------------

artifact = {
    "model": pipeline,
    "features": FEATURES,
    "labels": labels,
    "model_version": "1.0",
    "model_type": "RandomForestClassifier",
    "training_rows": len(data),
    "sklearn_version": sklearn.__version__,
}

joblib.dump(artifact, MODEL_PATH)

print(f"\nSaved model to: {MODEL_PATH}")


# --------------------------------------------------
# 6. Smoke-test the saved model
# --------------------------------------------------

loaded_artifact = joblib.load(MODEL_PATH)

sample_answers = pd.DataFrame([{
    "silhouette": "sculptural_asymmetric",
    "details": "experimental_details",
    "impression": "bold_unforgettable",
    "styling_approach": "unexpected_contrast",
    "statement_level": "high",
    "palette": "neutral",
}])

saved_model = loaded_artifact["model"]

predicted_style = saved_model.predict(sample_answers)[0]
probabilities = saved_model.predict_proba(sample_answers)[0]

classes = saved_model.named_steps["classifier"].classes_

print("\nSmoke-test prediction:")
print(predicted_style)

print("\nStyle probabilities:")

for style, probability in sorted(
    zip(classes, probabilities),
    key=lambda item: item[1],
    reverse=True,
):
    print(f"{style}: {probability:.1%}")