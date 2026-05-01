# Applied Data Science Course

Welcome to my repository for the **Applied Data Science** course. This repository contains all my assignments, projects, and related materials, organized systematically.

## 🗂️ Overall Repository Structure

Each homework assignment has its own dedicated directory (e.g., `ADS_A01`, `ADS_A02`). Inside each homework folder, you will find a consistent, self-contained project structure designed for data science workflows:

```text
Applied_Data_Science_Course/ (Root)
├── ADS_A01/                  # First Homework/Assignment
│   ├── data/                 # Ignored by Git (raw, processed, external datasets)
│   ├── src/                  # Python source code (scraping, preprocessing, modeling)
│   ├── notebooks/            # Jupyter Notebooks for analysis
│   ├── pre_provided/         # Raw instructions and assets provided by the instructor
│   ├── requirements.txt      # Dependencies specific to this assignment
│   └── README.md             # Specific details and findings for this exact homework
├── ADS_A.../                 # Future homeworks will follow the same pattern
├── LICENSE                   # MIT License
├── manual.txt                # Quick Git guide for managing this repo
├── .gitignore                # Global gitignore to prevent large files from uploading
└── README.md                 # This repository overview file
```

## 📦 Dependencies
Because each homework might require different libraries, dependencies are handled on a per-assignment basis. To run a specific homework, navigate into its folder and install its requirements:
```bash
cd ADS_A01
pip install -r requirements.txt
```

## 📝 Sub-projects
Each folder (like `ADS_A01`) has its own `README.md` that contains the Google Colab link, GitHub link, and specific explanations for what that specific homework accomplishes.

## 📜 License
This repository is licensed under the MIT License. See the `LICENSE` file for more details.