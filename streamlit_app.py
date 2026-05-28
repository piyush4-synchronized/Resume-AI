import streamlit as st
import joblib
import pandas as pd
import pdfplumber
import re
import io
import sys
import plotly.graph_objects as go

# ── Pickle fix ───────────────────────────────────────────────────────────────
def split_skills(text):
    return text.split(', ')

import __main__
__main__.split_skills = split_skills

# ── Load model ───────────────────────────────────────────────────────────────
@st.cache_resource
def load_model():
    return joblib.load('resume_scorer_pipeline.pkl')

model = load_model()

# ── Constants ────────────────────────────────────────────────────────────────
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

ATS_KEYWORDS = [
    'experience','education','skills','projects','certifications','achievements',
    'summary','objective','responsibilities','developed','managed','led','built',
    'designed','implemented','optimized','collaborated','achieved','improved',
    'bachelor','master','degree','university','college','gpa','intern',
    'full-stack','software engineer','developer','analyst','architect'
]

# ── Core logic ───────────────────────────────────────────────────────────────
def extract_text_from_pdf(file_stream):
    text = ""
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + " "
    return text.strip()

def extract_text_from_docx(file_stream):
    from docx import Document
    doc = Document(file_stream)
    return " ".join([p.text for p in doc.paragraphs if p.text.strip()])

def extract_text_from_txt(file_stream):
    raw = file_stream.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')

def analyze_resume(raw_text, job_role='Software Engineer'):
    text_lower = raw_text.lower()
    role_skills = ROLE_SKILLS.get(job_role, ROLE_SKILLS['Software Engineer'])

    found_skills = [s for s in role_skills if s in text_lower]
    missing_skills = [s for s in role_skills if s not in text_lower][:12]

    exp = 0
    exp_score = 0
    exp_match = re.search(r'(\d+)\+?\s*(years|yrs)', text_lower)
    if exp_match:
        exp = int(exp_match.group(1))
        exp_score = min(100, exp * 12)

    edu_score = 0
    for kw, pts in [('phd',100),('master',85),('mba',85),('b.tech',70),('bachelor',70),('diploma',50)]:
        if kw in text_lower:
            edu_score = pts
            break

    proj_count = len(re.findall(r'project', text_lower))
    proj_score = min(100, proj_count * 15)

    cert_count = len(re.findall(r'certif', text_lower))
    cert_score = min(100, cert_count * 25)

    skills_score = min(100, len(found_skills) * 6)

    ats_hits = [k for k in ATS_KEYWORDS if k in text_lower]
    ats_score = min(100, int((len(ats_hits) / len(ATS_KEYWORDS)) * 100))

    radar = {
        'Experience':     exp_score,
        'Education':      edu_score,
        'Projects':       proj_score,
        'Certifications': cert_score,
        'Skills':         skills_score,
        'ATS Match':      ats_score,
    }

    return {
        'exp': exp,
        'found_skills': found_skills[:15],
        'missing_skills': missing_skills,
        'section_scores': radar,
        'ats_score': ats_score,
        'ats_hits': ats_hits[:10],
    }

def score_text(found_skills, exp, job_role='Software Engineer'):
    skills_string = ", ".join(found_skills)
    user_data = pd.DataFrame([{
        'Skills': skills_string,
        'Experience (Years)': exp,
        'Education': 'B.Tech',
        'Certifications': 'None',
        'Job Role': job_role,
        'Projects Count': 3
    }])
    user_data['Total_Skills']      = len(found_skills)
    user_data['Projects_Per_Year'] = user_data['Projects Count'] / (user_data['Experience (Years)'] + 1)
    score = model.predict(user_data)[0]
    return round(max(0, min(100, float(score))), 2)

def get_tier(score):
    if score >= 85: return "🔥 Elite Candidate", "#4ADE80"
    if score >= 70: return "⭐ Strong Profile",   "#F7931A"
    if score >= 50: return "📈 Developing Profile","#FFD600"
    return "🛠 Needs Work", "#F87171"

def build_improvements(score, section_scores, missing_skills):
    tips = []
    if section_scores['Skills'] < 60:
        top_missing = missing_skills[:3]
        if top_missing:
            tips.append(f"Add key skills to your resume: **{', '.join(top_missing)}**.")
    if section_scores['Experience'] < 40:
        tips.append("Quantify your experience — mention years worked and measurable achievements.")
    if section_scores['Projects'] < 45:
        tips.append("Add more projects with clear descriptions of your role and technologies used.")
    if section_scores['Certifications'] < 50:
        tips.append("Consider adding certifications relevant to your target role.")
    if section_scores['Education'] < 70:
        tips.append("Include your highest education qualification clearly.")
    if section_scores['ATS Match'] < 50:
        tips.append("Use more industry-standard keywords to pass ATS filters.")
    if score >= 85:
        tips.append("Excellent profile! Keep your resume updated quarterly and tailor it per role.")
    return tips

