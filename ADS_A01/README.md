# ADS_A01 - [Assignment Title]

## Overview
This repository contains the first homework assignment (`ADS_A01`) for the Applied Data Science course. 

## Project Structure
- `data/`: Contains raw, external, and processed data. Note: Large data files are git-ignored.
- `src/`: Reusable Python modules for scraping, processing, visualizing, and modeling.
- `notebooks/`: Jupyter notebooks containing the main analysis.
- `pre_provided/`: Provided resources and homework instructions.

## Links
- **Google Colab:** [Paste Colab Link Here]
- **GitHub Repository:** [Paste GitHub Link Here]

## Instructions to Run
1. Install dependencies: `pip install -r requirements.txt`
2. Run the main notebook located at `notebooks/01_Main_Analysis.ipynb`


## About the Data
The raw data in this repository was scraped via a Python script from the public Telegram group [SharifMusic](https://t.me/SharifMusic) (The scraping action was strictly legal). The extraction ran for 8 hours on May 2, 2025, yielding a full year of historical records spanning exactly until May 1, 2025.

### 📊 Data Summary
The dataset has been converted to `.csv` format (from its original `.db` state for easier usage) and consists of:
- **10,725** Tracks
- **3,912** Artists
- **783** Active Users
- Comprehensive interaction arrays, highlighting which user uploaded which track, upvotes/downvotes based on emoji category, specific emoji reactions, and interaction maps correlating users to emojis.

*⚠️ Note:* The data inherently requires deep algorithmic cleaning due to variances in track naming, missing attributes, and unstructured emoji mappings. Expect robust EDA parsing methods inside the main notebook. 
