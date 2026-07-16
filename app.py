from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import joblib
import pandas as pd
import pdfplumber
import re
import os
import io
import json
import warnings

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
warnings.filterwarnings(
    "ignore",
    message=".*serialized model.*",
    category=UserWarning,
    module="xgboost.core",
)
try:
    from flask_cors import CORS as _CORS
    def _apply_cors(app): 
        # Set supports_credentials=True to allow cookies
        # Replace the URL with your exact frontend URL (e.g., Live Server port)
        origins = [
            origin.strip()
            for origin in os.environ.get(
                "CORS_ORIGIN",
                "http://localhost:5000,http://127.0.0.1:5000,http://127.0.0.1:5500,http://localhost:5500",
            ).split(",")
            if origin.strip()
        ]
        _CORS(app, supports_credentials=True, origins=origins)
except ImportError:
    def _apply_cors(app):
        @app.after_request
        def _cors_headers(response):
            # You must specify the exact origin when using credentials, '*' won't work
            origin = request.headers.get("Origin")
            allowed = {
                item.strip()
                for item in os.environ.get(
                    "CORS_ORIGIN",
                    "http://localhost:5000,http://127.0.0.1:5000,http://127.0.0.1:5500,http://localhost:5500",
                ).split(",")
                if item.strip()
            }
            if origin in allowed:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            return response
# groq imported safely below after app init
from dotenv import load_dotenv

load_dotenv()

# ── Fix for pickle deserialization ──────────────────────────────────────────
def split_skills(text):
    return text.split(', ')

import __main__
__main__.split_skills = split_skills

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
_apply_cors(app)

# ── Database Configuration ───────────────────────────────────────────────────
database_url = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI') or 'sqlite:///resumeai.db'
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='candidate')

class AuthSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(128), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc) + timedelta(days=7))
    user = db.relationship('User', backref=db.backref('sessions', lazy=True))

class ScanHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True, nullable=False)
    scan_type = db.Column(db.String(20), nullable=False, default='single')
    job_role = db.Column(db.String(120), nullable=True)
    payload = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

with app.app_context():
    db.create_all()  # Automatically creates resumeai.db on first run
    inspector = inspect(db.engine)
    if 'auth_session' in inspector.get_table_names():
        session_columns = {col['name'] for col in inspector.get_columns('auth_session')}
        if db.engine.url.get_backend_name() == 'sqlite':
            if 'created_at' not in session_columns:
                db.session.execute(text("ALTER TABLE auth_session ADD COLUMN created_at DATETIME"))
            if 'expires_at' not in session_columns:
                db.session.execute(text("ALTER TABLE auth_session ADD COLUMN expires_at DATETIME"))
            db.session.execute(
                text(
                    "UPDATE auth_session SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
                    "expires_at = COALESCE(expires_at, datetime(CURRENT_TIMESTAMP, '+7 days'))"
                )
            )
            db.session.commit()

# ── Groq client (optional — scoring works without it) ────────────────────────
try:
    from groq import Groq as _Groq
    _groq_key = os.environ.get("GROQ_API_KEY")
    groq_client = _Groq(api_key=_groq_key) if _groq_key else None
    if not _groq_key:
        print("WARNING: GROQ_API_KEY not set — AI features disabled, scoring still works")
except ImportError:
    groq_client = None
    print("WARNING: groq package not installed — AI features disabled, scoring still works")
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Lazy model loader ────────────────────────────────────────────────────────
_model = None
def get_model():
    global _model
    if _model is None:
        model_path = os.environ.get('SCORER_PKL_PATH', os.path.join(BASE_DIR, 'resume_scorer_pipeline.pkl'))
        if not os.path.isabs(model_path):
            model_path = os.path.join(BASE_DIR, model_path)
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Scoring model not found at {model_path}")
        _model = joblib.load(model_path)
    return _model

# ── File parsers ─────────────────────────────────────────────────────────────
def extract_text_from_pdf(file_stream):
    text = ""
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + " "
    return text.strip()

def extract_text_from_docx(file_stream):
    try:
        from docx import Document
        doc = Document(file_stream)
        return " ".join([p.text for p in doc.paragraphs if p.text.strip()])
    except ImportError:
        raise Exception("python-docx not installed. Run: pip install python-docx")

def extract_text_from_txt(file_stream):
    raw = file_stream.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')

# ── Role skill sets ───────────────────────────────────────────────────────────
ROLE_SKILLS = {
    'Software Engineer': [
        'python','java','javascript','typescript','c++','c#','go','rust',
        'react','node','rest api','graphql','flask','django','fastapi',
        'sql','mongodb','redis','postgres','mysql','git','docker',
        'kubernetes','aws','linux','bash','agile','scrum','microservices',
        'ci/cd','data structures','algorithms','oop','system design'
    ],
    'Data Scientist': [
        'python','r','sql','machine learning','deep learning','tensorflow',
        'pytorch','scikit','pandas','numpy','matplotlib','seaborn','scipy',
        'nlp','computer vision','opencv','statistics','probability',
        'data analysis','feature engineering','model deployment','spark',
        'hadoop','tableau','power bi','excel','jupyter','kaggle','mlflow',
        'data pipeline','a/b testing','hypothesis testing'
    ],
    'Frontend Developer': [
        'javascript','typescript','react','vue','angular','html','css',
        'sass','tailwind','webpack','vite','next.js','nuxt','redux',
        'graphql','rest api','jest','cypress','figma','responsive design',
        'accessibility','web performance','pwa','git','node','npm',
        'browser apis','svg','animation','ui/ux'
    ],
    'Backend Developer': [
        'python','java','node','go','rust','c#','php','ruby',
        'flask','django','fastapi','spring','express','rest api','graphql',
        'sql','mongodb','redis','postgres','mysql','kafka','rabbitmq',
        'docker','kubernetes','aws','linux','bash','ci/cd','microservices',
        'system design','authentication','caching','message queues'
    ],
    'DevOps Engineer': [
        'docker','kubernetes','terraform','ansible','jenkins','gitlab ci',
        'github actions','aws','azure','gcp','linux','bash','python',
        'ci/cd','prometheus','grafana','elk stack','nginx','helm',
        'git','cloud formation','infrastructure as code','networking',
        'security','monitoring','logging','scripting','devops'
    ],
    'Machine Learning Engineer': [
        'python','tensorflow','pytorch','scikit','keras','mlflow','kubeflow',
        'machine learning','deep learning','nlp','computer vision','opencv',
        'pandas','numpy','spark','sql','docker','kubernetes','aws','gcp',
        'model deployment','feature engineering','data pipeline','rest api',
        'git','cuda','distributed training','onnx','model optimization'
    ],
    'Data Analyst': [
        'sql','excel','python','r','tableau','power bi','looker','google analytics',
        'pandas','numpy','statistics','data visualization','data cleaning',
        'data wrangling','a/b testing','hypothesis testing','reporting',
        'dashboards','etl','data pipeline','business intelligence',
        'pivot tables','vlookup','google sheets','data storytelling'
    ],
    'Cloud Architect': [
        'aws','azure','gcp','terraform','kubernetes','docker','networking',
        'cloud formation','infrastructure as code','security','iam',
        'microservices','serverless','lambda','s3','ec2','rds','vpc',
        'load balancing','auto scaling','cdn','devops','linux','python',
        'bash','ci/cd','cost optimization','high availability','disaster recovery'
    ],
    'Full Stack Developer': [
        'javascript','typescript','react','node','python','html','css',
        'sql','mongodb','postgres','rest api','graphql','docker','git',
        'aws','linux','redux','next.js','express','django','flask',
        'tailwind','jest','ci/cd','agile','microservices','authentication'
    ],
    'Product Manager': [
        'product roadmap','user stories','agile','scrum','jira','confluence',
        'data analysis','sql','google analytics','a/b testing','wireframing',
        'figma','market research','competitive analysis','stakeholder management',
        'kpi','metrics','prioritization','product strategy','go-to-market',
        'customer discovery','user research','mvp','backlog','sprint planning'
    ],
    'UI/UX Designer': [
        'figma','sketch','adobe xd','invision','user research','wireframing',
        'prototyping','user testing','usability testing','information architecture',
        'interaction design','visual design','typography','color theory',
        'accessibility','responsive design','design systems','css','html',
        'a/b testing','heuristic evaluation','persona','user journey','zeplin'
    ],
    'Cybersecurity Analyst': [
        'penetration testing','network security','siem','splunk','ids/ips',
        'firewall','linux','python','bash','vulnerability assessment',
        'incident response','forensics','encryption','pki','oauth',
        'owasp','ethical hacking','metasploit','nmap','wireshark',
        'iso 27001','nist','compliance','cloud security','threat modeling'
    ],
}

