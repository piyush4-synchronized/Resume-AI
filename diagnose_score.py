"""
Run this in the SAME directory/environment as your running app.py
(same venv, same working directory the Flask process uses), e.g.:

    python diagnose_score.py

It does NOT modify anything. It just loads the same model files app.py
loads and runs one prediction through the exact same feature pipeline,
printing every step so we can see exactly where the score collapses.
"""

import os
import sys
import json

# ── Same fix app.py uses for unpickling the Skills CountVectorizer ──────────
# The pipeline's CountVectorizer(tokenizer=split_skills, ...) was pickled with
# split_skills bound to __main__ in the Colab notebook. Without this, joblib.load()
# fails with: AttributeError: Can't get attribute 'split_skills' on <module '__main__'>
def split_skills(text):
    return text.split(', ')

import __main__
__main__.split_skills = split_skills

print("=" * 70)
print("STEP 1 — Package versions (version drift between training and")
print("serving is the #1 cause of a model silently returning garbage)")
print("=" * 70)
for pkg in ["pandas", "numpy", "sklearn", "xgboost", "joblib"]:
    try:
        mod = __import__(pkg)
        print(f"  {pkg:10s} {getattr(mod, '__version__', '?')}")
    except ImportError as e:
        print(f"  {pkg:10s} NOT INSTALLED ({e})")

print()
print("=" * 70)
print("STEP 2 — Locate and load the model files")
print("=" * 70)
scorer_path = os.environ.get('SCORER_PKL_PATH', 'resume_scorer_pipeline.pkl')
clf_path    = os.environ.get('ROLE_CLASSIFIER_PKL_PATH', 'role_classifier.pkl')
print(f"  SCORER_PKL_PATH          = {scorer_path}")
print(f"  ROLE_CLASSIFIER_PKL_PATH = {clf_path}")
print(f"  cwd                      = {os.getcwd()}")
print(f"  scorer file exists?      = {os.path.exists(scorer_path)}")
print(f"  classifier file exists?  = {os.path.exists(clf_path)}")
if os.path.exists(scorer_path):
    print(f"  scorer file size (bytes) = {os.path.getsize(scorer_path)}")
    print(f"  scorer last modified     = {os.path.getmtime(scorer_path)}")

try:
    import joblib
    scorer = joblib.load(scorer_path)
    print(f"  ✓ scorer loaded OK, type = {type(scorer)}")
except Exception as e:
    print(f"  ✗ FAILED TO LOAD SCORER: {type(e).__name__}: {e}")
    sys.exit(1)

try:
    role_clf = joblib.load(clf_path)
    print(f"  ✓ classifier loaded OK, type = {type(role_clf)}")
except Exception as e:
    print(f"  ✗ FAILED TO LOAD CLASSIFIER: {type(e).__name__}: {e}")

print()
print("=" * 70)
print("STEP 3 — Inspect the scorer pipeline's expected input")
print("=" * 70)
preprocessor_step = None
try:
    if hasattr(scorer, 'feature_names_in_'):
        print(f"  feature_names_in_ = {list(scorer.feature_names_in_)}")
    if hasattr(scorer, 'named_steps'):
        print(f"  pipeline steps = {list(scorer.named_steps.keys())}")
        for step_name, step in scorer.named_steps.items():
            print(f"    - {step_name}: {type(step)}")
            if 'preprocess' in step_name.lower() or hasattr(step, 'transformers_'):
                preprocessor_step = step
            if hasattr(step, 'feature_names_in_'):
                print(f"      feature_names_in_ = {list(step.feature_names_in_)}")
            if hasattr(step, 'transformers_'):
                for tname, t, cols in step.transformers_:
                    print(f"      transformer '{tname}' -> cols {cols} -> {type(t)}")
except Exception as e:
    print(f"  (could not introspect: {e})")

print()
print("=" * 70)
print("STEP 3b — *** THE KEY CHECK *** Does the fitted Skills vectorizer's")
print("vocabulary (frozen at training time) actually contain the skill")
print("terms app.py produces at inference time? If overlap is near-zero,")
print("that confirms the 0% score is a vocabulary mismatch, not a")
print("data-quality or version issue.")
print("=" * 70)
skills_vectorizer = None
try:
    if preprocessor_step is not None and hasattr(preprocessor_step, 'transformers_'):
        for tname, t, cols in preprocessor_step.transformers_:
            if 'skill' in tname.lower() or cols == 'Skills':
                skills_vectorizer = t
                print(f"  Found skills transformer: '{tname}' ({type(t)})")
except Exception as e:
    print(f"  Could not locate skills transformer: {e}")

if skills_vectorizer is not None and hasattr(skills_vectorizer, 'vocabulary_'):
    trained_vocab = set(skills_vectorizer.vocabulary_.keys())
    print(f"  Trained vocabulary size: {len(trained_vocab)}")
    print(f"  Sample of trained vocabulary (first 25): {sorted(trained_vocab)[:25]}")
    print()

    # app.py's actual ROLE_SKILLS for Software Engineer — paste your real
    # ROLE_SKILLS list here if it differs from this copy.
    app_skill_vocab = ['python','java','javascript','typescript','c++','c#','go','rust','react',
        'node','rest api','graphql','flask','django','fastapi','sql','mongodb','redis','postgres',
        'mysql','git','docker','kubernetes','aws','linux','bash','agile','scrum','microservices',
        'ci/cd','data structures','algorithms','oop','system design']
    app_vocab_set = set(app_skill_vocab)
    overlap = trained_vocab & app_vocab_set
    missing = app_vocab_set - trained_vocab

    print(f"  app.py's Software Engineer skill terms: {len(app_vocab_set)}")
    print(f"  Terms that EXIST in trained vocabulary: {len(overlap)}  -> {sorted(overlap)}")
    print(f"  Terms MISSING from trained vocabulary:  {len(missing)}  -> {sorted(missing)}")
    print()
    overlap_pct = round(len(overlap) / len(app_vocab_set) * 100, 1) if app_vocab_set else 0
    print(f"  >>> OVERLAP: {overlap_pct}% of app.py's skill vocabulary exists in the trained model <<<")
    if overlap_pct < 30:
        print("  >>> This strongly confirms a vocabulary mismatch is causing near-zero scores. <<<")
