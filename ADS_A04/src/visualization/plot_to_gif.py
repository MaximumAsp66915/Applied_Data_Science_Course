import os
import torch
import numpy as np
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from torch.utils.data import TensorDataset, DataLoader
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
from src.modeling.mlp import GeneralBinaryMLP, evaluate_predictions

def generate_regression_gif(model, data_loader, criterion, optimizer, epochs=50, filename="regression_progress.gif", fps=5, device="cpu"):
    """
    Trains a regression model while tracking predictions at each epoch,
    then saves an animated GIF of a PERFECTLY SQUARE 'Predicted vs Actual' scatter plot.
    """
    model = model.to(device)
    epoch_predictions = []
    
    # Extract ground truths from DataLoader once for plotting
    all_trues = []
    for _, batch_y in data_loader:
        all_trues.extend(batch_y.numpy() if isinstance(batch_y, torch.Tensor) else batch_y)
    y_true = np.array(all_trues).squeeze()

    print("⚡ Training model and capturing epoch milestones...")
    for epoch in range(epochs):
        model.train()
        for batch_X, batch_y in data_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch_X), batch_y)
            loss.backward()
            optimizer.step()
            
        model.eval()
        epoch_preds = []
        with torch.no_grad():
            for batch_X, _ in data_loader:
                batch_X = batch_X.to(device)
                preds = model(batch_X)
                epoch_preds.extend(preds.cpu().numpy())
        epoch_predictions.append(np.array(epoch_preds).squeeze())

    # Setup a True Square Figure Grid Canvas
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ideal_min, ideal_max = y_true.min(), y_true.max()
    
    ax.set_xlim(ideal_min * 1.1, ideal_max * 1.1)
    ax.set_ylim(ideal_min * 1.1, ideal_max * 1.1)
    ax.set_xlabel('Actual Values', fontweight='bold')
    ax.set_ylabel('Predicted Values', fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    ax.plot([ideal_min, ideal_max], [ideal_min, ideal_max], 'r--', lw=2, label='Ideal Fit')
    scatter = ax.scatter([], [], alpha=0.6, color='#2ca02c', edgecolors='k', s=25)
    
    title_text = ax.set_title("", fontsize=11, fontweight='bold')
    
    metric_text = ax.text(0.05, 0.80, "", transform=ax.transAxes, 
                          bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))
    ax.legend(loc='lower right')
    
    plt.tight_layout(pad=2.0)

    # Animation Frame Update Routine
    def update(frame):
        y_pred = epoch_predictions[frame]
        data = np.vstack((y_true, y_pred)).T
        scatter.set_offsets(data)
        
        mse = np.mean((y_true - y_pred) ** 2)
        mae = np.mean(np.abs(y_true - y_pred))
        
        title_text.set_text(f"Predicted vs. Actual (Epoch {frame + 1}/{epochs})")
        metric_text.set_text(f"MSE: {mse:.4f}\nMAE: {mae:.4f}")
        return scatter, title_text, metric_text

    print("🎬 Generating repeatable square GIF frames...")
    anim = FuncAnimation(fig, update, frames=epochs, blit=True)
    anim.save(filename, writer='pillow', fps=fps, metadata={'loop': 0})
    plt.close(fig)
    print(f"💾 Animation saved successfully as: {os.path.abspath(filename)}")

# --------------------------------------------------------------------------
# 🏃 Execution Sequence
# --------------------------------------------------------------------------
X_sample = np.random.randn(500, 10).astype(np.float32)
y_sample_reg = np.random.randn(500, 1).astype(np.float32)

reg_loader = DataLoader(
    TensorDataset(torch.tensor(X_sample), torch.tensor(y_sample_reg)), 
    batch_size=32, 
    shuffle=False
)

print("⚙️ Initializing Core Regression Model Loop...")
reg_model = GeneralRegressionMLP(input_dim=10)
optimizer_reg = optim.Adam(reg_model.parameters(), lr=0.01)

