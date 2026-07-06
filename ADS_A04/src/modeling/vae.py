import torch.nn as nn
import torch

# ----------------------------------------------------------------
# Variational Autoencoder Class Definition
# ----------------------------------------------------------------
class VariationalAutoencoder(nn.Module):
    def __init__(self, input_dim=784, hidden_dim=400, latent_dim=20):
        super(VariationalAutoencoder, self).__init__()
        
        # Encoder Network Layers
        self.encoder_hidden = nn.Linear(input_dim, hidden_dim)
        self.fc_mu = nn.Linear(hidden_dim, latent_dim)
        self.fc_logvar = nn.Linear(hidden_dim, latent_dim)
        
        # Decoder Network Layers
        self.decoder_hidden = nn.Linear(latent_dim, hidden_dim)
        self.decoder_output = nn.Linear(hidden_dim, input_dim)
        
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()

    def encode(self, x):
        h = self.relu(self.encoder_hidden(x))
        return self.fc_mu(h), self.fc_logvar(h)

    def reparameterize(self, mu, logvar):
        """
        Reparameterization Trick: samples standard normal epsilon and transforms
        to retain backpropagation gradients through stochastic layers.
        """
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z):
        h = self.relu(self.decoder_hidden(z))
        return self.sigmoid(self.decoder_output(h))

    def forward(self, x):
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        return self.decode(z), mu, logvar

# Loss Calculation Helper Engine
def vae_loss_function(recon_x, x, mu, logvar, beta=1.0):
    """
    Computes standard Evidence Lower Bound (ELBO) tracking with an explicit 
    beta scaling factor for structural regularization experiments.
    """
    # Binary Cross Entropy acting as reconstruction loss
    BCE = nn.functional.binary_cross_entropy(recon_x, x, reduction='sum')
    
    # Kullback-Leibler Divergence tracking distribution constraints
    KLD = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())
    
    return BCE + beta * KLD, BCE, KLD