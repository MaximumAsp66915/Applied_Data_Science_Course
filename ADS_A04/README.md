# ADS_A04 - Modern Data Science Workflows

## Overview
This repository contains the fourth homework for the Applied Data Science course. The notebook focuses on **modern data science workflows** with an emphasis on clear notebook structure, reproducible experiments, and short explanations before each task.

The main notebook, [04_Main_Analysis.ipynb](notebooks/04_Main_Analysis.ipynb), follows the Assignment 4 specification and is organized into six major sections:

1. **ML Pipelines** for cleaning, preprocessing, imputation, and end-to-end classification
2. **Handling Imbalanced Data** with undersampling, oversampling, SMOTE, and class weights
3. **Variational Autoencoders (VAEs)** for image generation and latent-space analysis
4. **GANs** for MNIST generation and training diagnostics
5. **Diffusion Models** with linear vs cosine noise schedules
6. **Explainable AI (XAI)** with Grad-CAM, SHAP, LIME, and ELI5

The notebook is intentionally modular. Classical ML tasks use `pandas` and `scikit-learn`, imbalance handling uses `imbalanced-learn`, and the generative/XAI parts rely on `PyTorch` and image-based explainability tools.

## What’s Included

- Data loading and custom cleaning with `pandas.pipe`
- Validation-aware preprocessing with `ColumnTransformer`, `Pipeline`, and imputers
- Comparison of mean, median, KNN, and iterative imputation
- Undersampling, oversampling, SMOTE, and cost-sensitive learning experiments
- VAE, GAN, and DDPM implementations on small image datasets
- Grad-CAM, SHAP, LIME, and ELI5 analysis for CNN behavior
- Saved pipeline/model artifacts where needed

## Main Notebook Sections

### 1️⃣ ML Pipelines
This section covers the full supervised-learning workflow:

- load and validate the raw dataset
- clean data with custom pandas functions and `pipe`
- separate numeric and categorical features
- build preprocessing with `ColumnTransformer`
- compare imputation strategies: mean, median, KNN, iterative
- attach a classifier to the pipeline
- train, evaluate, and save the complete pipeline

Recommended approach: keep the classifier simple and reliable, such as `RandomForestClassifier` or `LogisticRegression`, so the focus stays on the pipeline itself.

### 2️⃣ Handling Imbalanced Data
This section compares four imbalance strategies:

- random undersampling
- random oversampling
- SMOTE
- cost-sensitive learning with `class_weight`

Recommended approach: use an `imblearn.pipeline.Pipeline` so resampling happens only inside training folds. Report recall, F1-score, PR-AUC, and the confusion matrix instead of relying on accuracy.

### 3️⃣ Variational Autoencoders
This section implements a VAE on a small image dataset:

- build encoder, latent space, and decoder
- implement the reparameterization trick
- train a baseline VAE and a beta-VAE variant
- compare KL weights and reconstruction quality
- sample from latent space and interpolate between latent vectors

Recommended approach: use `MNIST` or `Fashion-MNIST` with `PyTorch`. These datasets are fast, stable, and easy to visualize.

### 4️⃣ GANs
This section builds a simple GAN on MNIST:

- implement generator and discriminator
- write the alternating training loop
- track generator/discriminator losses
- save and visualize generated samples across epochs
- discuss mode collapse and training instability

Recommended approach: use a lightweight DCGAN-style model in `PyTorch`. Keep the architecture small and the number of epochs modest.

### 5️⃣ Diffusion Models
This section implements a simplified DDPM:

- define the forward noising process
- build a small denoising network
- compare linear and cosine noise schedules
- sample intermediate reverse-diffusion steps
- compare diffusion models with GANs

Recommended approach: again use a compact `PyTorch` implementation on MNIST. Keep timestep count and model size small so the notebook remains runnable.

### 6️⃣ Explainable AI (XAI)
This section explains the CNN from the previous homework:

- load the trained CNN from Assignment 3
- implement Grad-CAM for correct and incorrect predictions
- analyze at least three misclassified images
- apply SHAP, LIME, and ELI5 where practical
- summarize what the model focuses on and why failures happen

Recommended approach: make Grad-CAM the main explanation method, then add LIME and SHAP on a small subset. If ELI5 is awkward on raw images, use it through a surrogate or latent-feature representation.

## Libraries Used

- `pandas`, `numpy` for data handling and analysis
- `scikit-learn` for preprocessing, models, imputation, and evaluation
- `imbalanced-learn` for undersampling, oversampling, and SMOTE
- `joblib` for saving/loading pipelines
- `matplotlib`, `seaborn`, optional `plotly` for plots
- `torch`, `torchvision` for VAE, GAN, and diffusion models
- `shap`, `lime`, `eli5`, `cv2` for explainability and visualization

## Project Structure

- `data/`: raw and processed datasets
- `figs/`: saved figures and visual outputs
- `notebooks/`: the main notebook and supporting notebooks
- `src/`: reusable code for modeling, preprocessing, visualization, and utilities
- `pre_provided/`: course-provided resources
- `requirements.txt`: Python dependencies

## How to Run

1. Install dependencies:

	 ```bash
	 pip install -r requirements.txt
	 ```

2. Make sure the datasets referenced in the notebook are available in `data/`. The notebook uses the course data already available in this repository, plus small image datasets such as MNIST for generative modeling.

3. Open and run [04_Main_Analysis.ipynb](notebooks/04_Main_Analysis.ipynb).

## Notes

- The notebook is written to be explanatory as well as functional, because the assignment asks for both code and natural-language reasoning.
- PyTorch is used for the generative and explainability-heavy parts because it keeps the implementation flexible.
- Some sections are intentionally lightweight to avoid unnecessary training time.
- Results may vary slightly across runs because of randomness, but the workflow and conclusions should remain the same.

## Dataset Scope

1. **Course tabular data**: used for the ML pipeline and imbalance-handling sections.
2. **MNIST or Fashion-MNIST**: used for VAE, GAN, and diffusion experiments.
3. **CNN data from the previous homework**: reused for Grad-CAM and other XAI methods.

## Assignment Focus

The notebook is designed to show:

- how to build a clean end-to-end ML pipeline
- how imbalance handling changes model behavior
- how basic generative models behave in practice
- how to explain CNN predictions with visual and model-agnostic methods

The goal is not maximum training time or model size. The goal is a clear, defensible, and well-documented homework notebook.


