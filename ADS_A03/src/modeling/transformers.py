import torch
import torch.nn as nn
import math

class PositionalEncoding(nn.Module):
    """Injects geometric time context vectors into sequence embeddings."""
    def __init__(self, d_model, max_len=1000):
        super(PositionalEncoding, self).__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # Shape: [1, max_len, d_model]
        self.register_buffer('pe', pe)

    def forward(self, x):
        # x shape: [Batch, SeqLen, d_model]
        return x + self.pe[:, :x.size(1), :]

class StockTransformerSequencer(nn.Module):
    """Transformer Encoder variant optimized for low-dimensional tabular temporal sequences."""
    def __init__(self, input_size=5, d_model=64, nhead=4, num_layers=2, dim_feedforward=128, dropout=0.1):
        super(StockTransformerSequencer, self).__init__()
        self.rnn_type = "TRANSFORMER"  # Retained for tracking pipeline compatibility
        self.d_model = d_model
        
        # Linear Projection Head mapping 5 tabular columns to d_model spaces
        self.input_projection = nn.Linear(input_size, d_model)
        self.pos_encoder = PositionalEncoding(d_model)
        
        # Native PyTorch Encoder Layer core stack
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True
        )
        self.transformer_core = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc_head = nn.Linear(d_model, 1)

    def forward(self, x):
        # Shape translation: [Batch, SeqLen, InputSize] -> [Batch, SeqLen, d_model]
        out = self.input_projection(x) * math.sqrt(self.d_model)
        out = self.pos_encoder(out)
        
        # Process global cross-day multi-head attention scores
        out = self.transformer_core(out)
        
        # Extract last index token contextual frame representation
        out = out[:, -1, :]
        return self.fc_head(out).squeeze(-1)