# ── Plotly charts ─────────────────────────────────────────────────────────────
def make_radar(section_scores):
    categories = list(section_scores.keys())
    values     = list(section_scores.values())
    categories_closed = categories + [categories[0]]
    values_closed     = values + [values[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        fillcolor='rgba(247,147,26,0.18)',
        line=dict(color='#F7931A', width=2),
        name='Score'
    ))
    fig.update_layout(
        polar=dict(
            bgcolor='rgba(0,0,0,0)',
            radialaxis=dict(visible=True, range=[0,100],
                            gridcolor='rgba(255,255,255,0.1)',
                            tickfont=dict(color='#94A3B8', size=10)),
            angularaxis=dict(gridcolor='rgba(255,255,255,0.1)',
                             tickfont=dict(color='#FFFFFF', size=12))
        ),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        margin=dict(l=40, r=40, t=40, b=40),
        height=360,
    )
    return fig

def make_gauge(score):
    color = "#4ADE80" if score >= 70 else "#F7931A" if score >= 50 else "#F87171"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={'font': {'size': 52, 'color': color}},
        gauge={
            'axis': {'range': [0, 100], 'tickcolor': '#94A3B8',
                     'tickfont': {'color': '#94A3B8'}},
            'bar': {'color': color, 'thickness': 0.25},
            'bgcolor': 'rgba(255,255,255,0.05)',
            'borderwidth': 0,
            'steps': [
                {'range': [0,  50], 'color': 'rgba(248,113,113,0.12)'},
                {'range': [50, 70], 'color': 'rgba(247,147,26,0.12)'},
                {'range': [70,100], 'color': 'rgba(74,222,128,0.12)'},
            ],
        }
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=30, b=20),
        height=260,
    )
    return fig

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Resume Scorer",
    page_icon="📄",
    layout="centered",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Dark background */
.stApp { background: #030304; color: #FFFFFF; }

/* Hide default Streamlit header/footer */
#MainMenu, footer, header { visibility: hidden; }

/* Hero title */
.hero-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 2.6rem;
    font-weight: 700;
    text-align: center;
    background: linear-gradient(135deg, #F7931A, #FFD600);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 0.25rem;
}
.hero-sub {
    text-align: center;
    color: #94A3B8;
    font-size: 1rem;
    margin-bottom: 2rem;
}

/* Cards */
.card {
    background: #0F1115;
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1.25rem;
}
.card-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1rem;
    font-weight: 600;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: .08em;
    margin-bottom: 1rem;
}

/* Score big */
.score-wrap {
    text-align: center;
    padding: 1rem 0 0.5rem;
}
.tier-label {
    text-align: center;
    font-size: 1.2rem;
    font-weight: 600;
    margin-top: -0.5rem;
    margin-bottom: 0.5rem;
}

