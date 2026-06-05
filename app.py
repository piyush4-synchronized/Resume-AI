from email import message

from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import pdfplumber
import re
import os
import io
import sys
from groq import Groq 

# ── Fix for pickle deserialization ──────────────────────────────────────────
def split_skills(text):
    return text.split(', ')

import __main__
__main__.split_skills = split_skills
# ────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# ── Groq client (reads GROQ_API_KEY from env) ─────────────────────
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ── Lazy singleton — loads once on first request ─────────────────────────────
_model = None

def get_model():
    global _model
    if _model is None:
        _model = joblib.load('resume_scorer_pipeline.pkl')
    return _model

# ── File parsers ────────────────────────────────────────────────────────────
def extract_text_from_pdf(file_stream):
    text = ""
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + " "
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

# ── Role-specific skill sets ─────────────────────────────────────────────────
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

# ── Education tier map (must match the one used during retraining) ────────────
EDU_TIER_MAP = {
    'Diploma': 1,
    'B.Sc':    2, 'B.Tech': 2,
    'M.Tech':  3, 'MBA':    3, 'M.Sc': 3,
    'PhD':     4,
}

ATS_KEYWORDS = [
    'experience','education','skills','projects','certifications','achievements',
    'summary','objective','responsibilities','developed','managed','led','built',
    'designed','implemented','optimized','collaborated','achieved','improved',
    'bachelor','master','degree','university','college','gpa','intern',
    'full-stack','software engineer','developer','analyst','architect'
]

# ────────────────────────────────────────────────────────────────────────────
# FEATURE 1 — MODEL LIMITATION FIX: Real NLP extraction (no more hardcoded defaults)
# ────────────────────────────────────────────────────────────────────────────

EDU_PATTERNS = {
    'PhD': ['phd', 'ph.d', 'doctorate', 'doctor of philosophy'],
    'M.Tech': ['m.tech', 'mtech', 'master of technology'],
    'MBA':    ['mba', 'master of business'],
    'M.Sc':   ['m.sc', 'msc', 'master of science', 'ms ', 'ms.'],
    'B.Tech': ['b.tech', 'btech', 'bachelor of technology', 'be ', 'b.e'],
    'B.Sc':   ['b.sc', 'bsc', 'bachelor of science', 'bs '],
    'Diploma':['diploma'],
}

CERT_KEYWORDS = [
    'aws certified', 'google ml', 'deep learning specialization',
    'azure certified', 'gcp certified', 'pmp', 'cissp', 'ceh',
    'tensorflow developer', 'coursera', 'udemy', 'certification', 'certified'
]

def extract_education(text_lower):
    """Detect highest education degree from resume text."""
    priority = ['PhD', 'M.Tech', 'MBA', 'M.Sc', 'B.Tech', 'B.Sc', 'Diploma']
    for degree in priority:
        for kw in EDU_PATTERNS[degree]:
            if kw in text_lower:
                return degree
    return 'B.Tech'   # fallback

def extract_certifications(text_lower):
    """Return first matched certification keyword or 'None'."""
    for cert in CERT_KEYWORDS:
        if cert in text_lower:
            return cert.title()
    return 'None'

def extract_projects_count(text_lower):
    """Count distinct project mentions heuristically."""
    # Count lines/bullet points that look like project headings
    count = len(re.findall(r'\bproject\b', text_lower))
    return min(count, 10)   # cap at 10 to stay within training distribution