DEFAULT_ROLE = 'Software Engineer'

EDU_TIER_MAP = {
    'Diploma': 1, 'B.Sc': 2, 'B.Tech': 2,
    'M.Tech': 3, 'MBA': 3, 'M.Sc': 3, 'PhD': 4,
}

ATS_KEYWORDS = [
    'experience','education','skills','projects','certifications','achievements',
    'summary','objective','responsibilities','developed','managed','led','built',
    'designed','implemented','optimized','collaborated','achieved','improved',
    'bachelor','master','degree','university','college','gpa','intern',
    'full-stack','software engineer','developer','analyst','architect'
]

EDU_PATTERNS = {
    'PhD':    ['phd','ph.d','doctorate','doctor of philosophy'],
    'M.Tech': ['m.tech','mtech','master of technology'],
    'MBA':    ['mba','master of business'],
    'M.Sc':   ['m.sc','msc','master of science'],   # removed 'ms ' and 'ms.' — too broad
    'B.Tech': ['b.tech','btech','bachelor of technology','b.e.','b.e '],
    'B.Sc':   ['b.sc','bsc','bachelor of science'],
    'Diploma':['diploma'],
}

CERT_KEYWORDS = [
    'aws certified','google ml','deep learning specialization',
    'azure certified','gcp certified','pmp','cissp','ceh',
    'tensorflow developer','coursera','udemy','certification','certified'
]

# ── Feature extraction ───────────────────────────────────────────────────────
def extract_education(text_lower):
    # Master's / Doctorate Level
    if re.search(r'\b(phd|doctorate|m\.?tech|m\.?sc|m\.?ca|mba|master|m\.?s)\b', text_lower):
        if re.search(r'\b(phd|doctorate)\b', text_lower): return 'PhD'
        if re.search(r'\b(mba)\b', text_lower): return 'MBA'
        return 'M.Tech' # Grouping all Masters here for the ML model mapping
        
    # Bachelor's Level
    if re.search(r'\b(b\.?tech|b\.?e|b\.?sc|b\.?ca|b\.?ba|bachelor|b\.?s)\b', text_lower):
        return 'B.Tech' # Grouping all Bachelors here for the ML model mapping
        
    # Diploma Level
    if re.search(r'\b(diploma|associate)\b', text_lower):
        return 'Diploma'
        
    return 'None'

def extract_certifications(text_lower):
    # Check if the document mentions the word certificate/certification/certified anywhere
    has_cert_keyword = re.search(r'\bcertif(icate|ication|ied)\b', text_lower)
    
    # 1. Smart matching for high-value tech certifications (handles variations)
    if re.search(r'\b(aws|amazon web services)\b', text_lower) and has_cert_keyword:
        return 'AWS Certified'
    if re.search(r'\b(gcp|google cloud|google ml)\b', text_lower) and has_cert_keyword:
        return 'Google/GCP Certified'
    if re.search(r'\b(azure|microsoft)\b', text_lower) and has_cert_keyword:
        return 'Azure Certified'
    if re.search(r'\b(pmp|cissp|ceh|scrum)\b', text_lower):
        return 'Professional Certification'
        
    # 2. General fallback for other certificates
    if has_cert_keyword:
        return 'General Certification'
        
    # 3. Detect popular learning platforms even if the word "certificate" isn't used
    if re.search(r'\b(coursera|udemy|edx|datacamp|hackerrank)\b', text_lower):
        return 'Online Coursework'
        
    return 'None'

def extract_projects_count(text_lower):
    # 1. Catch both "project" and "projects"
    word_mentions = len(re.findall(r'\bprojects?\b', text_lower))
    
    # 2. Count GitHub repository links (a strong indicator of technical projects)
    github_links = len(re.findall(r'github\.com/[^\s]+', text_lower))
    
    # 3. Count common live-hosting URLs
    live_links = len(re.findall(r'vercel\.app|netlify\.app|herokuapp\.com', text_lower))
    
    # Take the highest reliable indicator
    estimated_count = max(word_mentions, github_links, live_links)
    
    # Fallback: if it still reads 0 but detects heavy builder keywords
    if estimated_count == 0 and any(kw in text_lower for kw in ['built ', 'developed ', 'hackathon', 'platform']):
        estimated_count = 2 
        
    return min(estimated_count, 10)

# ── Vocabulary-aware skill helpers ──────────────────────────────────────────
# These query the model's ACTUAL trained CountVectorizer vocabulary so we only
# send skill tokens the model genuinely knows.  Cached after first load.

_model_vocab_cache = None

def _get_model_vocab():
    """Read the real skill vocabulary from the loaded .pkl — never hardcode it."""
    global _model_vocab_cache
    if _model_vocab_cache is not None:
        return _model_vocab_cache
    try:
        m = get_model()
        pre = m.named_steps['preprocessor']
        for _, transformer, _ in pre.transformers_:
            if hasattr(transformer, 'vocabulary_'):
                _model_vocab_cache = set(transformer.vocabulary_.keys())
                return _model_vocab_cache
    except Exception:
        pass
    _model_vocab_cache = set()
    return _model_vocab_cache

def _skill_in_text(skill, text_lower):
    """
    Word-boundary-safe skill detection.
    Multi-word skills ('rest api') use plain substring — safe, no false matches.
    Single-word skills ('go', 'r', 'node') use regex boundary to avoid matching
    inside other words (e.g. 'node' inside 'android').
    """
    if ' ' in skill:
        return skill in text_lower
    return bool(re.search(r'(?<!\w)' + re.escape(skill) + r'(?!\w)', text_lower))

# Static synonym map: only used when a found_skill is NOT in the model vocab.
# Maps the resume skill → nearest model-vocabulary sibling.
_SKILL_SYNONYMS = {
    'js': 'javascript',
    'reactjs': 'react',
    'react.js': 'react',
    'node.js': 'node',
    'nodejs': 'node',
    'vuejs': 'vue',
    'nextjs': 'next.js',
    'ts': 'typescript',
    'cpp': 'c++',
    'c++': 'c++',
    'c#': 'c#',
    'csharp': 'c#',
    'aws': 'amazon web services',
    'gcp': 'google cloud',
    'k8s': 'kubernetes',
    'postgres': 'postgresql',
    'mongo': 'mongodb',
    'ml': 'machine learning',
    'ai': 'artificial intelligence',
    'nlp': 'natural language processing',
    'cv': 'computer vision'
}

