import torch
import numpy as np
import matplotlib.pyplot as plt
import math
import torch.nn as nn

def get_diffusion_schedule(schedule_type="linear", timesteps=200):
    if schedule_type == "linear":
        beta = torch.linspace(1e-4, 0.02, timesteps)
        alpha = 1.0 - beta
        alpha_bar = torch.cumprod(alpha, dim=0)
    elif schedule_type == "cosine":
        steps = timesteps + 1
        x = torch.linspace(0, timesteps, steps)
        s = 0.008
        alphas_cumprod = torch.cos(((x / timesteps) + s) / (1 + s) * math.pi / 2) ** 2
        alphas_cumprod = alphas_cumprod / alphas_cumprod[0]
        betas = 1 - (alphas_cumprod[1:] / alphas_cumprod[:-1])
        beta = torch.clip(betas, 0.0, 0.999)
        alpha = 1.0 - beta
        alpha_bar = alphas_cumprod[1:]
    return beta, alpha, alpha_bar


class SinusoidalPositionEmbeddings(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.dim = dim
    def forward(self, time):
        device = time.device
        half_dim = self.dim // 2
        embeddings = math.log(10000) / (half_dim - 1)
        embeddings = torch.exp(torch.arange(half_dim, device=device) * -embeddings)
        embeddings = time[:, None] * embeddings[None, :]
        embeddings = torch.cat((embeddings.sin(), embeddings.cos()), dim=-1)
        return embeddings

class SimpleDiffusionUNet(nn.Module):
    def __init__(self, in_channels=1, out_channels=1, time_emb_dim=32):
        super().__init__()
        self.time_mlp = nn.Sequential(
            SinusoidalPositionEmbeddings(time_emb_dim),
            nn.Linear(time_emb_dim, time_emb_dim),
            nn.ReLU()
        )
        self.down1 = nn.Conv2d(in_channels, 32, kernel_size=3, padding=1)
        self.down2 = nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1)
        self.up1 = nn.ConvTranspose2d(64, 32, kernel_size=4, stride=2, padding=1)
        self.up2 = nn.Conv2d(64, out_channels, kernel_size=3, padding=1)
        self.act = nn.ReLU()
        self.time_lookup = nn.Linear(time_emb_dim, 64)

    def forward(self, x, t):
        t_emb = self.time_mlp(t)
        h1 = self.act(self.down1(x))
        h2 = self.act(self.down2(h1))
        h2 = h2 + self.time_lookup(t_emb)[..., None, None]
        h3 = self.act(self.up1(h2))
        return self.up2(torch.cat([h3, h1], dim=1))

@torch.no_grad()
def sample_ddpm_trajectory(model, beta, alpha, alpha_bar, device, num_samples=8, T=200):
    model.eval()
    x = torch.randn(num_samples, 1, 28, 28, device=device)
    trajectory = {0: x.cpu()}
    
    for i in reversed(range(T)):
        t = torch.full((num_samples,), i, device=device, dtype=torch.long)
        predicted_noise = model(x, t)
        
        beta_t = beta[i]
        alpha_t = alpha[i]
        alpha_bar_t = alpha_bar[i]
        
        mean = (1 / torch.sqrt(alpha_t)) * (x - (beta_t / torch.sqrt(1 - alpha_bar_t)) * predicted_noise)
        if i > 0:
            x = mean + torch.sqrt(beta_t) * torch.randn_like(x)
        else:
            x = mean
            
        if i in [150, 100, 50, 0]:
            trajectory[T - i] = x.cpu()
            
    model.train()
    return trajectory