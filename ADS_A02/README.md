# ADS_A02 - 🎼 ADS Homework A02 - SUTMusic Predictive Modeling

## Overview
This repository contains the second homework assignment (`ADS_A02`) for the Applied Data Science course. It continues the analysis of the SUTMusic dataset, focusing exclusively on **Predictive Modeling** across continuous, binary, and multiclass targets.

## Project Structure
- `data/`: Contains raw, external, and processed data (`reg_tracks.csv`, etc.). Note: Large data files are git-ignored.
- `src/`: Reusable Python modules containing our robust data preprocessing pipelines and feature engineering specifically built for regression/classification stability.
- `notebooks/`: Jupyter notebooks (`02_Main_Analysis.ipynb`) containing the principal predictive analysis, tuning, and evaluation frameworks.
- `pre_provided/`: Provided resources and homework instructions.

## Analysis Portions

### 1️⃣ Regression Methods
Predicting continuous target variables (such as track total reactions/popularity) utilizing:
- Linear Regression (Baseline)
- Ridge & Lasso Regression (L2 / L1 Regularization)
- Kernel Ridge Regression
- Decision Tree Regressors

### 2️⃣ Binary Classification Methods
Grouping tracks into binary states of "Popular" vs "Not Popular" utilizing threshold modeling and evaluating with Confusion Matrices and ROC/AUC across:
- Logistic Regression
- Support Vector Machines (Linear & Kernel RBF)
- K-Nearest Neighbors (Tuned `k`)
- Decision Trees (Tuned `max_depth`)
- Random Forest 

### 3️⃣ Multiclass Classification & Boosting
Splitting tracks into 4 distinct groups (`Neutral`, `Loved`, `Hated`, `Controversial`) via reactions/likes/dislikes ratios to test multi-label capacities:
- Multiclass SVM & Logistic Regression (OVR / Multinomial)
- Tuned Multiclass KNN & Decision Trees
- **Advanced Ensemble & Boosting Methods:** Random Forest, XGBoost, LightGBM, AdaBoost, and CatBoost.
- Focus on `Macro F1-Score`, `Log Loss`, and Class-specific precision metrics.

### 4️⃣ Theoretical Discussions
Deep theoretical dives into the math and rationale driving the implementations (Bias-Variance tradeoff, MAPE unreliability, Overfitting constraints, Macro vs Micro variations).

## Instructions to Run
1. Install dependencies: `pip install -r requirements.txt`
2. Make sure you have exported your extracted dataset into the `data/raw` folder.
3. Run the main notebook located at `notebooks/02_Main_Analysis.ipynb`

## About the Data
The dataset contains historical records from the SUTMusic ecosystem spanning a full year (May 2024 to May 2025). It has been carefully structured through `pandas` data engineering to collapse complicated JSON string arrays into clean integer parameters for the estimators. 