def _build_model_skills(text_lower, found_skills):
    """
    Build the skill list actually sent to the ML model.

    Priority:
      1. found_skills terms that exist verbatim in the model vocab → pass through.
      2. found_skills terms NOT in vocab → try synonym map, only if target is in vocab.
      3. Scan raw text for any model-vocab term not yet captured (catches skills
         outside ROLE_SKILLS that the candidate listed and the model knows).

    Falls back to synonym-only if vocab is empty (pkl not loaded yet).
    """
    vocab = _get_model_vocab()
    result = []

    for s in found_skills:
        if not vocab or s in vocab:
            if s not in result:
                result.append(s)
        else:
            credited = _SKILL_SYNONYMS.get(s)
            if credited and (not vocab or credited in vocab) and credited not in result:
                result.append(credited)

    # Pick up any model-vocab terms in the resume text that weren't in ROLE_SKILLS
    if vocab:
        for term in vocab:
            if term not in result and _skill_in_text(term, text_lower):
                result.append(term)

    return result

def extract_experience(text_lower):
    import re
    import datetime
    current_year = datetime.datetime.now().year
    
    # --- 1. Explicit Experience Mentions (Using your logic) ---
    # Looks for direct phrases like "5 years of experience", "3 yrs exp", "working 2 years"
    explicit_exp = re.findall(r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s*of)?\s*(?:experience|exp|working)', text_lower)
    if explicit_exp:
        vals = [float(v) for v in explicit_exp if float(v) < 40]
        if vals:
            # If multiple are found (e.g., 3 years in job A, 4 years in job B)
            highest = max(vals)
            total_sum = sum(vals)
            
            # Smart check: If they wrote "7 years total" in the summary, but also list "3 years" and "4 years" 
            # below, max(7) is equal to sum(3+4). We return the highest summary number.
            # Otherwise, we sum up the individual jobs as you suggested!
            if highest >= (total_sum - highest):
                return highest
            else:
                return total_sum

    # --- 2. Fallback to Date Ranges (Fixing the PDF Layout Bug) ---
    exp_years = 0.0
    ranges = re.finditer(r'\b(19\d{2}|20\d{2})\s*(?:-|to|–)\s*(20\d{2}|present|current|now)\b', text_lower)
    
    for match in ranges:
        start_year = int(match.group(1))
        end_str = match.group(2)
        
        if end_str in ['present', 'current', 'now']:
            end_year = current_year
        else:
            end_year = int(end_str)
            
        # FIX A: Block Future Dates
        # Work experience cannot end in the future. If it ends after the current year 
        # (like your 2028 graduation), it is 100% an ongoing degree. Skip it!
        if end_year > current_year:
            continue
            
        # FIX B: Look both backwards AND forwards (Handles messy PDF columns)
        # We expand the search window to 150 characters on both sides of the dates
        context_start = max(0, match.start() - 150)
        context_end = min(len(text_lower), match.end() + 150)
        context = text_lower[context_start:context_end]
        
        # If the surrounding text mentions any education words, ignore this date range!
        edu_keywords = ['school', 'college', 'university', 'b.tech', 'm.tech', 'degree', '10th', '12th', 'cgpa', 'percentage', 'bachelor', 'academy']
        if any(kw in context for kw in edu_keywords):
            continue
            
        if end_year >= start_year:
            exp_years += (end_year - start_year)
            
    if exp_years > 0:
        return min(exp_years, 40.0)
        
    # --- 3. Last Resort Fallback ---
    # Catch stray numbers like bullet points just saying "3 years"
    generic = re.findall(r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)', text_lower)
    if generic:
        vals = [float(v) for v in generic if float(v) < 40]
        if vals:
            return max(vals) 
            
    return 0.0

def guess_candidate_category(text_lower):
    best_role = "Unknown"
    max_hits = 0
    # Scan the resume against all our known role dictionaries
    for role, skills in ROLE_SKILLS.items():
        hits = sum(1 for s in skills if _skill_in_text(s, text_lower))
        if hits > max_hits:
            max_hits = hits
            best_role = role
    return best_role if max_hits > 0 else "Unclassified"

def analyze_resume(raw_text, job_role=DEFAULT_ROLE):
    text_lower = raw_text.lower()
    role_skills = ROLE_SKILLS.get(job_role, ROLE_SKILLS[DEFAULT_ROLE])

    found_skills   = [s for s in role_skills if _skill_in_text(s, text_lower)]
    missing_skills = [s for s in role_skills if not _skill_in_text(s, text_lower)][:12]

    exp = extract_experience(text_lower)

    edu_score = 0
    for kw, pts in [('phd',100),('master',85),('mba',85),('b.tech',70),('bachelor',70),('diploma',50)]:
        if kw in text_lower:
            edu_score = pts; break

    proj_count = extract_projects_count(text_lower)
    cert_count = len(re.findall(r'certif', text_lower))
    ats_hits   = [k for k in ATS_KEYWORDS if k in text_lower]

    radar = {
        'Experience':     min(100, exp * 12),
        'Education':      edu_score,
        'Projects':       min(100, proj_count * 15),
        'Certifications': min(100, cert_count * 25),
        'Skills':         min(100, len(found_skills) * 6),
        'ATS Match':      min(100, int((len(ats_hits) / len(ATS_KEYWORDS)) * 100)),
    }

    return {
        'exp':            exp,
        'education':      extract_education(text_lower),
        'certification':  extract_certifications(text_lower),
        'projects_count': proj_count,
        'found_skills':   found_skills[:15],
        'missing_skills': missing_skills,
        'section_scores': radar,
        'ats_score':      radar['ATS Match'],
        'ats_hits':       ats_hits[:10],
        '_text_lower':    text_lower,   
        'guessed_category': guess_candidate_category(text_lower) # <--- ADD THIS LINE
    }

def score_text(found_skills, exp, education, certification, projects_count, job_role=DEFAULT_ROLE, text_lower='', radar_scores=None):
    import numpy as np

    # Build model-vocabulary-filtered skill list
    model_skills = _build_model_skills(text_lower, found_skills) if text_lower else found_skills
    n = len(model_skills)

    user_data = pd.DataFrame([{
        'Skills':             ', '.join(model_skills) if model_skills else 'None',
        'Experience (Years)': exp,
        'Education':          education,
        'Certifications':     certification,
        'Job Role':           job_role,
        'Projects Count':     projects_count,
    }])
    user_data['Total_Skills']      = n
    user_data['Projects_Per_Year'] = projects_count / (exp + 1)

    try:
        pre = get_model().named_steps['preprocessor']
        for _, transformer, cols in pre.transformers_:
            if hasattr(transformer, 'mean_'):
                if 'Edu_Tier' in cols:
                    user_data['Edu_Tier']        = EDU_TIER_MAP.get(education, 2)
                    user_data['Has_Cert']        = 0 if certification == 'None' else 1
                    user_data['Skill_Exp_Score'] = n * float(np.log1p(exp))
                break
    except Exception:
        pass

    score = get_model().predict(user_data)[0]
    ml_score = float(max(0, min(100, float(score))))

    # --- FAIRNESS FIX: BLEND ML SCORE WITH EXTRACTED RADAR METRICS ---
    if radar_scores:
        heuristic_score = (
            (radar_scores['Experience'] * 0.35) +    # Increased from 0.20
            (radar_scores['Education'] * 0.10) +
            (radar_scores['Projects'] * 0.15) +
            (radar_scores['Certifications'] * 0.05) +
            (radar_scores['Skills'] * 0.20) +        # Decreased from 0.25
            (radar_scores['ATS Match'] * 0.15)       # Decreased from 0.25
        )

        # If the ML model failed to recognize the resume structure (scored < 10),
        # rely entirely on the fair heuristic score.
        if ml_score < 10:
            return round(heuristic_score, 2)
        else:
            # Shift trust to the extracted facts: 80% Heuristic, 20% ML
            return round((ml_score * 0.20) + (heuristic_score * 0.80), 2)

    return round(ml_score, 2)