generate_regression_gif(
    model=reg_model,
    data_loader=reg_loader,
    criterion=nn.MSELoss(),
    optimizer=optimizer_reg,
    epochs=50,                  
    filename="regression_progress.gif",
    fps=10,                      
    device=device
)

evaluate_predictions(reg_model, reg_loader, task_type="regression", device=device)


def generate_classification_gif(model, data_loader, criterion, optimizer, epochs=50, filename="binary_progress.gif", fps=5, device="cpu"):
    """
    Trains a binary classification model while tracking predictions at each epoch,
    then saves an animated GIF of a PERFECTLY SQUARE 2x2 Confusion Matrix.
    """
    model = model.to(device)
    epoch_predictions = []
    
    # Extract ground truths from DataLoader once for computing metrics
    all_trues = []
    for _, batch_y in data_loader:
        all_trues.extend(batch_y.numpy() if isinstance(batch_y, torch.Tensor) else batch_y)
    y_true = np.array(all_trues).squeeze()

    print("⚡ Training model and capturing classification milestones...")
    for epoch in range(epochs):
        # Standard training cycle
        model.train()
        for batch_X, batch_y in data_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(batch_X), batch_y)
            loss.backward()
            optimizer.step()
            
        # Evaluation snapshot at the end of the current epoch
        model.eval()
        epoch_preds = []
        with torch.no_grad():
            for batch_X, _ in data_loader:
                batch_X = batch_X.to(device)
                preds = model(batch_X)
                epoch_preds.extend(preds.cpu().numpy())
        epoch_predictions.append(np.array(epoch_preds).squeeze())

    # Setup a True Square Figure Grid Canvas
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    plt.tight_layout(pad=3.0)

    # Animation Frame Update Routine
    def update(frame):
        ax.clear()  # Clear axes to redraw text matrices perfectly without overlays
        
        y_pred = epoch_predictions[frame]
        # Convert floating probabilities to discrete 0/1 predictions
        y_pred_classes = (y_pred >= 0.5).astype(int)
        
        # Calculate 2x2 confusion parameters
        cm = confusion_matrix(y_true, y_pred_classes, labels=[0, 1])
        
        # Draw the updated confusion matrix onto the clear axis frame
        disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=[0, 1])
        disp.plot(ax=ax, cmap='Blues', values_format='d', colorbar=False)
        
        # Style boundaries and add annotations frame-by-frame
        ax.set_title(f"🔮 2x2 Confusion Matrix (Epoch {frame + 1}/{epochs})", fontsize=11, fontweight='bold', pad=10)
        ax.set_xlabel('Predicted Label', fontweight='bold')
        ax.set_ylabel('True Label', fontweight='bold')
        
        return ax.images + ax.texts

    print("🎬 Generating repeatable square classification GIF frames...")
    anim = FuncAnimation(fig, update, frames=epochs, blit=False)
    
    # Save loop configuration safely via metadata dictionary isolation
    anim.save(filename, writer='pillow', fps=fps, metadata={'loop': 0})
    plt.close(fig)
    print(f"💾 Animation saved successfully as: {os.path.abspath(filename)}")

# --------------------------------------------------------------------------
# 🏃 Execution Sequence
# --------------------------------------------------------------------------
X_sample = np.random.randn(500, 10).astype(np.float32)
y_sample_bin = np.random.randint(0, 2, size=(500, 1)).astype(np.float32)

bin_loader = DataLoader(
    TensorDataset(torch.tensor(X_sample), torch.tensor(y_sample_bin)), 
    batch_size=32, 
    shuffle=False
)

print("⚙️ Initializing Core Binary Model Loop...")
bin_model = GeneralBinaryMLP(input_dim=10)
optimizer_bin = optim.Adam(bin_model.parameters(), lr=0.01)

generate_classification_gif(
    model=bin_model,
    data_loader=bin_loader,
    criterion=nn.BCELoss(),
    optimizer=optimizer_bin,
    epochs=50,                  
    filename="binary_progress.gif",
    fps=8,                      
    device=device
)

evaluate_predictions(bin_model, bin_loader, task_type="binary", device=device)