import torch
import torch.nn as nn
from torch.cuda.amp import autocast, GradScaler
import time

class UnifiedStockSequencer(nn.Module):
    def __init__(self, input_size=5, hidden_size=64, num_layers=1, rnn_type="LSTM", bidirectional=False, dropout=0.0):
        super(UnifiedStockSequencer, self).__init__()
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.rnn_type = rnn_type.upper()
        self.bidirectional = bidirectional
        
        # Configure the specified recurrent core network block
        if self.rnn_type == "RNN":
            self.rnn_core = nn.RNN(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        elif self.rnn_type == "GRU":
            self.rnn_core = nn.GRU(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        elif self.rnn_type == "LSTM":
            self.rnn_core = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout if num_layers > 1 else 0.0)
        else:
            raise ValueError("❌ Invalid rnn_type specified. Use 'RNN', 'LSTM', or 'GRU'.")
            
        # Linear map projection head adjusting to directional multiplier properties
        self.direction_multiplier = 2 if bidirectional else 1
        self.fc_head = nn.Linear(hidden_size * self.direction_multiplier, 1)

    def forward(self, x):
        # x shape layout: [Batch Size, Sequence Length, Input Size]
        out, _ = self.rnn_core(x)
        
        # Extract the hidden representations from the final sequential timestep slice
        out = out[:, -1, :]
        
        # Compute the regression output for the next day's closing price
        predictions = self.fc_head(out)
        return predictions.squeeze(-1)
    

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def train_sequence_model(model, train_loader, val_loader, criterion, optimizer, epochs=10):
    model = model.to(device)
    scaler = GradScaler()
    history = {'train_loss': [], 'val_loss': []}
    
    print(f"\n⚡ RNN Engine Active | Core: {model.rnn_type} | Device: {device.type.upper()}")
    
    for epoch in range(epochs):
        epoch_start = time.time()
        model.train()
        running_train_loss = 0.0
        
        for batch_idx, (sequences, targets) in enumerate(train_loader):
            sequences, targets = sequences.to(device), targets.to(device)
            optimizer.zero_grad()
            
            with autocast():
                predictions = model(sequences)
                loss = criterion(predictions, targets)
                
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            
            running_train_loss += loss.item() * sequences.size(0)
            
        epoch_train_loss = running_train_loss / len(train_loader.dataset)
        
        # --- Validation Phase ---
        model.eval()
        running_val_loss = 0.0
        with torch.no_grad():
            for sequences, targets in val_loader:
                sequences, targets = sequences.to(device), targets.to(device)
                with autocast():
                    predictions = model(sequences)
                    loss = criterion(predictions, targets)
                running_val_loss += loss.item() * sequences.size(0)
                
        epoch_val_loss = running_val_loss / len(val_loader.dataset)
        epoch_elapsed = time.time() - epoch_start
        
        print(f"⏳ Epoch {epoch+1:02d}/{epochs:02d} -> Train MSE: {epoch_train_loss:.6f} | Val MSE: {epoch_val_loss:.6f} | Time: {epoch_elapsed:.1f}s")
        
        history['train_loss'].append(epoch_train_loss)
        history['val_loss'].append(epoch_val_loss)
        
    return history