# ── Groq helper ──────────────────────────────────────────────────────────────
def groq_generate(prompt: str, max_tokens: int = 1024) -> str:
    if groq_client is None:
        raise RuntimeError("Groq client not available. Set GROQ_API_KEY and install groq package.")
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def groq_json(prompt: str, max_tokens: int = 1024):
    raw = groq_generate(prompt, max_tokens)
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$',     '', raw)
    return json.loads(raw)

# ── AI generators ────────────────────────────────────────────────────────────
def generate_interview_questions(job_role, found_skills, missing_skills, exp, score):
    tier = "senior" if exp >= 6 else "mid-level" if exp >= 3 else "junior/entry-level"
    prompt = f"""You are a senior technical recruiter interviewing a {tier} {job_role} candidate.

Candidate profile:
- Score: {score}/100
- Years of experience: {exp}
- Strong skills: {', '.join(found_skills[:10]) or 'Not specified'}
- Skill gaps: {', '.join(missing_skills[:6]) or 'None detected'}

Generate exactly 8 interview questions.
Rules:
1. Mix of technical, behavioural, and situational questions.
2. 3 questions probe STRONG skills.
3. 3 questions gently probe SKILL GAPS.
4. 2 behavioural/culture fit questions for a {tier} hire.
5. Each question includes a one-line interviewer hint.

Respond ONLY as a JSON array (no markdown, no preamble):
[{{"question":"...","category":"technical|behavioural|situational","hint":"..."}},...]"""
    return groq_json(prompt, 1200)

def generate_cover_letter(job_role, found_skills, exp, education, company_name="the company"):
    prompt = f"""You are an expert career coach. Write a professional ATS-friendly cover letter.

Candidate:
- Role: {job_role}
- Experience: {exp} years
- Education: {education}
- Skills: {', '.join(found_skills[:12])}
- Applying to: {company_name}

Rules:
1. 3 paragraphs: opening hook, value proposition, call to action.
2. Include these keywords naturally: {', '.join(found_skills[:8])}
3. Confident but not arrogant tone. Under 300 words.
4. Plain text only — no placeholders like [Your Name]."""
    return groq_generate(prompt, 700)

def generate_rewrite_suggestions(raw_text, missing_skills, job_role):
    prompt = f"""You are a senior resume coach. Analyse this resume and give improvement suggestions.

Target Role: {job_role}
Missing Skills: {', '.join(missing_skills[:8])}

Resume (first 1500 chars):
{raw_text[:1500]}

Give exactly 4 suggestions (no markdown fences):
[
  {{"section":"Summary","issue":"...","rewritten":"..."}},
  {{"section":"Skills","issue":"...","rewritten":"..."}},
  {{"section":"Experience Bullets","issue":"...","rewritten":"..."}},
  {{"section":"Keywords","issue":"...","rewritten":"..."}}
]"""
    return groq_json(prompt, 900)

def generate_linkedin_summary(job_role, found_skills, exp, education):
    prompt = f"""Write a compelling LinkedIn About section for a {job_role} professional.

Profile:
- Experience: {exp} years
- Education: {education}
- Top Skills: {', '.join(found_skills[:12])}

Rules:
1. 3 short paragraphs, max 300 words.
2. Strong first-person hook (not "I am a...").
3. Relevant recruiter keywords.
4. End with open-to opportunities line.
5. Plain text only."""
    return groq_generate(prompt, 500)

def generate_salary_estimate(job_role, found_skills, exp, location="India"):
    prompt = f"""You are a compensation expert. Estimate a realistic salary range.

Profile:
- Role: {job_role}
- Experience: {exp} years
- Location: {location}
- Skills: {', '.join(found_skills[:10])}

Respond ONLY as JSON (no markdown):
{{"min_salary":"...","max_salary":"...","currency":"INR or USD","level":"Junior/Mid/Senior","skills_to_increase_salary":["s1","s2","s3"],"market_insight":"2-line market context"}}"""
    return groq_json(prompt, 400)

def generate_learning_roadmap(job_role, missing_skills, exp):
    level = "senior" if exp >= 6 else "mid-level" if exp >= 3 else "beginner"
    prompt = f"""Create a 90-day skill-building roadmap for a {level} {job_role}.

Skills to learn: {', '.join(missing_skills[:8])}

Respond ONLY as JSON (no markdown):
{{
  "day_1_30":{{"focus":"...","tasks":["t1","t2","t3"],"resource":"..."}},
  "day_31_60":{{"focus":"...","tasks":["t1","t2","t3"],"resource":"..."}},
  "day_61_90":{{"focus":"...","tasks":["t1","t2","t3"],"resource":"..."}},
  "milestone":"What the candidate can show by day 90"
}}"""
    return groq_json(prompt, 700)

# ── Batch helper ─────────────────────────────────────────────────────────────
def parse_file_to_text(file_obj):
    name   = file_obj.filename.lower()
    data   = file_obj.read()
    stream = io.BytesIO(data)
    if name.endswith('.pdf'):
        return extract_text_from_pdf(stream)
    elif name.endswith('.docx'):
        return extract_text_from_docx(stream)
    elif name.endswith('.txt'):
        return data.decode('utf-8', errors='replace')
    raise ValueError(f"Unsupported file type: {name}")

# ════════════════════════════════════════════════════════════════════════════
# HTML PAGE  — paste your HTML_PAGE string here
# ════════════════════════════════════════════════════════════════════════════

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    scorer_path = os.environ.get('SCORER_PKL_PATH', os.path.join(BASE_DIR, 'resume_scorer_pipeline.pkl'))
    if not os.path.isabs(scorer_path):
        scorer_path = os.path.join(BASE_DIR, scorer_path)
    scorer_ok = os.path.exists(scorer_path)
    return jsonify({
        'status': 'ok',
        'scorer_pkl': scorer_ok,
        'database': app.config['SQLALCHEMY_DATABASE_URI'].split('@')[-1],
        'groq_client': groq_client is not None,
        'groq_key_set': bool(os.environ.get('GROQ_API_KEY')),
    })

@app.route('/', methods=['GET'])
def home():
    return render_template('resumeai_dashboard.html')

