import torch
import torch.nn as nn
from torchvision.models import resnet18, ResNet18_Weights

class GeneralCNN(nn.Module):
    """
    An ultra-robust, fully-parameterized CNN that uses Adaptive Pooling 
    to guarantee spatial dimension stability across all parameter changes.
    """
    def __init__(self, num_classes=6, kernel_size=3, stride=1, num_filters=32, 
                 pool_type="max", depth=2, dropout_p=0.3):
        super(GeneralCNN, self).__init__()
        
        layers = []
        in_channels = 3
        current_filters = num_filters
        
        for i in range(depth):
            padding = kernel_size // 2
            layers.append(nn.Conv2d(in_channels, current_filters, kernel_size=kernel_size, stride=stride, padding=padding))
            layers.append(nn.BatchNorm2d(current_filters))
            layers.append(nn.ReLU())
            
            if pool_type == "max":
                layers.append(nn.MaxPool2d(kernel_size=2, stride=2))
            elif pool_type == "avg":
                layers.append(nn.AvgPool2d(kernel_size=2, stride=2))
            
            in_channels = current_filters
            if i < depth - 1:
                current_filters *= 2
                
        self.features = nn.Sequential(*layers)
        
        # Forcefully squash any remaining spatial dimensions down to 4x4 
        # This completely avoids complex dimension division errors!
        self.adaptive_pool = nn.AdaptiveAvgPool2d((4, 4))
        self.flat_features_dim = in_channels * 4 * 4
        
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(self.flat_features_dim, 128),
            nn.ReLU(),
            nn.Dropout(p=dropout_p),
            nn.Linear(128, num_classes)
        )
        
    def forward(self, x):
        return self.classifier(self.adaptive_pool(self.features(x)))


def get_pretrained_resnet(num_classes=6, freeze=True):
    weights = ResNet18_Weights.DEFAULT
    model = resnet18(weights=weights)
    if freeze:
        for param in model.parameters():
            param.requires_grad = False
    num_features = model.fc.in_features
    model.fc = nn.Linear(num_features, num_classes)
    return model

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def train_image_model(model, train_loader, val_loader, criterion, optimizer, epochs=10):
    """
    Vocal debug version of the image training loop to detect data pipeline locks.
    """
    model = model.to(device)
    history = {'train_loss': [], 'val_loss': [], 'train_acc': [], 'val_acc': []}
    
    print(f"\n📋 Starting vocal training loop for {epochs} epochs...")
    print(f"📦 Total training batches to process per epoch: {len(train_loader)}")
    
    for epoch in range(epochs):
        model.train()
        running_loss, correct_train, total_train = 0.0, 0, 0
        
        print(f"\n🎬 --- Beginning Epoch {epoch + 1}/{epochs} ---")
        
        # We use enumerate to trace every single batch step
        for batch_idx, (images, labels) in enumerate(train_loader):
            if batch_idx % 5 == 0 or batch_idx == len(train_loader) - 1:
                print(f"⏳ [Epoch {epoch+1}] Loading batch {batch_idx}/{len(train_loader)} from disk to CPU...")
            
            # --- DETECT SYSTEM HANG POINT ---
            images, labels = images.to(device), labels.to(device)
            
            if batch_idx % 5 == 0 or batch_idx == len(train_loader) - 1:
                print(f"🚀 [Epoch {epoch+1}] Batch {batch_idx} successfully sent to GPU. Computing forward/backward pass...")
            
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            total_train += labels.size(0)
            correct_train += predicted.eq(labels).sum().item()
            
        epoch_train_loss = running_loss / len(train_loader.dataset)
        epoch_train_acc = correct_train / total_train
        print(f"✅ Finished Training Phase for Epoch {epoch+1}. Loss: {epoch_train_loss:.4f}, Acc: {epoch_train_acc:.4f}")
        
        # --- Validation Step ---
        print(f"🔍 [Epoch {epoch+1}] Entering Validation Phase...")
        model.eval()
        running_val_loss, correct_val, total_val = 0.0, 0, 0
        with torch.no_grad():
            for val_idx, (images, labels) in enumerate(val_loader):
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                loss = criterion(outputs, labels)
                
                running_val_loss += loss.item() * images.size(0)
                _, predicted = outputs.max(1)
                total_val += labels.size(0)
                correct_val += predicted.eq(labels).sum().item()
                
        epoch_val_loss = running_val_loss / len(val_loader.dataset)
        epoch_val_acc = correct_val / total_val
        print(f"📊 Validation Results for Epoch {epoch+1} -> Loss: {epoch_val_loss:.4f}, Acc: {epoch_val_acc:.4f}")
        
        history['train_loss'].append(epoch_train_loss)
        history['val_loss'].append(epoch_val_loss)
        history['train_acc'].append(epoch_train_acc)
        history['val_acc'].append(epoch_val_acc)
        
    return history