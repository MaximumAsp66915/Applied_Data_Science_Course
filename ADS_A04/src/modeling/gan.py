import torch.nn as nn

# ----------------------------------------------------------------
# DCGAN Generator Architecture
# ----------------------------------------------------------------
class DCGANGenerator(nn.Module):
    def __init__(self, nz=100, ngf=32, nc=1):
        super(DCGANGenerator, self).__init__()
        self.main = nn.Sequential(
            # Input noise vector shape: [batch, 100, 1, 1]
            nn.ConvTranspose2d(nz, ngf * 4, 3, 1, 0, bias=False),
            nn.BatchNorm2d(ngf * 4),
            nn.ReLU(True),
            
            # State shape: [batch, ngf * 4, 3, 3]
            nn.ConvTranspose2d(ngf * 4, ngf * 2, 3, 2, 0, bias=False),
            nn.BatchNorm2d(ngf * 2),
            nn.ReLU(True),
            
            # State shape: [batch, ngf * 2, 7, 7]
            nn.ConvTranspose2d(ngf * 2, ngf, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ngf),
            nn.ReLU(True),
            
            # State shape: [batch, ngf, 14, 14]
            nn.ConvTranspose2d(ngf, nc, 4, 2, 1, bias=False),
            nn.Tanh()
            # Final Output shape: [batch, 1, 28, 28]
        )

    def forward(self, x):
        return self.main(x)

# ----------------------------------------------------------------
# DCGAN Discriminator Architecture
# ----------------------------------------------------------------
class DCGANDiscriminator(nn.Module):
    def __init__(self, nc=1, ndf=32):
        super(DCGANDiscriminator, self).__init__()
        self.main = nn.Sequential(
            # Input image shape: [batch, 1, 28, 28]
            nn.Conv2d(nc, ndf, 4, 2, 1, bias=False),
            nn.LeakyReLU(0.2, inplace=True),
            
            # State shape: [batch, ndf, 14, 14]
            nn.Conv2d(ndf, ndf * 2, 4, 2, 1, bias=False),
            nn.BatchNorm2d(ndf * 2),
            nn.LeakyReLU(0.2, inplace=True),
            
            # State shape: [batch, ndf * 2, 7, 7]
            nn.Conv2d(ndf * 2, ndf * 4, 3, 2, 0, bias=False),
            nn.BatchNorm2d(ndf * 4),
            nn.LeakyReLU(0.2, inplace=True),
            
            # State shape: [batch, ndf * 4, 3, 3]
            nn.Conv2d(ndf * 4, 1, 3, 1, 0, bias=False),
            nn.Sigmoid()
            # Final binary scaling evaluation scalar
        )

    def forward(self, x):
        return self.main(x).view(-1)

# Custom initialization function for model weights to avoid training deadlocks
def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        nn.init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        nn.init.normal_(m.weight.data, 1.0, 0.02)
        nn.init.constant_(m.bias.data, 0)