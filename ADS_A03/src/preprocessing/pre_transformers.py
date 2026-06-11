import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader
from sklearn.preprocessing import MinMaxScaler

def prepare_transformer_datasets(df, lookback=30, batch_size=128):
    """Isolates, scales, and windows multivariate frames into strict tensor splits."""
    target_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    raw_arrays = df[target_columns].dropna().values
    
    # Isolate training split to guarantee zero scale data leakage
    split_boundary = int(len(raw_arrays) * 0.8)
    
    scaler = MinMaxScaler()
    scaled_train = scaler.fit_transform(raw_arrays[:split_boundary])
    scaled_val = scaler.transform(raw_arrays[split_boundary:])
    full_scaled = np.vstack([scaled_train, scaled_val])
    
    # Standard sliding target window allocation
    X, y = [], []
    for i in range(len(full_scaled) - lookback):
        X.append(full_scaled[i : i + lookback])
        y.append(full_scaled[i + lookback, 3])  # Target index 3 corresponds to Close price
        
    X, y = torch.FloatTensor(np.array(X)), torch.FloatTensor(np.array(y))
    
    # Re-verify clean shapes
    train_ds = TensorDataset(X[:split_boundary], y[:split_boundary])
    val_ds = TensorDataset(X[split_boundary:], y[split_boundary:])
    
    return (
        DataLoader(train_ds, batch_size=batch_size, shuffle=False),
        DataLoader(val_ds, batch_size=batch_size, shuffle=False)
    )