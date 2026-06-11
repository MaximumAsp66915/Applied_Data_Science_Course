import torch
import torch.nn as nn
import torch.optim as optim
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import classification_report, mean_squared_error, r2_score


class GeneralBinaryMLP(nn.Module):
    def __init__(self, input_dim, hidden_layers=[64, 32], activation=nn.ReLU(), use_batch_norm=False, dropout_p=0.0):
        super().__init__()
        layers = []
        in_dim = input_dim
        for h_dim in hidden_layers:
            layers.append(nn.Linear(in_dim, h_dim))
            if use_batch_norm:
                layers.append(nn.BatchNorm1d(h_dim))
            layers.append(activation)
            if dropout_p > 0.0:
                layers.append(nn.Dropout(dropout_p))
            in_dim = h_dim
        layers.append(nn.Linear(in_dim, 1))
        layers.append(nn.Sigmoid())
        self.network = nn.Sequential(*layers)
        
    def forward(self, x):
        return self.network(x)


class GeneralRegressionMLP(nn.Module):
    def __init__(self, input_dim, hidden_layers=[64, 32], activation=nn.ReLU(), use_batch_norm=False, dropout_p=0.0):
        super().__init__()
        layers = []
        in_dim = input_dim
        for h_dim in hidden_layers:
            layers.append(nn.Linear(in_dim, h_dim))
            if use_batch_norm:
                layers.append(nn.BatchNorm1d(h_dim))
            layers.append(activation)
            if dropout_p > 0.0:
                layers.append(nn.Dropout(dropout_p))
            in_dim = h_dim
        layers.append(nn.Linear(in_dim, 1)) # Continuous target
        self.network = nn.Sequential(*layers)
        
    def forward(self, x):
        return self.network(x)


def train_mlp(model,
              train_loader,
              val_loader, 
              criterion, 
              optimizer, 
              epochs=30, 
              scheduler=None, 
              early_stopping_patience=None, 
              l1_lambda=0.0, 
              clip_value=None,
              device=torch.device("cpu")
              ):
    
    """
    A unified training function handling Classification/Regression, GPU acceleration,
    L1 regularization, Gradient Clipping, Early Stopping, and Learning Rate Scheduling.
    """

    model = model.to(device)
    history = {'train_loss': [], 'val_loss': []}
    best_val_loss = float('inf')
    patience_counter = 0
    
    for epoch in range(epochs):
        # --- Training Phase ---
        model.train()
        running_train_loss = 0.0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            
            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            
            # Optional L1 Regularization
            if l1_lambda > 0.0:
                l1_norm = sum(p.abs().sum() for p in model.parameters())
                loss += l1_lambda * l1_norm
                
            loss.backward()
            
            # Optional Gradient Clipping
            if clip_value is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), clip_value)
                
            optimizer.step()
            running_train_loss += loss.item() * batch_x.size(0)
            
        epoch_train_loss = running_train_loss / len(train_loader.dataset)
        history['train_loss'].append(epoch_train_loss)
        
        # --- Validation Phase ---
        model.eval()
        running_val_loss = 0.0
        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                outputs = model(batch_x)
                loss = criterion(outputs, batch_y)
                running_val_loss += loss.item() * batch_x.size(0)
                
        epoch_val_loss = running_val_loss / len(val_loader.dataset)
        history['val_loss'].append(epoch_val_loss)
        
        # Adjust Learning Rate Scheduler
        if scheduler:
            scheduler.step()
            
        # Optional Early Stopping Engine
        if early_stopping_patience is not None:
            if epoch_val_loss < best_val_loss:
                best_val_loss = epoch_val_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= early_stopping_patience:
                    break
                    
    return history

def evaluate_predictions(model,
                         loader, 
                         task_type="binary",
                         device=torch.device("cpu")
                         ):
    """Extracts GPU data back to host CPU to build metrics tables."""
    model.eval()
    all_targets = []
    all_outputs = []
    
    with torch.no_grad():
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(device)
            outputs = model(batch_x)
            all_targets.extend(batch_y.numpy().flatten())
            all_outputs.extend(outputs.cpu().numpy().flatten())
            
    if task_type == "binary":
        preds = [1 if o > 0.5 else 0 for o in all_outputs]
        print("\n📊 Classification Performance Matrix:")
        print(classification_report(all_targets, preds, digits=4))
    else:
        mse = mean_squared_error(all_targets, all_outputs)
        r2 = r2_score(all_targets, all_outputs)
        metrics_df = pd.DataFrame({"Metric": ["MSE", "R² Score"], "Value": [mse, r2]})
        print("\n📈 Regression Metric Summary Table:")
        print(metrics_df.to_string(index=False))