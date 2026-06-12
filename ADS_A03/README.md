# ADS_A03 - 🎼 Deep Learning & Neural Networks

## Overview
This repository contains the third homework assignment for the Applied Data Science course. The notebook focuses on **deep learning workflows**, with an emphasis on understanding how modern neural network architectures behave rather than training large models for the sake of it.

The main notebook, [03_Main_Analysis.ipynb](notebooks/03_Main_Analysis.ipynb), is organized into five major sections:

1. **Multilayer Perceptron (MLP)** for binary classification and regression
2. **Convolutional Neural Networks (CNNs)** for image modeling
3. **Recurrent Neural Networks (RNNs)** with Vanilla RNN, LSTM, and GRU models
4. **Transformer-based models** using attention architectures
5. **Bonus research review** on machine learning models used in industry

The notebook is written to be readable, modular, and easy to extend. Larger training and utility code is kept in the `src/` folder instead of being embedded directly in the notebook.

## What’s Included

- Clean notebook structure with section and subsection headings
- PyTorch-based deep learning experiments
- Training and validation curves for model comparison
- Experiments on optimization, architecture, regularization, augmentation, and transfer learning
- A bonus industry research section with short written analysis

## Project Structure

- `data/`: Raw, external, and processed datasets
- `notebooks/`: The main analysis notebook and supporting notebooks
- `src/`: Reusable code for modeling, preprocessing, visualization, and collection utilities
- `pre_provided/`: Course-provided material and supporting resources
- `requirements.txt`: Python dependencies for the project

## Main Notebook Sections

### 1️⃣ Multilayer Perceptron (MLP)
Binary classification and regression experiments using fully connected networks. This section also covers optimizer choices, learning-rate behavior, depth/width changes, activation functions, normalization, dropout, and other regularization techniques. 🧠

### 2️⃣ Convolutional Neural Networks (CNNs)
Image modeling experiments using a custom CNN and transfer learning. This section includes kernel size, stride, pooling, depth, data augmentation, and pretrained model comparisons. 🖼️

### 3️⃣ Recurrent Neural Networks (RNNs)
Sequence modeling experiments with Vanilla RNN, LSTM, and GRU. The notebook compares sequence length, hidden size, stacked layers, bidirectionality, and dropout. ⏳

### 4️⃣ Transformer Models
Attention-based sequence modeling using a transformer encoder approach. This section compares Transformer behavior with recurrent models and discusses self-attention, positional encoding, and computational trade-offs. 🤖

### 5️⃣ Bonus: Research Review
A short industry-oriented review on the machine learning models most widely used in practice, plus a forward-looking discussion about how that distribution may change over the next 5–10 years. 🎖️

## How to Run

1. Install the dependencies:
	```bash
	pip install -r requirements.txt
	```
2. Make sure the expected datasets are available inside the `data/` directory; In case some where missing due to their size the download link for them is provided inside the notebook like:

<p align="center">
  <a href="https://www.kaggle.com/datasets/puneet6060/intel-image-classification"><img src="https://img.shields.io/badge/Kaggle-View_Dataset-blue?logo=Kaggle&logoColor=white" alt="View on Kaggle"></a>
  <a href="https://www.kaggle.com/datasets/isaaclopgu/nvidia-stock-data-daily-updated"><img src="https://img.shields.io/badge/Kaggle-View_Dataset-blue?logo=Kaggle&logoColor=white" alt="View on Kaggle"></a>
</p>

3. Open and run [03_Main_Analysis.ipynb](notebooks/03_Main_Analysis.ipynb).

## Notes

- PyTorch is used as the main deep learning framework in this homework.
- The notebook assumes a local environment with standard scientific Python packages installed.
- Some sections are intentionally modular so that heavier code can be moved into `src/modeling`, `src/preprocessing`, or `src/visualization` as the project grows.
- You are advised to use `GPU` for training the models inside this document especially for the `CNN` section.
- Some sections need heavy training so they might take a long time to train some models, Be Patient!
- Some numbers that are reported in the document might change with the new run, but the whole concpet would remain the same.

## Dataset Scope

1. **Tracks Dataset**: The notebook uses course data already prepared in earlier homeworks for the MLP section, and separate image and sequence datasets for the CNN and RNN/Transformer sections. This keeps the assignment focused on model behavior, architecture changes, and interpretation rather than data collection.
2. **Image Dataset**: From kaggle, and has been used for the `2th section`.
3. **Nvidia Stock Price Dataset**: Again from kaggle, and has been used for the `2th section`.


