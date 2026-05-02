# 🚗 Car Web Scraper (bama.ir)

This project asynchronously scrapes car listings from **bama.ir** and extracts structured data into an Excel file.

## 📊 Extracted Data

- Price
- Mileage
- Color
- Production Year
- Transmission Type
- Description
- URL

## ⚙️ Tech Stack

- asyncio
- aiohttp
- BeautifulSoup
- openpyxl

## 🚀 How to Use

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run from Jupyter Notebook

```python
import sys
sys.path.append("..")

from src.modeling.webscraper import main

await main()
```

### 📄 Output
The scraper generates:
```
cars_{timestamp}.xlsx
```
## With structured columns:
- URL
-Price
- Mileage
- Color
- Production Year
- Transmission
- Description

### ⚠️ Notes
- Some fields may be None if not available
- Mileage is extracted from HTML (fallback)
- Website structure changes may break scraping

### 📜 Disclaimer
This project is for educational purposes only. Respect the website’s terms of service.