else:
    print("  Could not find a fitted CountVectorizer with .vocabulary_ —")
    print("  pipeline structure may differ from colab_patches.py. See Step 3 output above")
    print("  for the actual transformer names/types and adjust this script accordingly.")

print()
print("=" * 70)
print("STEP 4 — Run a known, realistic input through the exact same")
print("feature-construction code app.py uses, then predict")
print("=" * 70)

import pandas as pd
import numpy as np

# A deliberately strong, unambiguous resume profile —
# if this scores near 0 too, the bug is structural, not input-quality.
found_skills = ["python", "react", "sql", "docker", "aws"]
exp = 5
education = "B.Tech"
certification = "AWS Certified"
job_role = "Software Engineer"
proj_count = 4
n_skills = len(found_skills)

# Exact copy of app.py's real EDU_TIER_MAP (line 236) — NOT a guess.
EDU_TIER_MAP = {'Diploma': 1, 'B.Sc': 2, 'B.Tech': 2, 'M.Tech': 3, 'MBA': 3, 'M.Sc': 3, 'PhD': 4}

user_data = pd.DataFrame([{
    'Skills':             ", ".join(found_skills),
    'Experience (Years)': exp,
    'Education':          education,
    'Certifications':     certification,
    'Job Role':           job_role,
    'Projects Count':     proj_count,
}])
user_data['Total_Skills']      = n_skills
user_data['Projects_Per_Year'] = proj_count / (exp + 1)
user_data['Edu_Tier']          = EDU_TIER_MAP.get(education, 2)
user_data['Has_Cert']          = 0 if certification == 'None' else 1
user_data['Skill_Exp_Score']   = n_skills * float(np.log1p(exp))

print("  Input dataframe:")
print(user_data.to_string(index=False))
print()
print(f"  dtypes:\n{user_data.dtypes}")
print()

try:
    raw_score = scorer.predict(user_data)[0]
    print(f"  RAW prediction        = {raw_score}")
    print(f"  RAW prediction type   = {type(raw_score)}")
    clamped = round(float(max(0, min(100, raw_score))), 2)
    print(f"  Clamped to [0,100]    = {clamped}")
except Exception as e:
    print(f"  ✗ PREDICTION FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
print("STEP 4b — Manually inspect what the Skills CountVectorizer actually")
print("sees from app.py's input string (does it produce an all-zero row?)")
print("=" * 70)
if skills_vectorizer is not None:
    try:
        skills_input = ", ".join(found_skills)
        transformed = skills_vectorizer.transform([skills_input])
        print(f"  Input string:          '{skills_input}'")
        print(f"  Transformed nnz:       {transformed.nnz} (0 = NO vocabulary terms matched at all)")
        print(f"  Transformed row:       {transformed.toarray()}")
    except Exception as e:
        print(f"  Could not transform: {e}")

print()
print("=" * 70)
print("STEP 5 — Try predict_proba / decision_function if available")
print("(sometimes .predict() is wired to the wrong pipeline step)")
print("=" * 70)
for method in ["predict_proba", "decision_function", "predict_raw"]:
    if hasattr(scorer, method):
        try:
            out = getattr(scorer, method)(user_data)
            print(f"  {method}(user_data) = {out}")
        except Exception as e:
            print(f"  {method} raised: {e}")
    else:
        print(f"  (no {method} method)")

print()
print("=" * 70)
print("STEP 6 — Test a batch of varied inputs to see if score is CONSTANT")
print("(constant output regardless of input = pipeline/model mismatch,")
print(" not a data-quality issue)")
print("=" * 70)
variants = [
    {"Skills": "python, react, sql, docker, aws", "Experience (Years)": 8, "Education": "PhD", "Certifications": "AWS Certified", "Job Role": "Software Engineer", "Projects Count": 10},
    {"Skills": "None", "Experience (Years)": 0, "Education": "Diploma", "Certifications": "None", "Job Role": "Software Engineer", "Projects Count": 0},
    {"Skills": "java, spring", "Experience (Years)": 2, "Education": "B.Tech", "Certifications": "None", "Job Role": "Software Engineer", "Projects Count": 1},
]
for v in variants:
    df = pd.DataFrame([v])
    n_sk = len([s for s in v["Skills"].split(", ") if s != "None"])
    df['Total_Skills']      = n_sk
    df['Projects_Per_Year'] = v["Projects Count"] / (v["Experience (Years)"] + 1)
    df['Edu_Tier']          = EDU_TIER_MAP.get(v["Education"], 2)
    df['Has_Cert']          = 0 if v["Certifications"] == 'None' else 1
    df['Skill_Exp_Score']   = n_sk * float(np.log1p(v["Experience (Years)"]))
    try:
        pred = scorer.predict(df)[0]
        print(f"  exp={v['Experience (Years)']:>2} edu={v['Education']:<8} skills={n_sk} certs={v['Certifications']:<15} -> raw={pred}")
    except Exception as e:
        print(f"  FAILED for {v}: {e}")

print()
print("=" * 70)
print("DONE — paste this entire output back")
print("=" * 70)
