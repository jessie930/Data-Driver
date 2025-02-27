import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.ensemble import RandomForestRegressor
from skl2onnx import to_onnx
from sklearn.metrics import make_scorer
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import StackingRegressor
from preprocessor import preprocess
from scorer import within_25_percent

FOLDER_PATHS = ["../data/training_data/video-144821", "../data/training_data/video-145043",
                "../data/training_data/video-145233", "../data/training_data/video-145641", "../data/training_data/video-150001"]
TEST_VIDEO_INDEX = None  # use n:th video for testing, or None to train on all videos

if TEST_VIDEO_INDEX is not None:
    test_video_path = FOLDER_PATHS[TEST_VIDEO_INDEX]
    del FOLDER_PATHS[TEST_VIDEO_INDEX]

with open("../data/config/sensor_whitelist.txt") as f:
    SENSOR_WHITELIST = f.read().splitlines()

dfs = [preprocess(path) for path in FOLDER_PATHS]
X_train = pd.concat(dfs, axis=0, ignore_index=True)
X_train.fillna(X_train.mean(), inplace=True)
y_train = X_train["groundSteering"]
X_train = X_train.filter(SENSOR_WHITELIST, axis=1)


if TEST_VIDEO_INDEX is not None:
    X_test = preprocess(test_video_path)
    X_test.fillna(X_test.mean(), inplace=True)
    y_test = X_test["groundSteering"]
    X_test = X_test.filter(SENSOR_WHITELIST, axis=1)

columns = X_train.columns
print("Columns used:")
print(columns)

param_grid = {
    'n_estimators': [100, 250, 500, 750],
    'max_depth': [None, 10, 20, 30],
    'min_samples_split': [2, 5, 10],
    'min_samples_leaf': [1, 2, 4]
}

X_train = X_train.to_numpy().astype(np.float32)

if TEST_VIDEO_INDEX is not None:
    X_test = X_test.to_numpy().astype(np.float32)

clr = RandomForestRegressor(random_state=42)

within_25pct_scorer = make_scorer(within_25_percent)
grid_search = GridSearchCV(
    estimator=clr, param_grid=param_grid, cv=2, scoring=within_25pct_scorer, verbose=1, n_jobs=-1)
grid_search.fit(X_train, y_train)


best_params = grid_search.best_params_
best_score = grid_search.best_score_

print("Best Parameters:", best_params)
print("Best Score (R^2):", best_score)

best_clr = grid_search.best_estimator_

print("Feature importance (most important first):")
col_importance_pair = sorted(zip(
    columns, best_clr.feature_importances_), key=lambda pair: pair[1], reverse=True)
for col, importance in col_importance_pair:
    print(f"Feature '{col}': {round(importance, 4)}")

stacked_model = StackingRegressor(
    estimators=[('rf', best_clr)],
    final_estimator=LinearRegression()
)

stacked_model.fit(X_train, y_train)

# export model to disk
onx = to_onnx(stacked_model, X_train)
with open("/app/model_output/clr.onnx", "wb") as f:
    f.write(onx.SerializeToString())

if TEST_VIDEO_INDEX is not None:
    y_pred = stacked_model.predict(X_test)
    accuracy = stacked_model.score(X_test, y_test)
    print("Accuracy:", accuracy)

    in_bounds_counter = 0
    for pred, actual in zip(y_pred, y_test):
        if actual == 0.0:
            continue

        lower_bound = min(actual * 0.75, actual * 1.25)
        upper_bound = max(actual * 0.75, actual * 1.25)

        if lower_bound < pred < upper_bound:
            in_bounds_counter += 1

    print("====================")
    print(f"{in_bounds_counter}/{len(y_test)} ({round(in_bounds_counter/len(y_test) * 100, 2)}%) of predictions (!= 0) are within 25% of the actual value")
    print("====================")
else:
    print("Not using any test data. Used all data to train to the model")
