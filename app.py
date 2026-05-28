from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import pdfplumber
import re
import os
import io
import sys

# ── Fix for pickle deserialization ──────────────────────────────────────────
# The .pkl was trained with split_skills defined in __main__.
# We must inject it into __main__ BEFORE joblib.load() so pickle can find it.
def split_skills(text):
    return text.split(', ')

import __main__
__main__.split_skills = split_skills
# ────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

model = joblib.load('resume_scorer_pipeline.pkl', mmap_mode='r')

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

ATS_KEYWORDS = [
    'experience','education','skills','projects','certifications','achievements',
    'summary','objective','responsibilities','developed','managed','led','built',
    'designed','implemented','optimized','collaborated','achieved','improved',
    'bachelor','master','degree','university','college','gpa','intern',
    'full-stack','software engineer','developer','analyst','architect'
]

def analyze_resume(raw_text, job_role=DEFAULT_ROLE):
    text_lower = raw_text.lower()

    role_skills = ROLE_SKILLS.get(job_role, ROLE_SKILLS[DEFAULT_ROLE])

    # ── Detected skills ──
    found_skills = [s for s in role_skills if s in text_lower]
    missing_skills = [s for s in role_skills if s not in text_lower][:12]

    # ── Section scores (0-100) ──
    exp_score = 0
    exp = 0
    exp_match = re.search(r'(\d+)\+?\s*(years|yrs)', text_lower)
    if exp_match:
        exp = int(exp_match.group(1))
        exp_score = min(100, exp * 12)

    edu_score = 0
    for kw, pts in [('phd',100),('master',85),('mba',85),('b.tech',70),('bachelor',70),('diploma',50)]:
        if kw in text_lower:
            edu_score = pts; break

    proj_count = len(re.findall(r'project', text_lower))
    proj_score = min(100, proj_count * 15)

    cert_count = len(re.findall(r'certif', text_lower))
    cert_score = min(100, cert_count * 25)

    skills_score = min(100, len(found_skills) * 6)

    # ── ATS match ──
    ats_hits = [k for k in ATS_KEYWORDS if k in text_lower]
    ats_score = min(100, int((len(ats_hits) / len(ATS_KEYWORDS)) * 100))

    # ── Radar dimensions ──
    radar = {
        'Experience':    exp_score,
        'Education':     edu_score,
        'Projects':      proj_score,
        'Certifications':cert_score,
        'Skills':        skills_score,
        'ATS Match':     ats_score,
    }

    return {
        'exp': exp,
        'found_skills': found_skills[:15],
        'missing_skills': missing_skills,
        'section_scores': radar,
        'ats_score': ats_score,
        'ats_hits': ats_hits[:10],
    }

def score_text(found_skills, exp, job_role=DEFAULT_ROLE):
    # Convert the list of matched skills back into a comma-separated string for the model
    skills_string = ", ".join(found_skills)

    user_data = pd.DataFrame([{
        'Skills': skills_string,  # Now the model only sees RELEVANT skills
        'Experience (Years)': exp,
        'Education': 'B.Tech',
        'Certifications': 'None',
        'Job Role': job_role,
        'Projects Count': 3
    }])
    # Safely count skills (if the list is empty, it's 0)
    user_data['Total_Skills']      = len(found_skills)
    user_data['Projects_Per_Year'] = user_data['Projects Count'] / (user_data['Experience (Years)'] + 1)
    score = model.predict(user_data)[0]
    return round(max(0, min(100, float(score))), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  HTML PAGE
# ══════════════════════════════════════════════════════════════════════════════
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Resume Scorer</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#030304;--surface:#0F1115;--surface2:#161A22;
  --fg:#FFFFFF;--muted:#94A3B8;--border:rgba(255,255,255,.09);
  --orange:#F7931A;--burnt:#EA580C;--gold:#FFD600;
  --red:#F87171;--green:#4ADE80;
}
html{scroll-behavior:smooth}
body{
  font-family:'Inter',sans-serif;
  background:var(--bg);color:var(--fg);
  height:100vh;width:100vw;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:0 1rem;
  position:relative;overflow:hidden;
}
body.results-visible{
  height:auto;min-height:100vh;
  justify-content:flex-start;
  padding:2.5rem 1rem 4rem;
  overflow-x:hidden;overflow-y:auto;
}
/* ambient glow */
body::before{
  content:'';position:fixed;top:-10%;left:50%;transform:translateX(-50%);
  width:700px;height:500px;
  background:radial-gradient(ellipse,rgba(247,147,26,.07) 0%,transparent 68%);
  filter:blur(40px);pointer-events:none;z-index:0;
}
/* grid */
body::after{
  content:'';position:fixed;inset:0;
  background-size:50px 50px;
  background-image:
    linear-gradient(to right,rgba(30,41,59,.45) 1px,transparent 1px),
    linear-gradient(to bottom,rgba(30,41,59,.45) 1px,transparent 1px);
  mask-image:radial-gradient(ellipse at 50% 30%,black 20%,transparent 70%);
  -webkit-mask-image:radial-gradient(ellipse at 50% 30%,black 20%,transparent 70%);
  pointer-events:none;z-index:0;
}