@app.route('/favicon.ico', methods=['GET'])
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/api/score', methods=['POST'])
def score_resume():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file     = request.files['file']
    job_role = request.form.get('job_role', DEFAULT_ROLE)
    filename = file.filename.lower()
    try:
        if filename.endswith('.pdf'):
            raw_text = extract_text_from_pdf(file)
        elif filename.endswith('.docx'):
            raw_text = extract_text_from_docx(file)
        elif filename.endswith('.txt'):
            raw_text = extract_text_from_txt(file)
        else:
            return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400
        a = analyze_resume(raw_text, job_role)
        score = score_text(a['found_skills'], a['exp'], a['education'], a['certification'],
                           a['projects_count'], job_role, text_lower=a['_text_lower'], radar_scores=a['section_scores'])
        target_company = request.form.get('target_company', '—')
        payload = {"success":True,"job_role":job_role,"ai_score":score,
            "extracted_experience":a['exp'],"extracted_education":a['education'],
            "found_skills":a['found_skills'],"missing_skills":a['missing_skills'],
            "section_scores":a['section_scores'],"ats_score":a['ats_score'],
            "ats_hits":a['ats_hits'],"target_company":target_company,
            "predicted_category": a['guessed_category'], "raw_text": raw_text[:5000]}
        # Save to history for the logged-in user (non-fatal if no session)
        sess, _ = _get_session()
        if sess:
            _save_scan(sess['email'], payload)
        return jsonify(payload)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route('/api/score-text', methods=['POST'])
