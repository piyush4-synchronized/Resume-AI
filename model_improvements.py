# ============================================================
# MODEL IMPROVEMENT PATCHES  —  add these cells to your Colab
# notebook AFTER the existing "LOAD DATASET" section.
# ============================================================

# ── PATCH 1: Richer feature engineering ─────────────────────
#
# Problem: your original model received hardcoded defaults
# (Education='B.Tech', Certifications='None', Projects Count=3)
# for every real resume, so those columns carried zero signal.
#
# Fix: add two scored numeric columns so the model can learn
# from education level and certification presence even when
# the pipeline's OneHotEncoder sees an unseen category.

import pandas as pd
import numpy as np
import re

df = pd.read_csv('/content/drive/MyDrive/AI_Internship/AI_Resume_Screening.csv')

# Fill NaN certifications with 'None' (already in training set)
df['Certifications'] = df['Certifications'].fillna('None')

# ── PATCH 1a: Education tier score (0-5 ordinal) ─────────────
EDU_TIER = {'Diploma': 1, 'B.Sc': 2, 'B.Tech': 2, 'M.Tech': 3, 'MBA': 3, 'PhD': 4}
df['Edu_Tier'] = df['Education'].map(EDU_TIER).fillna(2)

# ── PATCH 1b: Has certification flag ─────────────────────────
df['Has_Cert'] = (df['Certifications'] != 'None').astype(int)

# ── PATCH 1c: Existing engineered features ───────────────────
df['Total_Skills']      = df['Skills'].apply(lambda x: len(str(x).split(',')))
df['Projects_Per_Year'] = df['Projects Count'] / (df['Experience (Years)'] + 1)

# ── PATCH 1d: Skill × Experience interaction ─────────────────
# Captures that 5 skills + 8 years >> 5 skills + 0 years.
df['Skill_Exp_Score'] = df['Total_Skills'] * np.log1p(df['Experience (Years)'])

print("Feature columns:")
print(df[['Total_Skills','Projects_Per_Year','Edu_Tier','Has_Cert','Skill_Exp_Score']].head())


# ── PATCH 2: Updated preprocessor with new features ──────────

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

def split_skills(text):
    return text.split(', ')

preprocessor = ColumnTransformer(
    transformers=[
        # Original: bag-of-words on skill list
        ('skills_encoder',
         CountVectorizer(tokenizer=split_skills, binary=True, token_pattern=None),
         'Skills'),

        # Original: one-hot for Education, Certifications, Job Role
        ('cat_encoder',
         OneHotEncoder(handle_unknown='ignore'),
         ['Education', 'Certifications', 'Job Role']),

        # UPDATED: now includes Edu_Tier, Has_Cert, Skill_Exp_Score
        ('num_scaler',
         StandardScaler(),
         [
             'Experience (Years)',
             'Projects Count',
             'Total_Skills',
             'Projects_Per_Year',
             'Edu_Tier',       # NEW
             'Has_Cert',       # NEW
             'Skill_Exp_Score' # NEW
         ]),
    ]
)

X = df.drop(columns=['AI Score (0-100)', 'Name', 'Resume_ID',
                      'Recruiter Decision', 'Salary Expectation ($)'])
y = df['AI Score (0-100)']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

model_pipeline = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', XGBRegressor(
        n_estimators=300,      # up from 200
        learning_rate=0.08,    # slightly lower for better generalisation
        max_depth=5,
        subsample=0.85,        # NEW: row subsampling reduces overfitting
        colsample_bytree=0.8,  # NEW: column subsampling
        random_state=42
    ))
])

model_pipeline.fit(X_train, y_train)


# ── PATCH 3: Evaluation ───────────────────────────────────────
from sklearn.metrics import mean_absolute_error, r2_score

y_pred = model_pipeline.predict(X_test)
print(f"MAE  : {mean_absolute_error(y_test, y_pred):.2f}")
print(f"R²   : {r2_score(y_test, y_pred):.4f}")


# ── PATCH 4: Export new .pkl ──────────────────────────────────
import joblib

joblib.dump(model_pipeline, 'resume_scorer_pipeline.pkl')

from google.colab import files
files.download('resume_scorer_pipeline.pkl')


# ── PATCH 5: What to change in app.py score_text() ───────────
#
# Your app.py score_text() must now pass the three new columns.
# The updated app.py (provided separately) already does this:
#
#   user_data['Edu_Tier']       = EDU_TIER_MAP.get(education, 2)
#   user_data['Has_Cert']       = 0 if certification == 'None' else 1
#   user_data['Skill_Exp_Score']= len(found_skills) * np.log1p(exp)
#
# Make sure you re-export the .pkl from this updated notebook
# before deploying the new app.py.