def analyze_resume(raw_text, job_role=DEFAULT_ROLE):
    text_lower = raw_text.lower()
    role_skills = ROLE_SKILLS.get(job_role, ROLE_SKILLS[DEFAULT_ROLE])

    found_skills  = [s for s in role_skills if s in text_lower]
    missing_skills = [s for s in role_skills if s not in text_lower][:12]

    # ── Section scores (0-100) ──
    exp = 0
    exp_match = re.search(r'(\d+)\+?\s*(years|yrs)', text_lower)
    if exp_match:
        exp = int(exp_match.group(1))
    exp_score = min(100, exp * 12)

    edu_score = 0
    for kw, pts in [('phd',100),('master',85),('mba',85),('b.tech',70),('bachelor',70),('diploma',50)]:
        if kw in text_lower:
            edu_score = pts; break

    proj_count = extract_projects_count(text_lower)
    proj_score = min(100, proj_count * 15)

    cert_count = len(re.findall(r'certif', text_lower))
    cert_score = min(100, cert_count * 25)

    skills_score = min(100, len(found_skills) * 6)

    ats_hits  = [k for k in ATS_KEYWORDS if k in text_lower]
    ats_score = min(100, int((len(ats_hits) / len(ATS_KEYWORDS)) * 100))

    radar = {
        'Experience':    exp_score,
        'Education':     edu_score,
        'Projects':      proj_score,
        'Certifications':cert_score,
        'Skills':        skills_score,
        'ATS Match':     ats_score,
    }

    # Real extracted values (used by score_text)
    education      = extract_education(text_lower)
    certification  = extract_certifications(text_lower)

    return {
        'exp':            exp,
        'education':      education,
        'certification':  certification,
        'projects_count': proj_count,
        'found_skills':   found_skills[:15],
        'missing_skills': missing_skills,
        'section_scores': radar,
        'ats_score':      ats_score,
        'ats_hits':       ats_hits[:10],
    }

def score_text(found_skills, exp, education, certification, projects_count, job_role=DEFAULT_ROLE):
    """
    Call the XGBoost pipeline with REAL extracted features instead of hardcoded defaults.
    Includes the three new engineered columns added during model retraining:
      Edu_Tier, Has_Cert, Skill_Exp_Score
    """
    import numpy as np

    skills_string = ", ".join(found_skills)

    user_data = pd.DataFrame([{
        'Skills':              skills_string,
        'Experience (Years)':  exp,
        'Education':           education,
        'Certifications':      certification,
        'Job Role':            job_role,
        'Projects Count':      projects_count,
    }])

    n_skills = len(found_skills)
    user_data['Total_Skills']       = n_skills
    user_data['Projects_Per_Year']  = user_data['Projects Count'] / (user_data['Experience (Years)'] + 1)
    # New columns — must match the retrained model
    user_data['Edu_Tier']           = EDU_TIER_MAP.get(education, 2)
    user_data['Has_Cert']           = 0 if certification == 'None' else 1
    user_data['Skill_Exp_Score']    = n_skills * float(np.log1p(exp))

    score = get_model().predict(user_data)[0]
    return round(max(0, min(100, float(score))), 2)

# ────────────────────────────────────────────────────────────────────────────
# FEATURE 2 — INTERVIEW QUESTION GENERATOR (Claude API)
# ────────────────────────────────────────────────────────────────────────────

def generate_interview_questions(job_role, found_skills, missing_skills, exp, score):
    """
    Ask Claude to generate role-specific interview questions based on the
    candidate's skill profile, gaps, and seniority level.
    """
    tier = (
        "senior"   if exp >= 6 else
        "mid-level" if exp >= 3 else
        "junior/entry-level"
    )

    prompt = f"""You are a senior technical recruiter interviewing a {tier} {job_role} candidate.

Candidate profile:
- Score: {score}/100
- Years of experience: {exp}
- Strong skills: {', '.join(found_skills[:10]) if found_skills else 'Not specified'}
- Skill gaps (missing from their resume): {', '.join(missing_skills[:6]) if missing_skills else 'None detected'}

Generate exactly 8 interview questions for this candidate.
Rules:
1. Mix of technical, behavioural, and situational questions.
2. 3 questions should probe their STRONG skills to verify depth.
3. 3 questions should gently probe their SKILL GAPS to assess awareness and learning ability.
4. 2 questions should be behavioural/culture fit appropriate for a {tier} hire.
5. For each question include a one-line hint to the interviewer on what a good answer looks like.

Respond ONLY as a JSON array (no markdown fences, no preamble) with this exact shape:
[
  {{"question": "...", "category": "technical|behavioural|situational", "hint": "..."}},
  ...
]"""

    message = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    max_tokens=1000,
    messages=[{"role": "user", "content": prompt}]
    )
    import json
    raw = message.choices[0].message.content.strip()

    # Strip accidental markdown fences if Claude adds them
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