.page{position:relative;z-index:1;width:100%;max-width:680px;display:flex;flex-direction:column;align-items:center;gap:1.8rem;}
.page.input-only{justify-content:center;}
body.results-visible .page{max-width:900px;}

/* ── hero header ── */
.hero-header{
  display:flex;flex-direction:column;align-items:center;gap:.9rem;
  width:100%;text-align:center;
}

/* ── logo ── */
.logo-wrap{display:flex;align-items:center;gap:12px;}
.logo-icon{
  width:46px;height:46px;border-radius:12px;flex-shrink:0;
  background:linear-gradient(135deg,#EA580C,#F7931A);
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 22px -4px rgba(247,147,26,.55);
}
.logo-icon svg{width:26px;height:26px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
.logo-text{display:flex;flex-direction:column;line-height:1;}
.logo-name{
  font-family:'Space Grotesk',sans-serif;font-size:1.6rem;font-weight:700;
  background:linear-gradient(90deg,#F7931A,#FFD600);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
  letter-spacing:-.01em;
}
.logo-sub{
  font-family:'JetBrains Mono',monospace;font-size:.76rem;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-top:2px;
}

/* ── badge ── */
.badge{
  display:inline-flex;align-items:center;gap:8px;
  background:rgba(247,147,26,.10);border:1px solid rgba(247,147,26,.30);
  border-radius:9999px;padding:5px 16px;
  font-family:'JetBrains Mono',monospace;font-size:.85rem;
  letter-spacing:.12em;text-transform:uppercase;color:var(--orange);
}
.badge .dot{width:6px;height:6px;border-radius:50%;background:var(--orange);position:relative;}
.badge .dot::after{
  content:'';position:absolute;inset:-3px;border-radius:50%;
  background:var(--orange);opacity:.4;
  animation:ping 1.5s cubic-bezier(0,0,.2,1) infinite;
}
@keyframes ping{75%,100%{transform:scale(2.2);opacity:0}}

/* ── headline ── */
.headline{
  font-family:'Space Grotesk',sans-serif;
  font-size:clamp(2.2rem,6vw,3.4rem);font-weight:700;
  line-height:1.15;text-align:center;letter-spacing:-.02em;
}
.grad{
  background:linear-gradient(90deg,#F7931A,#FFD600);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.subline{text-align:center;color:var(--muted);font-size:1.05rem;line-height:1.65;max-width:420px;}

/* ── card ── */
.card{
  width:100%;background:var(--surface);
  border:1px solid var(--border);border-radius:20px;
  padding:2rem 2rem 2rem;
  box-shadow:0 0 60px -20px rgba(247,147,26,.09);
  transition:box-shadow .3s,border-color .3s;
  position:relative;overflow:hidden;
}
.card:hover{border-color:rgba(247,147,26,.18);box-shadow:0 0 70px -15px rgba(247,147,26,.14);}
/* corner accents */
.card::before,.card::after{content:'';position:absolute;width:18px;height:18px;}
.card::before{top:0;left:0;border-top:2px solid var(--orange);border-left:2px solid var(--orange);border-radius:4px 0 0 0;}
.card::after{bottom:0;right:0;border-bottom:2px solid var(--orange);border-right:2px solid var(--orange);border-radius:0 0 4px 0;}

/* ── tab switcher ── */
.tabs{display:flex;gap:4px;background:rgba(0,0,0,.35);border:1px solid var(--border);border-radius:12px;padding:4px;margin-bottom:1.5rem;}
.tab{
  flex:1;height:38px;border:none;background:transparent;
  color:var(--muted);font-family:'JetBrains Mono',monospace;
  font-size:.88rem;letter-spacing:.06em;text-transform:uppercase;
  border-radius:9px;cursor:pointer;transition:all .2s;
  display:flex;align-items:center;justify-content:center;gap:7px;
}
.tab.active{background:linear-gradient(135deg,#EA580C,#F7931A);color:#fff;box-shadow:0 0 16px -4px rgba(234,88,12,.5);}
.tab:not(.active):hover{background:rgba(255,255,255,.05);color:var(--fg);}
.tab svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}

/* ── panels ── */
.panel{display:none;} .panel.active{display:block;}

/* ── drop zone ── */
.drop-zone{
  border:1px dashed rgba(255,255,255,.15);border-radius:12px;
  padding:1.8rem 1.5rem;text-align:center;cursor:pointer;
  transition:all .25s;background:rgba(0,0,0,.25);
  margin-bottom:1.2rem;position:relative;overflow:hidden;
}
.drop-zone:hover,.drop-zone.drag-over{
  border-color:rgba(247,147,26,.50);background:rgba(247,147,26,.05);
  box-shadow:0 0 20px -5px rgba(247,147,26,.18);
}
.drop-zone input[type="file"]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%;}
.drop-icon{
  width:44px;height:44px;margin:0 auto .7rem;
  background:rgba(234,88,12,.14);border:1px solid rgba(234,88,12,.38);
  border-radius:10px;display:flex;align-items:center;justify-content:center;
}
.drop-icon svg{width:22px;height:22px;stroke:var(--orange);fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
.drop-label{font-family:'JetBrains Mono',monospace;font-size:.90rem;color:var(--muted);letter-spacing:.04em;}
.drop-label span{color:var(--orange);}
.file-formats{margin-top:.4rem;font-size:.80rem;color:rgba(148,163,184,.5);font-family:'JetBrains Mono',monospace;letter-spacing:.05em;}
.file-name-display{
  margin-top:.6rem;font-family:'JetBrains Mono',monospace;font-size:.74rem;
  color:var(--gold);display:none;
}

/* text area panel */
.txt-label{font-family:'JetBrains Mono',monospace;font-size:.85rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:.5rem;}
textarea{
  width:100%;height:160px;background:rgba(0,0,0,.4);
  border:1px solid rgba(255,255,255,.10);border-radius:12px;
  color:var(--fg);font-family:'JetBrains Mono',monospace;font-size:.92rem;
  line-height:1.55;padding:1rem;resize:vertical;
  transition:border-color .2s,box-shadow .2s;margin-bottom:1.2rem;
}
textarea:focus{outline:none;border-color:rgba(247,147,26,.5);box-shadow:0 0 0 3px rgba(247,147,26,.08);}
textarea::placeholder{color:rgba(148,163,184,.35);}

/* ── job role selector ── */
.role-wrap{margin-bottom:1.2rem;}
.role-label{
  font-family:'JetBrains Mono',monospace;font-size:.85rem;
  letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  margin-bottom:.5rem;display:flex;align-items:center;gap:6px;
}
.role-label svg{width:13px;height:13px;stroke:var(--orange);fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
.role-select{
  width:100%;height:44px;background:rgba(0,0,0,.4);
  border:1px solid rgba(255,255,255,.10);border-radius:12px;
  color:var(--fg);font-family:'JetBrains Mono',monospace;font-size:.92rem;
  padding:0 1rem;cursor:pointer;appearance:none;-webkit-appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2' stroke-linecap='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 14px center;
  transition:border-color .2s,box-shadow .2s;
}
.role-select:focus{outline:none;border-color:rgba(247,147,26,.5);box-shadow:0 0 0 3px rgba(247,147,26,.08);}
.role-select option{background:#0F1115;color:#fff;}

/* ── primary btn ── */
.btn-primary{
  width:100%;height:52px;
  background:linear-gradient(90deg,#EA580C,#F7931A);
  border:none;border-radius:9999px;color:#fff;
  font-family:'Inter',sans-serif;font-size:1rem;font-weight:600;
  letter-spacing:.08em;text-transform:uppercase;cursor:pointer;
  box-shadow:0 0 22px -5px rgba(234,88,12,.52);
  transition:transform .25s,box-shadow .25s,opacity .25s;
  display:flex;align-items:center;justify-content:center;gap:10px;
}
.btn-primary:hover:not(:disabled){transform:scale(1.025);box-shadow:0 0 34px -4px rgba(247,147,26,.68);}
.btn-primary:disabled{opacity:.6;cursor:not-allowed;}
.spinner{width:18px;height:18px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;display:none;}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── results ── */
#results-section{width:100%;display:none;animation:fadeUp .45s ease forwards;}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}

/* score hero */
.score-hero{
  background:var(--surface);border:1px solid var(--border);border-radius:20px;
  padding:2rem;margin-bottom:1rem;text-align:center;
  box-shadow:0 0 50px -15px rgba(247,147,26,.12);
  position:relative;overflow:hidden;
}
.score-hero::before{
  content:'';position:absolute;top:-60px;left:50%;transform:translateX(-50%);
  width:240px;height:120px;
  background:radial-gradient(ellipse,rgba(247,147,26,.12),transparent 70%);
  filter:blur(20px);
}
.score-role-badge{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(247,147,26,.10);border:1px solid rgba(247,147,26,.25);
  border-radius:9999px;padding:3px 12px;margin-bottom:.6rem;
  font-family:'JetBrains Mono',monospace;font-size:.80rem;
  letter-spacing:.10em;text-transform:uppercase;color:var(--orange);
}
.score-tier-label{
  font-family:'JetBrains Mono',monospace;font-size:.84rem;
  letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-bottom:.3rem;
}
.score-big{
  font-family:'Space Grotesk',sans-serif;font-size:5rem;font-weight:700;line-height:1;
  background:linear-gradient(135deg,#F7931A,#FFD600);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.score-unit{font-size:1.6rem;color:var(--muted);vertical-align:super;}
.progress-track{
  width:100%;height:5px;background:rgba(255,255,255,.07);
  border-radius:9999px;overflow:hidden;margin:1rem 0 .8rem;
}
.progress-fill{
  height:100%;border-radius:9999px;
  background:linear-gradient(90deg,#EA580C,#F7931A,#FFD600);
  box-shadow:0 0 10px rgba(247,147,26,.55);
  transition:width .9s cubic-bezier(.22,1,.36,1);width:0%;
}
.motivation-box{
  background:rgba(247,147,26,.07);border:1px solid rgba(247,147,26,.18);
  border-radius:12px;padding:1rem 1.2rem;
  font-size:1rem;color:#fde68a;line-height:1.6;
  font-family:'Inter',sans-serif;
  display:flex;gap:10px;align-items:flex-start;text-align:left;
}
.motivation-box .icon-wrap{flex-shrink:0;margin-top:1px;}
.motivation-box svg{width:18px;height:18px;stroke:var(--orange);fill:none;stroke-width:2;stroke-linecap:round;}

/* grid 2-col */
.result-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem;}
@media(max-width:560px){.result-grid{grid-template-columns:1fr;}}

.result-card{
  background:var(--surface);border:1px solid var(--border);border-radius:16px;
  padding:1.4rem;transition:border-color .25s,box-shadow .25s;
}
.result-card:hover{border-color:rgba(247,147,26,.22);box-shadow:0 0 25px -8px rgba(247,147,26,.15);}
.rc-title{
  font-family:'JetBrains Mono',monospace;font-size:.82rem;
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:1rem;
  display:flex;align-items:center;gap:6px;
}
.rc-title svg{width:14px;height:14px;stroke:var(--orange);fill:none;stroke-width:2;stroke-linecap:round;}

/* radar chart */
#radarCanvas{display:block;margin:0 auto;}

/* section bars */
.sec-row{margin-bottom:.75rem;}
.sec-row:last-child{margin-bottom:0;}
.sec-meta{display:flex;justify-content:space-between;margin-bottom:.3rem;}
.sec-name{font-family:'JetBrains Mono',monospace;font-size:.86rem;color:var(--muted);}
.sec-val{font-family:'JetBrains Mono',monospace;font-size:.86rem;color:var(--fg);font-weight:500;}
.sec-track{height:4px;background:rgba(255,255,255,.07);border-radius:9999px;overflow:hidden;}
.sec-fill{height:100%;border-radius:9999px;background:linear-gradient(90deg,#EA580C,#F7931A);transition:width .8s cubic-bezier(.22,1,.36,1);width:0%;}

/* skills */
.skills-wrap{display:flex;flex-wrap:wrap;gap:6px;}
.skill-chip{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 10px;border-radius:9999px;font-family:'JetBrains Mono',monospace;font-size:.82rem;
  border:1px solid;white-space:nowrap;
}
.skill-chip.found{background:rgba(74,222,128,.08);border-color:rgba(74,222,128,.25);color:#4ade80;}
.skill-chip.missing{background:rgba(248,113,113,.08);border-color:rgba(248,113,113,.22);color:#f87171;}
.skill-chip svg{width:10px;height:10px;stroke:currentColor;fill:none;stroke-width:2.5;stroke-linecap:round;}

/* ATS */
.ats-ring-wrap{display:flex;flex-direction:column;align-items:center;gap:.5rem;}
.ats-big{
  font-family:'Space Grotesk',sans-serif;font-size:2.4rem;font-weight:700;
  background:linear-gradient(90deg,#F7931A,#FFD600);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.ats-sub{font-family:'JetBrains Mono',monospace;font-size:.82rem;color:var(--muted);letter-spacing:.1em;text-transform:uppercase;}
.ats-keywords{display:flex;flex-wrap:wrap;gap:5px;margin-top:.8rem;}
.ats-kw{
  padding:3px 9px;border-radius:9999px;
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.10);
  font-family:'JetBrains Mono',monospace;font-size:.78rem;color:var(--muted);
}

/* improvements */
.improve-list{list-style:none;}
.improve-item{
  display:flex;align-items:flex-start;gap:10px;
  padding:.6rem 0;border-bottom:1px solid rgba(255,255,255,.05);
  font-size:.96rem;color:var(--muted);line-height:1.5;
}
.improve-item:last-child{border-bottom:none;}
.improve-item .bullet{
  flex-shrink:0;width:20px;height:20px;border-radius:50%;margin-top:1px;
  background:rgba(234,88,12,.15);border:1px solid rgba(234,88,12,.35);
  display:flex;align-items:center;justify-content:center;
}
.improve-item .bullet svg{width:10px;height:10px;stroke:var(--orange);fill:none;stroke-width:2.5;stroke-linecap:round;}

/* error */
.result-error{
  font-family:'JetBrains Mono',monospace;font-size:.92rem;color:#f87171;
  display:flex;align-items:center;gap:8px;padding:1rem;
  background:rgba(248,113,113,.07);border:1px solid rgba(248,113,113,.18);
  border-radius:12px;
}

.footer-txt{font-family:'JetBrains Mono',monospace;font-size:.78rem;letter-spacing:.08em;color:rgba(148,163,184,.35);text-align:center;}

/* scroll-full on mobile */
@media(max-width:400px){
  .card{padding:1.5rem 1.2rem;}
  .score-big{font-size:3.8rem;}
}
</style>
</head>
<body>

<div class="page input-only">

  <!-- ── hero header ── -->
  <div class="hero-header">

    <!-- logo -->
    <div class="logo-wrap">
      <div class="logo-icon">
        <svg viewBox="0 0 24 24">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="9" y1="13" x2="15" y2="13"/>
          <line x1="9" y1="17" x2="13" y2="17"/>
          <polyline points="9 9 10 9"/>
        </svg>
      </div>
      <div class="logo-text">
        <span class="logo-name">ResumeAI</span>
        <span class="logo-sub">Deep Score Engine · v3.0</span>
      </div>
    </div>

    <!-- badge -->
    <div class="badge"><span class="dot"></span>AI Resume Engine &nbsp;·&nbsp; v3.0</div>

    <!-- headline -->
    <div>
      <h1 class="headline">Resume Scanner<br>with <span class="grad">Deep Insights</span></h1>
      <p class="subline" style="margin-top:.7rem;">Upload PDF, DOCX, or TXT — or paste raw text. Choose your target role and get a tailored hiring score instantly.</p>
    </div>

  </div>

  <!-- upload card -->
  <div class="card">

    <!-- tab switcher -->
    <div class="tabs">
      <button class="tab active" id="tab-file" onclick="switchTab('file')">
        <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        Upload File
      </button>
      <button class="tab" id="tab-text" onclick="switchTab('text')">
        <svg viewBox="0 0 24 24"><line x1="21" y1="6" x2="3" y2="6"/><line x1="15" y1="12" x2="3" y2="12"/><line x1="17" y1="18" x2="3" y2="18"/></svg>
        Paste Text
      </button>
    </div>

    <!-- file panel -->
    <div class="panel active" id="panel-file">
      <div class="drop-zone" id="dropZone">
        <input type="file" id="fileInput" accept=".pdf,.docx,.txt">
        <div class="drop-icon">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        </div>
        <p class="drop-label">Drop your resume here or <span>browse files</span></p>
        <p class="file-formats">PDF &nbsp;·&nbsp; DOCX &nbsp;·&nbsp; TXT supported</p>
        <p class="file-name-display" id="fileName"></p>
      </div>
    </div>

    <!-- text panel -->
    <div class="panel" id="panel-text">
      <p class="txt-label">Paste Resume Text</p>
      <textarea id="resumeText" placeholder="Paste your resume content here...&#10;&#10;Include skills, experience, education, projects, and certifications for the best analysis."></textarea>
    </div>

    <!-- ── job role selector (shared, below both panels) ── -->
    <div class="role-wrap">
      <p class="role-label">
        <svg viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><line x1="12" y1="12" x2="12" y2="16"/><line x1="10" y1="14" x2="14" y2="14"/></svg>
        Target Job Role
      </p>
      <select class="role-select" id="jobRole">
        <option value="Software Engineer">Software Engineer</option>
        <option value="Data Scientist">Data Scientist</option>
        <option value="Frontend Developer">Frontend Developer</option>
        <option value="Backend Developer">Backend Developer</option>
        <option value="Full Stack Developer">Full Stack Developer</option>
        <option value="Machine Learning Engineer">Machine Learning Engineer</option>
        <option value="Data Analyst">Data Analyst</option>
        <option value="DevOps Engineer">DevOps Engineer</option>
        <option value="Cloud Architect">Cloud Architect</option>
        <option value="UI/UX Designer">UI/UX Designer</option>
        <option value="Product Manager">Product Manager</option>
        <option value="Cybersecurity Analyst">Cybersecurity Analyst</option>
      </select>
    </div>

    <button class="btn-primary" id="submitBtn" onclick="handleSubmit()">
      <div class="spinner" id="spinner"></div>
      <span id="btnText">Scan Resume</span>
    </button>

  </div>

  <!-- ── results ── -->
  <div id="results-section">

    <!-- score hero -->
    <div class="score-hero">
      <div class="score-role-badge" id="scoreRoleBadge">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>
        <span id="scoreRoleLabel">Software Engineer</span>
      </div>
      <p class="score-tier-label" id="tierLabel">Hiring Probability</p>
      <div>
        <span class="score-big" id="scoreBig">0</span><span class="score-unit">%</span>
      </div>
      <div class="progress-track"><div class="progress-fill" id="progressFill"></div></div>
      <div class="motivation-box" id="motivationBox">
        <div class="icon-wrap">
          <svg viewBox="0 0 24 24"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/></svg>
        </div>
        <span id="motivationText"></span>
      </div>
    </div>

    <!-- 2-col grid -->
    <div class="result-grid">

      <!-- radar -->
      <div class="result-card" style="grid-column:1/-1;">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          Resume Strength Radar
        </p>
        <canvas id="radarCanvas" width="320" height="230"></canvas>
      </div>

      <!-- section scores -->
      <div class="result-card">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          Section Scores
        </p>
        <div id="sectionBars"></div>
      </div>

      <!-- ATS -->
      <div class="result-card">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          ATS Match Score
        </p>
        <div class="ats-ring-wrap">
          <div class="ats-big" id="atsScore">0%</div>
          <div class="ats-sub">keyword coverage</div>
          <canvas id="atsArc" width="120" height="70"></canvas>
          <div class="ats-keywords" id="atsKeywords"></div>
        </div>
      </div>

      <!-- found skills -->
      <div class="result-card">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
          Detected Skills
        </p>
        <div class="skills-wrap" id="foundSkills"></div>
      </div>

      <!-- missing skills -->
      <div class="result-card">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Skills Gap
        </p>
        <div class="skills-wrap" id="missingSkills"></div>
      </div>

      <!-- improvements -->
      <div class="result-card" style="grid-column:1/-1;">
        <p class="rc-title">
          <svg viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          Improvement Roadmap
        </p>
        <ul class="improve-list" id="improveList"></ul>
      </div>

    </div>
  </div>

  <p class="footer-txt" style="margin-top:1rem;">POWERED BY MACHINE LEARNING &nbsp;·&nbsp; AI RESUME ENGINE V3</p>

</div>

<script>
// ── tab switch ──────────────────────────────────────────────────────────────
function switchTab(t){
  document.getElementById('tab-file').classList.toggle('active',t==='file');
  document.getElementById('tab-text').classList.toggle('active',t==='text');
  document.getElementById('panel-file').classList.toggle('active',t==='file');
  document.getElementById('panel-text').classList.toggle('active',t==='text');
}

// ── drag & drop ─────────────────────────────────────────────────────────────
const fileInput = document.getElementById('fileInput');
const fileName  = document.getElementById('fileName');
const dropZone  = document.getElementById('dropZone');
fileInput.addEventListener('change', ()=>{
  if(fileInput.files[0]){ fileName.style.display='block'; fileName.textContent=fileInput.files[0].name; }
});
dropZone.addEventListener('dragover',e=>{e.preventDefault();dropZone.classList.add('drag-over');});
dropZone.addEventListener('dragleave',()=>dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop',e=>{
  e.preventDefault();dropZone.classList.remove('drag-over');
  if(e.dataTransfer.files[0]){
    fileInput.files=e.dataTransfer.files;
    fileName.style.display='block';
    fileName.textContent=e.dataTransfer.files[0].name;
  }
});

// ── loading state ────────────────────────────────────────────────────────────
function setLoading(on){
  document.getElementById('submitBtn').disabled=on;
  document.getElementById('spinner').style.display=on?'block':'none';
  document.getElementById('btnText').textContent=on?'Analyzing...':'Scan Resume';
}

// ── motivation messages ──────────────────────────────────────────────────────
function getMotivation(score){
  if(score>=85) return{icon:'star',msg:"Outstanding! You're in the top tier. Recruiters will take notice — your profile demonstrates the depth and breadth that high-growth companies look for. Fine-tune your narrative and you're ready to apply with full confidence."};
  if(score>=70) return{icon:'up',msg:"Strong profile! You have the core competencies. To reach the top 10%, focus on quantifying your achievements with metrics, closing the skills gaps below, and tightening your ATS keyword coverage."};
  if(score>=50) return{icon:'mid',msg:"Solid foundation with clear room to grow. Target the skills gaps flagged below — adding 3-4 in-demand technologies to your projects section could push your score past 70. Every skill you add multiplies your visibility."};
  if(score>=30) return{icon:'low',msg:"This is your starting point, not your ceiling. Focus on the improvement roadmap below. Build 2-3 portfolio projects, earn one cloud certification, and restructure your resume with ATS-friendly keywords. 6 months of deliberate effort transforms this score."};
  return{icon:'alert',msg:"The journey starts here. Don't be discouraged — every expert was once a beginner. Follow the roadmap section-by-section: start with core skills, build small projects, and keep iterating. Consistency beats talent long-term."};
}

// ── draw radar ───────────────────────────────────────────────────────────────
function drawRadar(scores){
  const canvas=document.getElementById('radarCanvas');
  const ctx=canvas.getContext('2d');
  const W=canvas.width,H=canvas.height;
  const cx=W/2,cy=H/2+10;
  const R=Math.min(W,H)*0.36;
  const labels=Object.keys(scores);
  const vals=Object.values(scores);
  const n=labels.length;
  ctx.clearRect(0,0,W,H);

  // grid rings
  [.25,.5,.75,1].forEach(f=>{
    ctx.beginPath();
    for(let i=0;i<n;i++){
      const a=(i/n)*Math.PI*2-Math.PI/2;
      const x=cx+Math.cos(a)*R*f, y=cy+Math.sin(a)*R*f;
      i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.strokeStyle=`rgba(255,255,255,${f===1?.10:.05})`;
    ctx.lineWidth=1;ctx.stroke();
  });

  // spokes
  for(let i=0;i<n;i++){
    const a=(i/n)*Math.PI*2-Math.PI/2;
    ctx.beginPath();ctx.moveTo(cx,cy);
    ctx.lineTo(cx+Math.cos(a)*R,cy+Math.sin(a)*R);
    ctx.strokeStyle='rgba(255,255,255,.07)';ctx.lineWidth=1;ctx.stroke();
  }

  // data fill
  ctx.beginPath();
  for(let i=0;i<n;i++){
    const a=(i/n)*Math.PI*2-Math.PI/2;
    const r=R*(vals[i]/100);
    const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r;
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  }
  ctx.closePath();
  ctx.fillStyle='rgba(247,147,26,.18)';ctx.fill();
  ctx.strokeStyle='rgba(247,147,26,.75)';ctx.lineWidth=2;ctx.stroke();

  // dots
  for(let i=0;i<n;i++){
    const a=(i/n)*Math.PI*2-Math.PI/2;
    const r=R*(vals[i]/100);
    const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r;
    ctx.beginPath();ctx.arc(x,y,3.5,0,Math.PI*2);
    ctx.fillStyle='#F7931A';ctx.fill();
  }

  // labels
  ctx.font='500 10.5px JetBrains Mono,monospace';
  ctx.textAlign='center';ctx.textBaseline='middle';
  for(let i=0;i<n;i++){
    const a=(i/n)*Math.PI*2-Math.PI/2;
    const lx=cx+Math.cos(a)*(R+26),ly=cy+Math.sin(a)*(R+18);
    ctx.fillStyle='rgba(148,163,184,.85)';
    ctx.fillText(labels[i],lx,ly);
  }
}

// ── draw ATS arc ──────────────────────────────────────────────────────────────
function drawAtsArc(pct){
  const canvas=document.getElementById('atsArc');
  const ctx=canvas.getContext('2d');
  const W=canvas.width,H=canvas.height;
  ctx.clearRect(0,0,W,H);
  const cx=W/2,cy=H-8,r=50;
  const startA=Math.PI,endA=Math.PI*(1+pct/100);
  ctx.beginPath();ctx.arc(cx,cy,r,Math.PI,0);
  ctx.strokeStyle='rgba(255,255,255,.06)';ctx.lineWidth=8;
  ctx.lineCap='round';ctx.stroke();
  if(pct>0){
    ctx.beginPath();ctx.arc(cx,cy,r,startA,endA);
    const grad=ctx.createLinearGradient(cx-r,cy,cx+r,cy);
    grad.addColorStop(0,'#EA580C');grad.addColorStop(1,'#FFD600');
    ctx.strokeStyle=grad;ctx.lineWidth=8;ctx.lineCap='round';ctx.stroke();
  }
}

// ── render improvements ───────────────────────────────────────────────────────
function buildImprovements(score, sections, missing){
  const tips=[];
  const lo=(k)=>sections[k]<50;
  if(lo('Experience'))  tips.push('Add specific role durations with months/years — e.g. "Jan 2022 – Present". Quantify impact: "reduced load time by 40%".');
  if(lo('Education'))   tips.push('List your degree, institution, and GPA (if above 3.0). Include relevant coursework or academic projects.');
  if(lo('Projects'))    tips.push('Add 2–3 real projects with GitHub links. Describe the tech stack, problem solved, and measurable outcome.');
  if(lo('Certifications')) tips.push('Earn one industry cert — AWS Cloud Practitioner, Google Associate Cloud Engineer, or a Coursera specialization — to signal commitment.');
  if(lo('Skills'))      tips.push(`Expand your skills section. Missing high-value skills for this role: ${missing.slice(0,4).join(', ')}. Even beginner proficiency counts.`);
  if(lo('ATS Match'))   tips.push('Rewrite bullet points using action verbs (developed, implemented, optimized). Mirror keywords from job descriptions.');
  if(score<50)          tips.push('Structure matters: use standard headings (Summary, Experience, Skills, Education, Projects, Certifications) for ATS scanners.');
  if(score>=70)         tips.push('You\'re close to elite tier. Add a 3-line professional summary at the top and tailor keywords for each application.');
  if(tips.length===0)   tips.push('Excellent profile! Keep your resume updated quarterly and tailor it per role. Consider adding a portfolio link or GitHub.');
  return tips;
}

// ── main render ───────────────────────────────────────────────────────────────
function renderResults(data){
  const sec=document.getElementById('results-section');
  sec.style.display='block';
  document.body.classList.add('results-visible');
  document.querySelector('.page').classList.remove('input-only');

  // show selected role in results header
  document.getElementById('scoreRoleLabel').textContent=data.job_role||'Software Engineer';

  // score
  const score=data.ai_score;
  document.getElementById('scoreBig').textContent=score;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    document.getElementById('progressFill').style.width=score+'%';
  }));

  // tier label
  const tier = score>=85?'🔥 Elite Candidate':score>=70?'⭐ Strong Profile':score>=50?'📈 Developing Profile':'🛠 Needs Work';
  document.getElementById('tierLabel').textContent=tier;

  // motivation
  const m=getMotivation(score);
  document.getElementById('motivationText').textContent=m.msg;

  // radar
  const ss=data.section_scores;
  drawRadar(ss);

  // section bars
  const barsEl=document.getElementById('sectionBars');
  barsEl.innerHTML='';
  Object.entries(ss).forEach(([k,v])=>{
    barsEl.innerHTML+=`
      <div class="sec-row">
        <div class="sec-meta"><span class="sec-name">${k}</span><span class="sec-val">${v}%</span></div>
        <div class="sec-track"><div class="sec-fill" data-val="${v}"></div></div>
      </div>`;
  });
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    document.querySelectorAll('.sec-fill').forEach(el=>{ el.style.width=el.dataset.val+'%'; });
  }));

  // ATS
  document.getElementById('atsScore').textContent=data.ats_score+'%';
  drawAtsArc(data.ats_score);
  document.getElementById('atsKeywords').innerHTML=data.ats_hits.map(k=>`<span class="ats-kw">${k}</span>`).join('');

  // found skills
  document.getElementById('foundSkills').innerHTML=data.found_skills.map(s=>`
    <span class="skill-chip found">
      <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>${s}
    </span>`).join('');

  // missing skills
  document.getElementById('missingSkills').innerHTML=data.missing_skills.slice(0,10).map(s=>`
    <span class="skill-chip missing">
      <svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>${s}
    </span>`).join('');

  // improvements
  const tips=buildImprovements(score, ss, data.missing_skills);
  document.getElementById('improveList').innerHTML=tips.map(t=>`
    <li class="improve-item">
      <div class="bullet"><svg viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg></div>
      <span>${t}</span>
    </li>`).join('');

  sec.scrollIntoView({behavior:'smooth',block:'start'});
}

function showError(msg){
  const sec=document.getElementById('results-section');
  sec.style.display='block';
  document.body.classList.add('results-visible');
  document.querySelector('.page').classList.remove('input-only');
  sec.innerHTML=`<div class="result-error">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
    ${msg}
  </div>`;
}

// ── submit ────────────────────────────────────────────────────────────────────
async function handleSubmit(){
  const isFile = document.getElementById('panel-file').classList.contains('active');
  const jobRole = document.getElementById('jobRole').value;
  const sec=document.getElementById('results-section');
  sec.style.display='none';
  document.body.classList.remove('results-visible');
  document.querySelector('.page').classList.add('input-only');
  setLoading(true);

  try{
    let response;
    if(isFile){
      if(!fileInput.files[0]){setLoading(false);alert('Please select a file first.');return;}
      const fd=new FormData();
      fd.append('file',fileInput.files[0]);
      fd.append('job_role',jobRole);
      response=await fetch('/api/score',{method:'POST',body:fd});
    } else {
      const txt=document.getElementById('resumeText').value.trim();
      if(!txt){setLoading(false);alert('Please paste your resume text first.');return;}
      response=await fetch('/api/score-text',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({text:txt, job_role:jobRole})
      });
    }
    const data=await response.json();
    if(data.success) renderResults(data);
    else showError('Error: '+(data.error||'Unknown error'));
  } catch(err){
    showError('Failed to connect to AI engine.');
  } finally {
    setLoading(false);
  }
}
</script>
</body>
</html>
"""

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET'])
def home():
    return HTML_PAGE


@app.route('/api/score', methods=['POST'])
def score_resume():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
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

        analysis = analyze_resume(raw_text, job_role)
        final_score = score_text(analysis['found_skills'], analysis['exp'], job_role)

        import gc
        del raw_text
        gc.collect()

        return jsonify({
            "success": True,
            "job_role": job_role,
            "ai_score": final_score,
            "extracted_experience": analysis['exp'],
            "found_skills": analysis['found_skills'],
            "missing_skills": analysis['missing_skills'],
            "section_scores": analysis['section_scores'],
            "ats_score": analysis['ats_score'],
            "ats_hits": analysis['ats_hits'],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/score-text', methods=['POST'])
def score_resume_text():
    body = request.get_json(silent=True)
    if not body or not body.get('text', '').strip():
        return jsonify({"error": "No text provided"}), 400

    raw_text = body['text']
    job_role = body.get('job_role', 'Software Engineer')

    try:
        analysis = analyze_resume(raw_text, job_role)
        final_score = score_text(analysis['found_skills'], analysis['exp'], job_role)

        return jsonify({
            "success": True,
            "job_role": job_role,
            "ai_score": final_score,
            "extracted_experience": analysis['exp'],
            "found_skills": analysis['found_skills'],
            "missing_skills": analysis['missing_skills'],
            "section_scores": analysis['section_scores'],
            "ats_score": analysis['ats_score'],
            "ats_hits": analysis['ats_hits'],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
