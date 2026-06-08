# ============================================================
# MODEL IMPROVEMENT PATCHES  —  add these cells to your Colab
# notebook AFTER the existing "LOAD DATASET" section.
# ============================================================

# ── PATCH 0: Install Google Generative AI SDK (run once) ────
# !pip install google-generativeai

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
        ('skills_encoder',
         CountVectorizer(tokenizer=split_skills, binary=True, token_pattern=None),
         'Skills'),
        ('cat_encoder',
         OneHotEncoder(handle_unknown='ignore'),
         ['Education', 'Certifications', 'Job Role']),
        ('num_scaler',
         StandardScaler(),
         [
             'Experience (Years)',
             'Projects Count',
             'Total_Skills',
             'Projects_Per_Year',
             'Edu_Tier',        # NEW
             'Has_Cert',        # NEW
             'Skill_Exp_Score'  # NEW
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
        n_estimators=300,
        learning_rate=0.08,
        max_depth=5,
        subsample=0.85,
        colsample_bytree=0.8,
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


# ── PATCH 5: Changes made in app.py (Google AI Studio edition) ──
#
# REMOVED  (Groq):
#   from groq import Groq
#   groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
#
# ADDED  (Google Generative AI):
#   import google.generativeai as genai
#   genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
#   gemini_model = genai.GenerativeModel("gemini-1.5-flash")
#
# REMOVED  groq_generate() helper:
#   groq_client.chat.completions.create(model="llama-3.3-70b-versatile", ...)
#
# REPLACED with  gemini_generate() helper:
#   response = gemini_model.generate_content(
#       prompt,
#       generation_config=genai.types.GenerationConfig(
#           max_output_tokens=max_output_tokens,
#           temperature=0.7,
#       )
#   )
#   return response.text.strip()
#
# ENVIRONMENT VARIABLE:
#   Old:  GROQ_API_KEY
#   New:  GOOGLE_API_KEY   ← set this in your deployment environment
#
# MODEL USED:  gemini-1.5-flash  (fast, generous free quota on AI Studio)
#   Upgrade to "gemini-1.5-pro" for better JSON accuracy on complex prompts.
#
# All feature engineering columns (Edu_Tier, Has_Cert, Skill_Exp_Score)
# remain unchanged — only the LLM call layer was swapped.