# ── Helper: one reusable Groq call ──────────────────────────────────────────
def groq_generate(prompt, max_tokens=1024):
    message = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.choices[0].message.content.strip()


# ── FEATURE A: Cover Letter Generator ───────────────────────────────────────
def generate_cover_letter(job_role, found_skills, exp, education, company_name="the company"):
    prompt = f"""You are an expert career coach. Write a professional, ATS-friendly cover letter.

Candidate profile:
- Target Role: {job_role}
- Experience: {exp} years
- Education: {education}
- Key Skills: {', '.join(found_skills[:12])}
- Applying to: {company_name}

Rules:
1. 3 paragraphs: opening hook, value proposition, call to action.
2. Naturally include these skills as keywords: {', '.join(found_skills[:8])}
3. Confident but not arrogant tone.
4. Under 300 words.
5. Return plain text only, no placeholders like [Your Name]."""

    return groq_generate(prompt, max_tokens=600)


# ── FEATURE B: Resume Rewrite Suggestions ───────────────────────────────────
def generate_rewrite_suggestions(raw_text, missing_skills, job_role):
    prompt = f"""You are a senior resume coach. Analyse this resume text and give improvement suggestions.

Target Role: {job_role}
Missing Skills to add: {', '.join(missing_skills[:8])}

Resume Text (first 1500 chars):
{raw_text[:1500]}

Give exactly 4 suggestions in this JSON format (no markdown fences):
[
  {{"section": "Summary", "issue": "...", "rewritten": "..."}},
  {{"section": "Skills", "issue": "...", "rewritten": "..."}},
  {{"section": "Experience Bullets", "issue": "...", "rewritten": "..."}},
  {{"section": "Keywords", "issue": "...", "rewritten": "..."}}
]"""

    import json
    raw = groq_generate(prompt, max_tokens=800)
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ── FEATURE C: LinkedIn Summary Generator ───────────────────────────────────
def generate_linkedin_summary(job_role, found_skills, exp, education):
    prompt = f"""Write a compelling LinkedIn 'About' section for a {job_role} professional.

Profile:
- Experience: {exp} years
- Education: {education}  
- Top Skills: {', '.join(found_skills[:12])}

Rules:
1. 3 short paragraphs (max 300 words total).
2. Start with a strong first-person hook (no "I am a...").
3. Include relevant keywords for recruiter search.
4. End with what opportunities they are open to.
5. Plain text only."""

    return groq_generate(prompt, max_tokens=400)


# ── FEATURE D: Salary Estimator ─────────────────────────────────────────────
def generate_salary_estimate(job_role, found_skills, exp, location="India"):
    prompt = f"""You are a compensation expert. Estimate a realistic salary range.

Profile:
- Role: {job_role}
- Experience: {exp} years
- Location: {location}
- Skills: {', '.join(found_skills[:10])}

Respond ONLY as JSON (no markdown fences):
{{
  "min_salary": "...",
  "max_salary": "...",
  "currency": "INR or USD based on location",
  "level": "Junior / Mid / Senior",
  "skills_to_increase_salary": ["skill1", "skill2", "skill3"],
  "market_insight": "2-line context about this role's market demand"
}}"""

    import json
    raw = groq_generate(prompt, max_tokens=400)
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ── FEATURE E: 30-60-90 Day Learning Roadmap ────────────────────────────────
def generate_learning_roadmap(job_role, missing_skills, exp):
    level = "senior" if exp >= 6 else "mid-level" if exp >= 3 else "beginner"
    prompt = f"""Create a 90-day skill-building roadmap for a {level} {job_role}.

Skills to learn: {', '.join(missing_skills[:8])}

Respond ONLY as JSON (no markdown fences):
{{
  "day_1_30": {{
    "focus": "...",
    "tasks": ["task1", "task2", "task3"],
    "resource": "specific course or resource name"
  }},
  "day_31_60": {{
    "focus": "...",
    "tasks": ["task1", "task2", "task3"],
    "resource": "specific course or resource name"
  }},
  "day_61_90": {{
    "focus": "...",
    "tasks": ["task1", "task2", "task3"],
    "resource": "specific course or resource name"
  }},
  "milestone": "What the candidate should be able to show/build by day 90"
}}"""

    import json
    raw = groq_generate(prompt, max_tokens=600)
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ────────────────────────────────────────────────────────────────────────────
# FEATURE 3 — RECRUITER BATCH MODE
# ────────────────────────────────────────────────────────────────────────────