/* Skill chips */
.skill-chip {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 500;
    margin: 3px 3px;
}
.chip-found   { background: rgba(74,222,128,0.15); color: #4ADE80; border:1px solid rgba(74,222,128,0.3); }
.chip-missing { background: rgba(248,113,113,0.13); color: #F87171; border:1px solid rgba(248,113,113,0.3); }
.chip-ats     { background: rgba(247,147,26,0.15);  color: #F7931A; border:1px solid rgba(247,147,26,0.3); }

/* Section bar */
.bar-row { margin-bottom: 0.7rem; }
.bar-label { display:flex; justify-content:space-between; font-size:0.85rem; color:#CBD5E1; margin-bottom:4px; }
.bar-track { background:rgba(255,255,255,0.07); border-radius:999px; height:8px; }
.bar-fill  { height:8px; border-radius:999px; background: linear-gradient(90deg,#F7931A,#FFD600); }

/* Improve list */
.improve-item {
    display: flex;
    gap: 0.6rem;
    align-items: flex-start;
    padding: 0.6rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-size: 0.9rem;
    color: #CBD5E1;
}
.improve-dot { color: #F7931A; font-size: 1rem; margin-top:1px; }

/* Divider */
.divider { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 1.5rem 0; }

/* Streamlit widget overrides */
div[data-testid="stTabs"] button {
    color: #94A3B8 !important;
    font-weight: 500;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #F7931A !important;
    border-bottom-color: #F7931A !important;
}
div[data-testid="stSelectbox"] > div > div {
    background: #0F1115 !important;
    border-color: rgba(255,255,255,0.12) !important;
    color: #FFFFFF !important;
}
div[data-testid="stFileUploader"] {
    background: #0F1115 !important;
    border: 1px dashed rgba(247,147,26,0.4) !important;
    border-radius: 12px !important;
}
textarea {
    background: #0F1115 !important;
    color: #FFFFFF !important;
    border-color: rgba(255,255,255,0.12) !important;
}
div[data-testid="stButton"] > button {
    width: 100%;
    background: linear-gradient(135deg, #F7931A, #EA580C) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.65rem 1.5rem !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    letter-spacing: 0.02em !important;
    margin-top: 0.5rem;
}
div[data-testid="stButton"] > button:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px);
}
</style>
""", unsafe_allow_html=True)

# ── UI ────────────────────────────────────────────────────────────────────────
st.markdown('<div class="hero-title">AI Resume Scorer</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-sub">Get an instant AI-powered score & actionable feedback for your resume</div>', unsafe_allow_html=True)

# Job role selector
job_role = st.selectbox("🎯 Target Job Role", list(ROLE_SKILLS.keys()), index=0)

# Input tabs
tab_file, tab_text = st.tabs(["📎 Upload File", "📝 Paste Text"])

raw_text = None

with tab_file:
    uploaded = st.file_uploader("Upload your resume (PDF, DOCX, TXT)", type=["pdf","docx","txt"], label_visibility="collapsed")
    if uploaded:
        try:
            if uploaded.name.lower().endswith('.pdf'):
                raw_text = extract_text_from_pdf(uploaded)
            elif uploaded.name.lower().endswith('.docx'):
                raw_text = extract_text_from_docx(uploaded)
            elif uploaded.name.lower().endswith('.txt'):
                raw_text = extract_text_from_txt(uploaded)
            st.success(f"✅ File loaded: **{uploaded.name}**")
        except Exception as e:
            st.error(f"Error reading file: {e}")

with tab_text:
    pasted = st.text_area("Paste your resume text here...", height=220, placeholder="Paste your full resume content here...")
    if pasted.strip():
        raw_text = pasted.strip()

# Analyze button
analyze_btn = st.button("⚡ Analyze Resume")

# ── Results ───────────────────────────────────────────────────────────────────
if analyze_btn:
    if not raw_text:
        st.warning("Please upload a file or paste your resume text first.")
    else:
        with st.spinner("Analyzing your resume..."):
            analysis   = analyze_resume(raw_text, job_role)
            ai_score   = score_text(analysis['found_skills'], analysis['exp'], job_role)
            tier_label, tier_color = get_tier(ai_score)
            tips       = build_improvements(ai_score, analysis['section_scores'], analysis['missing_skills'])

        st.markdown("<hr class='divider'>", unsafe_allow_html=True)

        # ── Score + Radar ──
        col_gauge, col_radar = st.columns([1, 1.3], gap="medium")

        with col_gauge:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f'<div class="card-title">AI Score — {job_role}</div>', unsafe_allow_html=True)
            st.plotly_chart(make_gauge(ai_score), use_container_width=True, config={'displayModeBar': False})
            st.markdown(f'<div class="tier-label" style="color:{tier_color}">{tier_label}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_radar:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">Profile Breakdown</div>', unsafe_allow_html=True)
            st.plotly_chart(make_radar(analysis['section_scores']), use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Section Bars ──
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">Section Scores</div>', unsafe_allow_html=True)
        bars_html = ""
        for name, val in analysis['section_scores'].items():
            bars_html += f"""
            <div class="bar-row">
              <div class="bar-label"><span>{name}</span><span>{val}%</span></div>
              <div class="bar-track"><div class="bar-fill" style="width:{val}%"></div></div>
            </div>"""
        st.markdown(bars_html, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # ── Skills + ATS ──
        col_skills, col_ats = st.columns(2, gap="medium")

        with col_skills:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">✅ Found Skills</div>', unsafe_allow_html=True)
            if analysis['found_skills']:
                chips = "".join(f'<span class="skill-chip chip-found">{s}</span>' for s in analysis['found_skills'])
                st.markdown(chips, unsafe_allow_html=True)
            else:
                st.markdown('<span style="color:#94A3B8;font-size:0.85rem">No matching skills detected.</span>', unsafe_allow_html=True)

            st.markdown('<br><div class="card-title" style="margin-top:0.8rem">❌ Missing Skills</div>', unsafe_allow_html=True)
            if analysis['missing_skills']:
                chips = "".join(f'<span class="skill-chip chip-missing">{s}</span>' for s in analysis['missing_skills'])
                st.markdown(chips, unsafe_allow_html=True)
            else:
                st.markdown('<span style="color:#94A3B8;font-size:0.85rem">Great — no major gaps found!</span>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with col_ats:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f'<div class="card-title">🤖 ATS Match — {analysis["ats_score"]}%</div>', unsafe_allow_html=True)
            ats_color = "#4ADE80" if analysis['ats_score'] >= 70 else "#F7931A" if analysis['ats_score'] >= 40 else "#F87171"
            st.markdown(f'<div style="font-size:2.2rem;font-weight:700;color:{ats_color};margin-bottom:0.6rem">{analysis["ats_score"]}%</div>', unsafe_allow_html=True)
            st.markdown('<div style="font-size:0.8rem;color:#94A3B8;margin-bottom:0.8rem">Keywords detected in your resume:</div>', unsafe_allow_html=True)
            if analysis['ats_hits']:
                chips = "".join(f'<span class="skill-chip chip-ats">{k}</span>' for k in analysis['ats_hits'])
                st.markdown(chips, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Improvements ──
        if tips:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown('<div class="card-title">💡 Improvement Suggestions</div>', unsafe_allow_html=True)
            items_html = "".join(
                f'<div class="improve-item"><span class="improve-dot">›</span><span>{t}</span></div>'
                for t in tips
            )
            st.markdown(items_html, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