def score_resume_text():
    body = request.get_json(silent=True)
    if not body or not body.get('text','').strip():
        return jsonify({"error": "No text provided"}), 400
    raw_text = body['text']
    job_role = body.get('job_role', DEFAULT_ROLE)
    try:
        a = analyze_resume(raw_text, job_role)
        score = score_text(a['found_skills'], a['exp'], a['education'], a['certification'],
                           a['projects_count'], job_role, text_lower=a['_text_lower'], radar_scores=a['section_scores'])
        target_company = body.get('target_company', '—')
        payload = {"success":True,"job_role":job_role,"ai_score":score,
            "extracted_experience":a['exp'],"extracted_education":a['education'],
            "found_skills":a['found_skills'],"missing_skills":a['missing_skills'],
            "section_scores":a['section_scores'],"ats_score":a['ats_score'],
            "ats_hits":a['ats_hits'],"target_company":target_company,
            "predicted_category": a['guessed_category'], "raw_text": raw_text[:5000]}
        sess, _ = _get_session()
        if sess:
            _save_scan(sess['email'], payload)
        return jsonify(payload)
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route('/api/interview-questions', methods=['POST'])
def interview_questions():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        qs = generate_interview_questions(
            body.get('job_role', DEFAULT_ROLE), body.get('found_skills',[]),
            body.get('missing_skills',[]), body.get('exp',0), body.get('score',50))
        return jsonify({"success": True, "questions": qs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/cover-letter', methods=['POST'])
def cover_letter():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_cover_letter(
            body.get('job_role', DEFAULT_ROLE), body.get('found_skills',[]),
            body.get('exp',0), body.get('education','B.Tech'), body.get('company_name','the company'))
        return jsonify({"success": True, "cover_letter": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/rewrite', methods=['POST'])
def rewrite_suggestions():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_rewrite_suggestions(
            body.get('raw_text',''), body.get('missing_skills',[]), body.get('job_role', DEFAULT_ROLE))
        return jsonify({"success": True, "suggestions": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/linkedin-summary', methods=['POST'])
def linkedin_summary():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_linkedin_summary(
            body.get('job_role', DEFAULT_ROLE), body.get('found_skills',[]),
            body.get('exp',0), body.get('education','B.Tech'))
        return jsonify({"success": True, "linkedin_summary": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/salary', methods=['POST'])
def salary_estimate():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_salary_estimate(
            body.get('job_role', DEFAULT_ROLE), body.get('found_skills',[]),
            body.get('exp',0), body.get('location','India'))
        return jsonify({"success": True, "salary": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/roadmap', methods=['POST'])
def learning_roadmap():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_learning_roadmap(
            body.get('job_role', DEFAULT_ROLE), body.get('missing_skills',[]), body.get('exp',0))
        return jsonify({"success": True, "roadmap": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import uuid
import io
import zipfile
from datetime import datetime
from werkzeug.datastructures import FileStorage

# Global memory store for background processing jobs
_batch_jobs = {}

@app.route('/api/batch-score', methods=['POST'])
def batch_score():
    if 'files[]' not in request.files:
        return jsonify({"error": "No files provided."}), 400
    
    files = request.files.getlist('files[]')
    job_role = request.form.get('job_role', 'Software Engineer')
    
    results, errors, files_to_process = [], [], []
    
    print("\n" + "="*50)
    print(f"BATCH UPLOAD STARTED: Received {len(files)} uploaded item(s)")
    
    # Retrieve user session for saving to history
    sess, _ = _get_session()
    user_email = sess['email'] if sess else None
    
    # Step 1: Safely Unzip using Native Flask FileStorage
    for f in files:
        name = f.filename.lower()
        if name.endswith('.zip') or f.mimetype in ['application/zip', 'application/x-zip-compressed']:
            print(f"Unzipping archive: {f.filename}...")
            try:
                zip_bytes = f.read()
                with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as z:
                    for info in z.infolist():
                        if info.is_dir() or '__MACOSX' in info.filename or info.filename.split('/')[-1].startswith('.'):
                            continue
                        
                        ext = info.filename.lower()
                        if ext.endswith(('.pdf', '.docx', '.txt')):
                            file_bytes = z.read(info.filename)
                            base_name = info.filename.split('/')[-1]
                            
                            # Create a perfect replica of a standard Flask file upload
                            mock_file = FileStorage(
                                stream=io.BytesIO(file_bytes),
                                filename=base_name,
                                content_type="application/pdf" if ext.endswith('.pdf') else "text/plain"
                            )
                            files_to_process.append(mock_file)
            except Exception as e:
                print(f"ZIP Error: {str(e)}")
                errors.append({"filename": f.filename, "error": f"Failed to extract: {str(e)}"})
        else:
            if name.endswith(('.pdf', '.docx', '.txt')):
                files_to_process.append(f)

    print(f"Found {len(files_to_process)} valid resumes inside. Starting analysis...")
    print("-" * 50)

    # Step 2: Sequential Processing with Live Terminal Updates
    for i, file_obj in enumerate(files_to_process, 1):
        print(f"[{i}/{len(files_to_process)}] Analyzing {file_obj.filename} ... ", end="", flush=True)
        
        try:
            raw_text = parse_file_to_text(file_obj)
            a        = analyze_resume(raw_text, job_role)
            score    = score_text(a['found_skills'], a['exp'], a['education'], a['certification'],
                                  a['projects_count'], job_role, text_lower=a['_text_lower'], radar_scores=a['section_scores'])
            
            tier = ("Elite Candidate" if score>=85 else "Strong Profile" if score>=70
                    else "Developing Profile" if score>=50 else "Needs Work")
            
            results.append({
                "filename":          file_obj.filename,
                "candidate_id":      file_obj.filename,
                "ai_score":          score,
                "match_pct":         score,               
                "predicted_category":a['guessed_category'],            
                "tier":              tier,
                "exp":               a['exp'],
                "education":         a['education'],
                "certification":     a['certification'],
                "found_skills":      a['found_skills'][:8],
                "missing_skills":    a['missing_skills'][:6],
                "ats_score":         a['ats_score'],
                "section_scores":    a['section_scores'],
            })
            print("DONE!")
        except Exception as e:
            print(f"FAILED! ({str(e)})")
            errors.append({"filename": file_obj.filename, "error": str(e)})

    print("-" * 50)
    print(f"BATCH COMPLETE: {len(results)} succeeded, {len(errors)} failed.")
    print("=" * 50 + "\n")

    # Step 3: Rank Candidates
    results.sort(key=lambda x: x['ai_score'], reverse=True)
    for i, r in enumerate(results, 1):
        r['rank'] = i
        
    # Step 4: Link small batches to Analytics and save to History
    j_id = uuid.uuid4().hex
    _batch_jobs[j_id] = {
        "status": "done",
        "processed": len(results),
        "total": len(results),
        "results": results,
        "errors": errors,
        "batch_run_id": j_id
    }
    
    if user_email:
        # Safely calculate average score to avoid division by zero
        avg = round(sum(r['ai_score'] for r in results) / max(1, len(results)), 1)
        _save_history_entry(user_email, {
            "type": "batch",
            "created_at": datetime.now().strftime("%b %d, %Y %H:%M"),
            "job_role": job_role,
            "total_candidates": len(results),
            "avg_score": avg,
            "details": {"ranked": results, "errors": errors, "batch_run_id": j_id}
        })

    return jsonify({
        "success": True,
        "job_role": job_role,
        "total": len(results),
        "ranked": results,
        "errors": errors,
        "batch_run_id": j_id
    })

import threading
import uuid
import io
import zipfile
from werkzeug.datastructures import FileStorage

@app.route('/api/batch-large', methods=['POST'])
def batch_large():
    if 'files[]' not in request.files:
        return jsonify({"error": "No files provided."}), 400
    
    files = request.files.getlist('files[]')
    job_role = request.form.get('job_role', DEFAULT_ROLE)
    
    job_id = uuid.uuid4().hex
    files_to_process = []
    errors = []
    
    # Step 1: Extract and hold raw file bytes in memory to get the exact total
    for f in files:
        name = f.filename.lower()
        if name.endswith('.zip') or f.mimetype in ['application/zip', 'application/x-zip-compressed']:
            try:
                zip_bytes = f.read()
                with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as z:
                    for info in z.infolist():
                        if info.is_dir() or '__MACOSX' in info.filename or info.filename.split('/')[-1].startswith('.'):
                            continue
                        ext = info.filename.lower()
                        if ext.endswith(('.pdf', '.docx', '.txt')):
                            file_bytes = z.read(info.filename)
                            base_name = info.filename.split('/')[-1]
                            files_to_process.append({"filename": base_name, "data": file_bytes, "ext": ext})
            except Exception as e:
                errors.append({"filename": f.filename, "error": f"ZIP error: {str(e)}"})
        else:
            if name.endswith(('.pdf', '.docx', '.txt')):
                files_to_process.append({"filename": f.filename, "data": f.read(), "ext": name})

    total_files = len(files_to_process)
    
    # Step 2: Initialize the job tracker state
    _batch_jobs[job_id] = {
        "status": "processing",
        "processed": 0,
        "total": total_files,
        "results": [],
        "errors": errors,
        "batch_run_id": job_id
    }
    sess, _ = _get_session()
    user_email = sess['email'] if sess else None

    # Step 3: Define the background worker
    def background_worker(j_id, f_list, role):
        # Pre-load models in this thread to avoid lazy-loading race conditions
        get_model()
        _get_model_vocab()
        
        for item in f_list:
            # Reconstruct the file stream specifically for the parser
            mock_file = FileStorage(
                stream=io.BytesIO(item["data"]),
                filename=item["filename"],
                content_type="application/pdf" if item["ext"].endswith('.pdf') else "text/plain"
            )
            try:
                raw_text = parse_file_to_text(mock_file)
                a        = analyze_resume(raw_text, role)
                score    = score_text(a['found_skills'], a['exp'], a['education'], a['certification'],
                                      a['projects_count'], role, text_lower=a['_text_lower'], radar_scores=a['section_scores'])
                
                tier = ("Elite Candidate" if score>=85 else "Strong Profile" if score>=70
                        else "Developing Profile" if score>=50 else "Needs Work")
                
                _batch_jobs[j_id]["results"].append({
                    "filename":          mock_file.filename,
                    "candidate_id":      mock_file.filename,
                    "ai_score":          score,
                    "match_pct":         score,               
                    "predicted_category":a['guessed_category'],            
                    "tier":              tier,
                    "exp":               a['exp'],
                    "education":         a['education'],
                    "certification":     a['certification'],
                    "found_skills":      a['found_skills'][:8],
                    "missing_skills":    a['missing_skills'][:6],
                    "ats_score":         a['ats_score'],
                    "section_scores":    a['section_scores'],
                })
            except Exception as e:
                _batch_jobs[j_id]["errors"].append({"filename": mock_file.filename, "error": str(e)})
            
            # Update the progress counter live (this is what the UI polls!)
            _batch_jobs[j_id]["processed"] += 1

        # Rank candidates when finished
        _batch_jobs[j_id]["results"].sort(key=lambda x: x['ai_score'], reverse=True)
        for i, r in enumerate(_batch_jobs[j_id]["results"], 1):
            r['rank'] = i
            
        _batch_jobs[j_id]["status"] = "done"
        if user_email:
            res_list = _batch_jobs[j_id]["results"]
            avg = round(sum(r['ai_score'] for r in res_list) / max(1, len(res_list)), 1)
            _save_history_entry(user_email, {
                "type": "batch",
                "created_at": datetime.now().strftime("%b %d, %Y %H:%M"),
                "job_role": role,
                "total_candidates": len(res_list),
                "avg_score": avg,
                "details": {"ranked": res_list, "errors": _batch_jobs[j_id]["errors"], "batch_run_id": j_id}
            })

    # Step 4: Start the background thread
    thread = threading.Thread(target=background_worker, args=(job_id, files_to_process, job_role))
    thread.daemon = True
    thread.start()

    # Step 5: Immediately return the Job ID so the frontend can start polling
    return jsonify({"success": True, "job_id": job_id, "total": total_files})

@app.route('/api/batch-status/<job_id>', methods=['GET'])
def batch_status(job_id):
    job = _batch_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# =============================================================================
# AUTH ROUTES — Persistent SQLite Database
# =============================================================================
SESSION_COOKIE_NAME = 'resumeai_token'
SESSION_DAYS = int(os.environ.get('SESSION_DAYS', '7'))

def _hash(pw): return generate_password_hash(pw, method='pbkdf2:sha256', salt_length=16)

def _verify_password(stored_hash, password):
    if not stored_hash:
        return False
    if stored_hash.startswith(('pbkdf2:', 'scrypt:')):
        return check_password_hash(stored_hash, password)
    return stored_hash == hashlib.sha256(password.encode()).hexdigest()

def _make_token(): return secrets.token_hex(32)

def _get_session():
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None, None
    session_record = AuthSession.query.filter_by(token=token).first()
    if session_record and session_record.user:
        expires_at = session_record.expires_at
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                db.session.delete(session_record)
                db.session.commit()
                return None, token
        return {"email": session_record.user.email, "role": session_record.user.role}, token
    return None, token

def _set_auth_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=app.config['SESSION_COOKIE_SECURE'],
        samesite=app.config['SESSION_COOKIE_SAMESITE'],
        max_age=86400 * SESSION_DAYS,
    )
    return response

@app.route('/api/signup', methods=['POST'])
def signup():
    body = request.get_json(silent=True) or {}
    email    = (body.get('email') or '').strip().lower()
    password = body.get('password') or ''
    role     = body.get('role', 'candidate')
    
    if not email or not password:
        return jsonify({"success": False, "error": "Email and password required"}), 400
        
    # Validate unique email
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"success": False, "error": "Email is already registered. Please log in."}), 409
        
    if role not in ('candidate', 'recruiter'):
        role = 'candidate'
        
    # Save permanent user
    new_user = User(email=email, password_hash=_hash(password), role=role)
    db.session.add(new_user)
    db.session.commit()
    
    # Create persistent session
    token = _make_token()
    new_session = AuthSession(
        token=token,
        user_id=new_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    )
    db.session.add(new_session)
    db.session.commit()
    
    return _set_auth_cookie(jsonify({"success": True, "role": role, "email": email}), token)

@app.route('/api/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    email    = (body.get('email') or '').strip().lower()
    password = body.get('password') or ''
    
    if not email or not password:
        return jsonify({"success": False, "error": "Email and password required"}), 400
        
    # Verify user
    user = User.query.filter_by(email=email).first()
    if not user or not _verify_password(user.password_hash, password):
        return jsonify({"success": False, "error": "Invalid email or password"}), 401
    if not user.password_hash.startswith(('pbkdf2:', 'scrypt:')):
        user.password_hash = _hash(password)
        
    # Create persistent session
    token = _make_token()
    new_session = AuthSession(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    )
    db.session.add(new_session)
    db.session.commit()
    
    return _set_auth_cookie(jsonify({"success": True, "role": user.role, "email": email}), token)

@app.route('/api/logout', methods=['POST'])
def logout():
    sess, token = _get_session()
    if token:
        # Destroy session in database
        session_record = AuthSession.query.filter_by(token=token).first()
        if session_record:
            db.session.delete(session_record)
            db.session.commit()
            
    resp = jsonify({"success": True})
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp

@app.route('/api/me', methods=['GET'])
def me():
    sess, _ = _get_session()
    if not sess:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "email": sess['email'], "role": sess['role']})

def require_auth():
    sess, _ = _get_session()
    if not sess:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    return sess, None

# =============================================================================
# SCAN HISTORY — in-memory per session (persists while server runs)
# =============================================================================

_scan_history = {}   # email -> list of scan dicts

def _save_history_entry(email, entry):
    if not email:
        return
    if email not in _scan_history:
        _scan_history[email] = []
    _scan_history[email].append(entry)
    try:
        db.session.add(ScanHistory(
            email=email,
            scan_type=entry.get("type", "single"),
            job_role=entry.get("job_role"),
            payload=entry,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

@app.route('/api/history', methods=['GET'])
def get_history():
    sess, err = require_auth()
    if err: return err
    records = ScanHistory.query.filter_by(email=sess['email']).order_by(ScanHistory.created_at.desc()).all()
    scans = [r.payload for r in records] if records else list(reversed(_scan_history.get(sess['email'], [])))
    return jsonify({"success": True, "history": scans})

def _save_scan(email, scan_data):
    """Called after every successful /api/score to persist to history."""
    _save_history_entry(email, {
        "type": "single",
        "created_at": datetime.now().strftime("%b %d, %Y %H:%M"),
        "job_role":       scan_data.get("job_role", "—"),
        "target_company": scan_data.get("target_company", "—"),
        "ai_score":       scan_data.get("ai_score", 0),
        "tier":           _tier(scan_data.get("ai_score", 0)),
        "details":        scan_data,   # full payload for "View Report"
    })

def _tier(score):
    if score >= 85: return "Elite Candidate"
    if score >= 70: return "Strong Profile"
    if score >= 50: return "Developing"
    return "Needs Work"

# =============================================================================
# AI FEATURE ROUTES — red-flags, scorecard, outreach (Groq-powered)
# =============================================================================

@app.route('/api/red-flags', methods=['POST'])
def red_flags():
    sess, err = require_auth()
    if err: return err
    body = request.get_json(silent=True) or {}
    try:
        prompt = f"""You are a senior hiring manager reviewing a resume for a {body.get('job_role','Software Engineer')} role.

Candidate: {body.get('exp',0)} years exp, education: {body.get('education','Unknown')}, score: {body.get('score',0)}/100
Found skills: {', '.join(body.get('found_skills',[])[:10])}
Missing skills: {', '.join(body.get('missing_skills',[])[:8])}

Identify 3-5 resume red flags. Respond ONLY as a JSON array (no markdown):
[{{"flag":"...","severity":"High|Medium|Low","details":"one-line explanation"}}]"""
        flags = groq_json(prompt, 700)
        return jsonify({"success": True, "flags": flags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/scorecard', methods=['POST'])
def scorecard():
    sess, err = require_auth()
    if err: return err
    body = request.get_json(silent=True) or {}
    try:
        prompt = f"""Create a structured interview scorecard for a {body.get('job_role','Software Engineer')} candidate.

Profile: {body.get('exp',0)} years exp, skills: {', '.join(body.get('found_skills',[])[:10])}

Generate 5 evaluation competencies. Respond ONLY as a JSON array (no markdown):
[{{"competency":"...","question":"...","look_for":"what a great answer includes"}}]"""
        scorecard_data = groq_json(prompt, 800)
        return jsonify({"success": True, "scorecard": scorecard_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/outreach', methods=['POST'])
def outreach():
    sess, err = require_auth()
    if err: return err
    body = request.get_json(silent=True) or {}
    try:
        prompt = f"""Write a recruiter outreach email to invite a candidate for a {body.get('job_role','Software Engineer')} interview.

Candidate profile: {body.get('exp',0)} years exp, score {body.get('score',0)}/100, skills: {', '.join(body.get('found_skills',[])[:8])}

Respond ONLY as JSON (no markdown):
{{"subject":"...","body":"3-paragraph professional email, warm tone, under 200 words"}}"""
        email_data = groq_json(prompt, 500)
        return jsonify({"success": True, "email": email_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================================================
# ANALYTICS OVERVIEW — supports the Candidates page
# =============================================================================

@app.route('/api/analytics/overview', methods=['GET'])
def analytics_overview():
    sess, err = require_auth()
    if err: return err
    # Return all history entries from all users (recruiter view)
    all_entries = []
    for email, scans in _scan_history.items():
        for s in scans:
            all_entries.append({
                "id":         id(s),
                "email":      email,
                "job_role":   s.get("job_role","—"),
                "ai_score":   s.get("ai_score", 0),
                "experience": s.get("details",{}).get("extracted_experience", 0),
                "education":  s.get("details",{}).get("extracted_education","—"),
                "created_at": s.get("created_at","—"),
            })
    all_entries = []
    records = ScanHistory.query.order_by(ScanHistory.created_at.desc()).all()
    history_entries = [(record.email, record.payload, record.id) for record in records]
    if not history_entries:
        history_entries = [
            (email, scan, abs(hash(f"{email}:{idx}:{scan.get('created_at', '')}")))
            for email, scans in _scan_history.items()
            for idx, scan in enumerate(scans)
        ]

    for email, s, record_id in history_entries:
        if s.get("type") == "batch":
            ranked = s.get("details", {}).get("ranked", [])
            for idx, candidate in enumerate(ranked, 1):
                stable_id = f"{record_id}-{idx}"
                all_entries.append({
                    "id": stable_id,
                    "candidate_id": stable_id,
                    "email": email,
                    "filename": candidate.get("filename") or candidate.get("candidate_id") or f"Candidate {idx}",
                    "job_role": s.get("job_role", "â€”"),
                    "ai_score": candidate.get("ai_score", 0),
                    "match_pct": candidate.get("match_pct", candidate.get("ai_score", 0)),
                    "predicted_category": candidate.get("predicted_category", "Unclassified"),
                    "experience": candidate.get("exp", 0),
                    "exp": candidate.get("exp", 0),
                    "education": candidate.get("education", "â€”"),
                    "tier": candidate.get("tier") or _tier(candidate.get("ai_score", 0)),
                    "found_skills": candidate.get("found_skills", []),
                    "missing_skills": candidate.get("missing_skills", []),
                    "section_scores": candidate.get("section_scores", {}),
                    "created_at": s.get("created_at", "â€”"),
                })
        else:
            details = s.get("details", {})
            all_entries.append({
                "id": str(record_id),
                "candidate_id": str(record_id),
                "email": email,
                "filename": f"{email} resume",
                "job_role": s.get("job_role", "â€”"),
                "ai_score": s.get("ai_score", 0),
                "match_pct": s.get("ai_score", 0),
                "predicted_category": details.get("predicted_category", "Unclassified"),
                "experience": details.get("extracted_experience", 0),
                "exp": details.get("extracted_experience", 0),
                "education": details.get("extracted_education", "â€”"),
                "tier": s.get("tier") or _tier(s.get("ai_score", 0)),
                "found_skills": details.get("found_skills", []),
                "missing_skills": details.get("missing_skills", []),
                "section_scores": details.get("section_scores", {}),
                "created_at": s.get("created_at", "â€”"),
            })

    all_entries.sort(key=lambda x: x['ai_score'], reverse=True)
    min_score  = float(request.args.get('min_score', 0))
    role_filter= request.args.get('job_role','').strip()
    if min_score:
        all_entries = [e for e in all_entries if e['ai_score'] >= min_score]
    if role_filter:
        all_entries = [e for e in all_entries if role_filter.lower() in e['job_role'].lower()]
    page     = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    total    = len(all_entries)
    pages    = max(1, (total + per_page - 1) // per_page)
    start    = (page - 1) * per_page
    return jsonify({"success": True, "total": total, "page": page, "pages": pages,
                    "candidates": all_entries[start:start+per_page]})

# =============================================================================
# BATCH ANALYTICS & PDF EXPORT
# =============================================================================

@app.route('/api/analytics/batch/<batch_id>', methods=['GET'])
def batch_analytics(batch_id):
    sess, err = require_auth()
    if err: return err

    # _batch_jobs is the global dictionary we added earlier to track large batches
    job = _batch_jobs.get(batch_id)
    if not job or job['status'] != 'done':
        return jsonify({"error": "Batch not found or still processing"}), 404

    results = job['results']
    if not results:
        return jsonify({"error": "No candidates found in this batch"}), 404

    # Prepare data dictionaries for the frontend Chart.js components
    score_dist = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
    tier_breakdown = {"excellent": 0, "good": 0, "average": 0, "rejected": 0}
    cat_dist = {}
    skill_counts = {}
    exp_dist = {"0-2y": 0, "3-5y": 0, "6-10y": 0, "10+y": 0}
    edu_dist = {}

    for r in results:
        score = r.get('ai_score', 0)
        
        # 1. Score Distribution
        if score >= 90: score_dist["90-100"] += 1
        elif score >= 80: score_dist["80-89"] += 1
        elif score >= 70: score_dist["70-79"] += 1
        elif score >= 60: score_dist["60-69"] += 1
        else: score_dist["<60"] += 1

        # 2. Tier Breakdown
        if score >= 85: tier_breakdown["excellent"] += 1
        elif score >= 70: tier_breakdown["good"] += 1
        elif score >= 50: tier_breakdown["average"] += 1
        else: tier_breakdown["rejected"] += 1

        # 3. Category Distribution
        cat = r.get('predicted_category', 'Unknown')
        cat_dist[cat] = cat_dist.get(cat, 0) + 1

        # 4. Top Skills
        for skill in r.get('found_skills', []):
            skill_counts[skill] = skill_counts.get(skill, 0) + 1

        # 5. Experience Distribution
        exp = r.get('exp', 0)
        if exp <= 2: exp_dist["0-2y"] += 1
        elif exp <= 5: exp_dist["3-5y"] += 1
        elif exp <= 10: exp_dist["6-10y"] += 1
        else: exp_dist["10+y"] += 1

        # 6. Education Distribution
        edu = r.get('education', 'Unknown')
        edu_dist[edu] = edu_dist.get(edu, 0) + 1

    # Sort skills by frequency for the bar chart
    top_tech = [{"skill": k, "count": v} for k, v in sorted(skill_counts.items(), key=lambda item: item[1], reverse=True)[:10]]

    return jsonify({
        "success": True,
        "score_distribution": score_dist,
        "tier_breakdown": tier_breakdown,
        "predicted_category_distribution": cat_dist,
        "top_technologies": top_tech,
        "experience_distribution": exp_dist,
        "education_distribution": edu_dist
    })


@app.route('/api/analytics/batch/<batch_id>/export-pdf', methods=['GET'])
def batch_export_pdf(batch_id):
    sess, err = require_auth()
    if err: return err

    job = _batch_jobs.get(batch_id)
    if not job or job['status'] != 'done':
        return jsonify({"error": "Batch not found or still processing"}), 404

    threshold = float(request.args.get('threshold', 70))
    results = job['results']

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from flask import send_file
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()

        # Document Header
        elements.append(Paragraph(f"AI Resume Batch Screening Report", styles['Title']))
        elements.append(Paragraph(f"Minimum AI Score Threshold: {threshold}", styles['Normal']))
        elements.append(Spacer(1, 12))

        # Filter candidates based on the UI slider
        shortlisted = [r for r in results if r.get('ai_score', 0) >= threshold]
        rejected = [r for r in results if r.get('ai_score', 0) < threshold]

        elements.append(Paragraph(f"Total Candidates Processed: {len(results)}", styles['Normal']))
        elements.append(Paragraph(f"Shortlisted Candidates: {len(shortlisted)}", styles['Normal']))
        elements.append(Paragraph(f"Rejected Candidates: {len(rejected)}", styles['Normal']))
        elements.append(Spacer(1, 20))

        # Shortlisted Candidates Table
        elements.append(Paragraph("Shortlisted Candidates Overview", styles['Heading2']))
        
        # Table Headers
        data = [["Rank", "Candidate File", "AI Score", "Experience", "Category"]]
        
        # Populate table rows (Limit to top 100 to prevent PDF generation from crashing on massive batches)
        for r in shortlisted[:100]: 
            data.append([
                str(r.get('rank', '-')), 
                r.get('filename', 'Unknown')[:25], 
                str(r.get('ai_score', '')), 
                f"{r.get('exp', 0)} yrs", 
                r.get('predicted_category', '')
            ])

        if len(data) > 1:
            t = Table(data, colWidths=[40, 180, 60, 80, 120])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e293b")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 10),
                ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#f1f5f9")),
                ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#e2e8f0"))
            ]))
            elements.append(t)
        else:
            elements.append(Paragraph("No candidates met the required threshold.", styles['Normal']))

        doc.build(elements)
        buffer.seek(0)

        return send_file(buffer, as_attachment=True, download_name=f"Batch_Report_{batch_id}.pdf", mimetype='application/pdf')

    except ImportError:
        return jsonify({"error": "ReportLab is not installed. Please run: pip install reportlab"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug)