def parse_file_to_text(file_obj):
    """Dispatch file extraction by extension."""
    name = file_obj.filename.lower()
    # Save to a temporary BytesIO (pdfplumber needs seekable stream)
    data = file_obj.read()
    stream = io.BytesIO(data)
    if name.endswith('.pdf'):
        return extract_text_from_pdf(stream)
    elif name.endswith('.docx'):
        return extract_text_from_docx(stream)
    elif name.endswith('.txt'):
        return data.decode('utf-8', errors='replace')
    else:
        raise ValueError(f"Unsupported file type: {name}")


# ════════════════════════════════════════════════════════════════════════════
# HTML PAGE  (same as before — omitted here for brevity, paste your original)
# ════════════════════════════════════════════════════════════════════════════
# NOTE: Keep your original HTML_PAGE string here unchanged.
HTML_PAGE = "<!-- paste your original HTML_PAGE string here -->"


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def home():
    return HTML_PAGE


# ── Existing: score a single uploaded file ───────────────────────────────────
@app.route('/api/score', methods=['POST'])
def score_resume():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file     = request.files['file']
    filename = file.filename.lower()
    job_role = request.form.get('job_role', 'Software Engineer')

    try:
        if filename.endswith('.pdf'):
            raw_text = extract_text_from_pdf(file)
        elif filename.endswith('.docx'):
            raw_text = extract_text_from_docx(file)
        elif filename.endswith('.txt'):
            raw_text = extract_text_from_txt(file)
        else:
            return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

        analysis    = analyze_resume(raw_text, job_role)
        final_score = score_text(
            analysis['found_skills'],
            analysis['exp'],
            analysis['education'],       # ✅ FEATURE 1
            analysis['certification'],   # ✅ FEATURE 1
            analysis['projects_count'],  # ✅ FEATURE 1
            job_role
        )

        return jsonify({
            "success":              True,
            "job_role":             job_role,
            "ai_score":             final_score,
            "extracted_experience": analysis['exp'],
            "extracted_education":  analysis['education'],   # new
            "found_skills":         analysis['found_skills'],
            "missing_skills":       analysis['missing_skills'],
            "section_scores":       analysis['section_scores'],
            "ats_score":            analysis['ats_score'],
            "ats_hits":             analysis['ats_hits'],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Existing: score raw pasted text ─────────────────────────────────────────
@app.route('/api/score-text', methods=['POST'])
def score_resume_text():
    body = request.get_json(silent=True)
    if not body or not body.get('text', '').strip():
        return jsonify({"error": "No text provided"}), 400

    raw_text = body['text']
    job_role = body.get('job_role', 'Software Engineer')

    try:
        analysis    = analyze_resume(raw_text, job_role)
        final_score = score_text(
            analysis['found_skills'],
            analysis['exp'],
            analysis['education'],
            analysis['certification'],
            analysis['projects_count'],
            job_role
        )

        return jsonify({
            "success":              True,
            "job_role":             job_role,
            "ai_score":             final_score,
            "extracted_experience": analysis['exp'],
            "extracted_education":  analysis['education'],
            "found_skills":         analysis['found_skills'],
            "missing_skills":       analysis['missing_skills'],
            "section_scores":       analysis['section_scores'],
            "ats_score":            analysis['ats_score'],
            "ats_hits":             analysis['ats_hits'],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── FEATURE 2: Interview question generator ──────────────────────────────────
@app.route('/api/interview-questions', methods=['POST'])
def interview_questions():
    """
    Expects JSON body:
    {
        "job_role": "Software Engineer",
        "found_skills": ["python", "docker", ...],
        "missing_skills": ["kubernetes", ...],
        "exp": 4,
        "score": 72.5
    }
    Returns:
    {
        "success": true,
        "questions": [
            {"question": "...", "category": "technical", "hint": "..."},
            ...
        ]
    }
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body provided"}), 400

    job_role      = body.get('job_role', DEFAULT_ROLE)
    found_skills  = body.get('found_skills', [])
    missing_skills = body.get('missing_skills', [])
    exp           = body.get('exp', 0)
    score         = body.get('score', 50)

    try:
        questions = generate_interview_questions(
            job_role, found_skills, missing_skills, exp, score
        )
        return jsonify({"success": True, "questions": questions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/cover-letter', methods=['POST'])
def cover_letter():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    try:
        result = generate_cover_letter(
            body.get('job_role', DEFAULT_ROLE),
            body.get('found_skills', []),
            body.get('exp', 0),
            body.get('education', 'B.Tech'),
            body.get('company_name', 'the company')
        )
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
            body.get('raw_text', ''),
            body.get('missing_skills', []),
            body.get('job_role', DEFAULT_ROLE)
        )
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
            body.get('job_role', DEFAULT_ROLE),
            body.get('found_skills', []),
            body.get('exp', 0),
            body.get('education', 'B.Tech')
        )
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
            body.get('job_role', DEFAULT_ROLE),
            body.get('found_skills', []),
            body.get('exp', 0),
            body.get('location', 'India')
        )
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
            body.get('job_role', DEFAULT_ROLE),
            body.get('missing_skills', []),
            body.get('exp', 0)
        )
        return jsonify({"success": True, "roadmap": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── FEATURE 3: Recruiter batch mode ─────────────────────────────────────────
@app.route('/api/batch-score', methods=['POST'])
def batch_score():
    """
    Accepts multipart/form-data with:
      - files[]:   up to 20 resume files (PDF / DOCX / TXT)
      - job_role:  target role string

    Returns a ranked JSON array of candidates sorted by score descending.

    Example curl:
      curl -X POST http://localhost:5000/api/batch-score \\
           -F "files[]=@cv1.pdf" -F "files[]=@cv2.pdf" \\
           -F "job_role=Data Scientist"
    """
    if 'files[]' not in request.files:
        return jsonify({"error": "No files provided. Use field name 'files[]'."}), 400

    files    = request.files.getlist('files[]')
    job_role = request.form.get('job_role', DEFAULT_ROLE)

    if len(files) > 20:
        return jsonify({"error": "Maximum 20 files per batch."}), 400

    results  = []
    errors   = []

    for f in files:
        try:
            raw_text    = parse_file_to_text(f)
            analysis    = analyze_resume(raw_text, job_role)
            final_score = score_text(
                analysis['found_skills'],
                analysis['exp'],
                analysis['education'],
                analysis['certification'],
                analysis['projects_count'],
                job_role
            )

            # Tier label
            tier = (
                "Elite Candidate"    if final_score >= 85 else
                "Strong Profile"     if final_score >= 70 else
                "Developing Profile" if final_score >= 50 else
                "Needs Work"
            )

            results.append({
                "filename":       f.filename,
                "ai_score":       final_score,
                "tier":           tier,
                "exp":            analysis['exp'],
                "education":      analysis['education'],
                "certification":  analysis['certification'],
                "found_skills":   analysis['found_skills'][:8],
                "missing_skills": analysis['missing_skills'][:6],
                "ats_score":      analysis['ats_score'],
                "section_scores": analysis['section_scores'],
            })

        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})

    # Sort by score descending — highest ranked candidate first
    results.sort(key=lambda x: x['ai_score'], reverse=True)

    # Add rank
    for idx, r in enumerate(results, start=1):
        r['rank'] = idx

    return jsonify({
        "success":   True,
        "job_role":  job_role,
        "total":     len(results),
        "ranked":    results,
        "errors":    errors,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)




