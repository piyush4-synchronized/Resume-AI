// ═══════════════════════════════════════════════════════════════════════
// THEME SYSTEM — Light / Dark / System, persisted via localStorage.
// No page reload required: swaps [data-theme] on <html> and every CSS
// rule using var(--token) repaints instantly. Runs immediately (top of
// file, before Chart.js setup) so there's no flash of the wrong theme.
// ═══════════════════════════════════════════════════════════════════════
const THEME_KEY = "resumeai_theme"; // stored value: 'light' | 'dark' | 'system'

function getStoredThemePref() {
  return localStorage.getItem(THEME_KEY) || "system";
}

function resolveTheme(pref) {
  if (pref === "system") {
    return window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return pref;
}

function applyTheme(pref, { withTransition = false } = {}) {
  const resolved = resolveTheme(pref);
  const root = document.documentElement;

  if (
    withTransition &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), 400);
  }

  if (resolved === "dark") {
    root.setAttribute("data-theme", "dark");
  } else {
    root.removeAttribute("data-theme");
  }
  setTimeout(syncChartColors, 10);
  // sync the Settings page UI if it's in the DOM
  ["light", "dark", "system"].forEach((key) => {
    const btn = document.getElementById(
      "themeOpt" + key.charAt(0).toUpperCase() + key.slice(1),
    );
    if (btn) {
      const active = key === pref;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-checked", active ? "true" : "false");
    }
  });
}

function syncChartColors() {
  if (!window.Chart) return;

  // Extract the real hex codes from the active CSS theme
  const style = getComputedStyle(document.documentElement);
  const fg = style.getPropertyValue("--muted-fg").trim() || "#64748B";
  const border = style.getPropertyValue("--border").trim() || "#E2E8F0";

  // Feed the pure hex codes to Chart.js globally
  Chart.defaults.color = fg;
  Chart.defaults.borderColor = border;

  // Force all active charts on the page to repaint instantly
  const allCharts = [
    ringInst,
    radarInst,
    doughInst,
    benchInst,
    batchBarInst,
    ringInstVis,
    radarInstVis,
    doughInstVis,
    benchInstVis,
    ...Object.values(
      typeof analyticsCharts !== "undefined" ? analyticsCharts : {},
    ),
  ];
  allCharts.forEach((c) => {
    if (c && typeof c.update === "function") c.update();
  });
}

function setTheme(pref) {
  localStorage.setItem(THEME_KEY, pref);
  applyTheme(pref, { withTransition: true });
}

// Apply saved/system theme immediately (before DOMContentLoaded) to avoid flash.
applyTheme(getStoredThemePref());

// Keep in sync if the user changes their OS theme while pref === 'system'.
if (window.matchMedia) {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (getStoredThemePref() === "system") applyTheme("system");
    });
}

if (!window.Chart) {
  window.Chart = class {
    static defaults = { color: "", borderColor: "", font: {} };
    constructor() {}
    destroy() {}
  };
}
// ─── Chart defaults ───────────────────────────────────────────────────────
Chart.defaults.color = "var(--muted-fg)";
Chart.defaults.borderColor = "var(--border)";

// ── Dashboard bridge ─────────────────────────────────────────────────────
// Called after the original renderResults populates legacy elements; mirrors into dashboard UI
function mirrorToDashboard(d) {
  // KPI strip
  document.getElementById("kpiScore").textContent = d.ai_score ?? "--";
  document.getElementById("kpiAts").textContent = (d.ats_score ?? "--") + "%";
  document.getElementById("kpiSkills").textContent = (
    d.found_skills || []
  ).length;
  document.getElementById("kpiExp").textContent =
    (d.extracted_experience ?? "--") + "y";

  // Score panel
  document.getElementById("scoreNumVis").textContent = d.ai_score ?? "--";
  document.getElementById("scoreTitleVis").textContent =
    d.job_role ?? "Candidate Profile";
  // tier
  const tier = document.getElementById("scoreTier");
  const tierVis = document.getElementById("scoreTierVis");
  if (tier) tierVis.className = tier.className;
  if (tier) tierVis.textContent = tier.textContent;
  // meta pills
  const pills = document.getElementById("metaPills");
  const pillsVis = document.getElementById("metaPillsVis");
  if (pills) pillsVis.innerHTML = pills.innerHTML;
  // section bars
  const bars = document.getElementById("sectionBars");
  const barsVis = document.getElementById("sectionBarsVis");
  if (bars) barsVis.innerHTML = bars.innerHTML;

  // Skills
  const found = document.getElementById("foundSkills");
  const foundVis = document.getElementById("foundSkillsVis");
  if (found) foundVis.innerHTML = found.innerHTML;
  const missing = document.getElementById("missingSkills");
  const missingVis = document.getElementById("missingSkillsVis");
  if (missing) missingVis.innerHTML = missing.innerHTML;
  const ats = document.getElementById("atsHits");
  const atsVis = document.getElementById("atsHitsVis");
  if (ats) atsVis.innerHTML = ats.innerHTML;

  // Draw ring in visible canvas
  if (ringInstVis) ringInstVis.destroy();
  const score = d.ai_score || 0;
  const ringColor =
    score >= 70 ? "#34D399" : score >= 50 ? "#FBBF24" : "#EF4444";
  ringInstVis = new Chart(document.getElementById("ringChartVis"), {
    type: "doughnut",
    data: {
      datasets: [
        {
          data: [score, 100 - score],
          backgroundColor: [ringColor, "#F1F5F9"],
          borderWidth: 0,
          cutout: "76%",
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      animation: { duration: 1200 },
      events: [],
    },
  });

  // Draw visual charts
  setTimeout(() => {
    const src = {
      radar: document.getElementById("radarChart"),
      donut: document.getElementById("doughnutChart"),
      bench: document.getElementById("barBenchChart"),
    };
    const dst = {
      radar: document.getElementById("radarChartVis"),
      donut: document.getElementById("doughnutChartVis"),
      bench: document.getElementById("barBenchChartVis"),
    };
    // radar
    if (radarInst) {
      if (radarInstVis) radarInstVis.destroy();
      radarInstVis = new Chart(dst.radar, {
        type: "radar",
        data: JSON.parse(JSON.stringify(radarInst.data)),
        options: JSON.parse(JSON.stringify(radarInst.options)),
      });
    }
    // doughnut
    if (doughInst) {
      if (doughInstVis) doughInstVis.destroy();
      doughInstVis = new Chart(dst.donut, {
        type: "doughnut",
        data: JSON.parse(JSON.stringify(doughInst.data)),
        options: JSON.parse(JSON.stringify(doughInst.options)),
      });
    }
    // bench
    if (benchInst) {
      if (benchInstVis) benchInstVis.destroy();
      benchInstVis = new Chart(dst.bench, {
        type: "bar",
        data: JSON.parse(JSON.stringify(benchInst.data)),
        options: JSON.parse(JSON.stringify(benchInst.options)),
      });
    }
  }, 200);
}

let ringInstVis = null,
  radarInstVis = null,
  doughInstVis = null,
  benchInstVis = null;

// ── Dashboard feature runner ───────────────────────────────────────────────
let activeFeatBtn = null;
async function runFeatureDash(type, btn) {
  if (!currentData) {
    toast("Run a scan first", "error");
    return;
  }
  const d = currentData;
  // update nav state
  document
    .querySelectorAll(".feat-nav-btn")
    .forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  activeFeatBtn = btn;

  const panel = document.getElementById("dashOutputPanel");
  panel.innerHTML = `
          <div class="output-header-strip">
            <div class="output-breadcrumb">AI Modules <span>→</span> ${btn.querySelector(".feat-nav-name").textContent}</div>
            <div class="output-generating"><div class="status-dot"></div>Generating…</div>
          </div>
          <div style="flex:1;display:flex;align-items:center;justify-content:center">
            <div style="text-align:center"><div class="geo-spinner" style="margin:0 auto 1rem"></div><div class="loader-text">AI is working…</div></div>
          </div>`;

  // call original runFeature which writes to featureContent
  const compInput = document.getElementById("targetCompany");
  const companyName =
    compInput && compInput.value.trim() !== ""
      ? compInput.value.trim()
      : "the company";

  const payload = {
    job_role: d.job_role,
    found_skills: d.found_skills,
    missing_skills: d.missing_skills,
    exp: d.extracted_experience,
    education: d.extracted_education,
    score: d.ai_score,
    company_name: companyName,
    raw_text: d.raw_text,
  };
  const ep = {
    interview: "/api/interview-questions",
    cover: "/api/cover-letter",
    rewrite: "/api/rewrite",
    linkedin: "/api/linkedin-summary",
    salary: "/api/salary",
    roadmap: "/api/roadmap",
    redflag: "/api/red-flags",
    scorecard: "/api/scorecard",
    outreach: "/api/outreach",
  };
  try {
    const res = await fetch(ep[type], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);
    const tmp = document.createElement("div");
    renderFeature(type, data, tmp);
    panel.innerHTML = `
            <div class="output-header-strip">
              <div class="output-breadcrumb">AI Modules <span>→</span> ${btn.querySelector(".feat-nav-name").textContent}</div>
            </div>
            <div id="dashOutputContent"></div>`;
    document.getElementById("dashOutputContent").appendChild(tmp);
  } catch (e) {
    panel.innerHTML = `<div class="output-header-strip"><div class="output-breadcrumb">Error</div></div><p style="color:var(--danger);font-size:.85rem;font-weight:500;padding:.5rem 0">Error: ${e.message}</p>`;
  }
}

// ─── State ───────────────────────────────────────────────────────────────
let currentData = null,
  inputMode = "file";
let ringInst = null,
  radarInst = null,
  doughInst = null,
  benchInst = null,
  batchBarInst = null;
let batchFiles = [];
let batchCache = null;

// ─── Motivational lines ──────────────────────────────────────────────────
const MOTIVES = {
  high: [
    {
      icon: "🚀",
      label: "ELITE SIGNAL DETECTED",
      text: "Outstanding. Your profile cuts through the noise like a laser through fiber optic. You are in the top tier — keep pushing the boundaries, the industry needs minds like yours.",
    },
    {
      icon: "⚡",
      label: "TOP-TIER CANDIDATE",
      text: "You're not just qualified — you're dangerous in the best way. This score puts you ahead of the pack. The only direction from here is further up.",
    },
    {
      icon: "🏆",
      label: "MISSION ACCOMPLISHED",
      text: "Your resume is a weapon. Sharpen your interview skills to match and no door stays closed. You've done the work — now own the room.",
    },
  ],
  medium: [
    {
      icon: "📡",
      label: "SIGNAL LOCKED — AMPLIFY",
      text: "You're transmitting on the right frequency. A few targeted upgrades — close those skill gaps, add certifications — and your signal becomes impossible to ignore.",
    },
    {
      icon: "⬆",
      label: "TRAJECTORY: ASCENDING",
      text: "You're in the game and gaining momentum. The gap between where you are and elite is smaller than it looks. Stay the course, level up those missing skills.",
    },
    {
      icon: "🔧",
      label: "CALIBRATION IN PROGRESS",
      text: "Good foundation, room to build. Every expert was once at this exact stage. Treat the skill gaps as your roadmap, not your ceiling.",
    },
  ],
  low: [
    {
      icon: "💡",
      label: "INITIATION PHASE — EMBRACE IT",
      text: "Every master was once a beginner standing exactly where you are. This score is not a verdict — it's a starting coordinate. Use the 90-day roadmap below and watch the numbers change.",
    },
    {
      icon: "🌱",
      label: "POTENTIAL DETECTED",
      text: "Raw potential is unscored on any algorithm. Your journey is just beginning, and beginning is the hardest part. You've already done that. Build one skill at a time.",
    },
    {
      icon: "⚔",
      label: "GRIND MODE: ACTIVATE",
      text: "This is where legends are made — in the gap between where you are and where you're going. The résumé that gets you the dream role is built one commit, one project, one cert at a time.",
    },
  ],
};

function getMotiveData(score) {
  if (score >= 70)
    return {
      ...MOTIVES.high[Math.floor(Math.random() * 3)],
      cls: "high",
    };
  if (score >= 45)
    return {
      ...MOTIVES.medium[Math.floor(Math.random() * 3)],
      cls: "medium",
    };
  return { ...MOTIVES.low[Math.floor(Math.random() * 3)], cls: "low" };
}

// ─── Nav ─────────────────────────────────────────────────────────────────
// ─── Page ID labels for breadcrumb ──────────────────────────────────────
const PAGE_LABELS = {
  home: "Dashboard",
  batch: "Dashboard",
  history: "History",
  about: "Settings",
  settings: "Settings",
  candidates: "Candidates",
  analytics: "Analytics",
};

function setBreadcrumb(label) {
  const el = document.getElementById("breadcrumbCurrent");
  if (el) el.textContent = label;
}

function showPage(id, el) {
  document
    .querySelectorAll(".page")
    .forEach((p) => p.classList.remove("active"));
  document
    .querySelectorAll(".nav-tab")
    .forEach((t) => t.classList.remove("active"));
  const target = document.getElementById("page-" + id);
  if (target) target.classList.add("active");
  if (el) el.classList.add("active");
  setBreadcrumb(PAGE_LABELS[id] || id);
  if (id === "history") loadHistory();
  // collapse mobile nav after navigating
  const tabs = document.getElementById("navTabs");
  if (tabs) tabs.classList.remove("mobile-open");
}

// ─── Nav router — maps the 5 top-level nav items to actual pages.
// "Dashboard" resolves by role: candidate → home, recruiter → batch.
// "Settings" resolves to the new "settings" page, which now contains
// its own copy of the System Information cards (the old "about" page
// is kept in the DOM, unreferenced, in case it's wanted again later).
function navigateTo(navKey, el) {
  const role = localStorage.getItem("resumeai_role");
  let pageId = navKey;
  if (navKey === "dashboard") pageId = role === "recruiter" ? "batch" : "home";
  if (navKey === "settings") pageId = "settings";

  // find the right nav tab button to mark active (data-nav match)
  const navBtn = el || document.querySelector(`.nav-tab[data-nav="${navKey}"]`);
  showPage(pageId, navBtn);

  if (pageId === "settings") {
    applyTheme(getStoredThemePref()); // re-sync active state now buttons exist
    populateSettingsAccountInfo();
  }
  
  // 1. Fetches candidates when the Candidates tab is clicked
  if (pageId === "candidates") {
    loadCandidatesOverview(1);
  }
  
  // 2. NEW: Draws the charts when the Analytics tab is clicked
  if (pageId === "analytics") {
    if (currentBatchRunId) {
      // Point the charting engine to the Analytics tab wrapper
      const analyticsTabWrap = document.getElementById("analyticsWrap");
      if (analyticsTabWrap) {
          analyticsTabWrap.id = "analyticsChartsWrap"; 
      }
      // Trigger the chart drawing function
      loadBatchAnalytics(currentBatchRunId);
    } else {
      // If no batch has been run yet, remind the user
      document.getElementById("analyticsWrap").innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📊</div>
          <div class="empty-state-title">No analytics yet</div>
          <div class="empty-state-sub">Run a batch screening first to generate insights.</div>
        </div>`;
    }
  }
}

async function populateSettingsAccountInfo() {
  const emailEl = document.getElementById("settingsEmail");
  const roleEl = document.getElementById("settingsRole");
  if (!emailEl || !roleEl) return;
  try {
    const res = await fetch("/api/me");
    const data = await res.json();
    if (data.authenticated) {
      emailEl.textContent = data.email;
      roleEl.textContent =
        data.role === "recruiter" ? "Recruiter" : "Candidate";
    }
  } catch (e) {
    /* non-fatal */
  }
}

// ═══════════════════════════════════════════════════════════════════════
// CANDIDATES PAGE — cross-batch browser backed by /api/analytics/overview.
// Note: this endpoint returns `id` (not candidate_id) and `experience`
// (not exp) — different field names than /api/batch-score's response,
// kept distinct intentionally rather than silently renamed.
// ═══════════════════════════════════════════════════════════════════════
let candOverviewState = { page: 1, perPage: 20, pages: 1, total: 0 };

async function loadCandidatesOverview(page) {
  candOverviewState.page = page || candOverviewState.page;
  const minScore = document.getElementById("candOverviewMinScore")?.value || 0;
  const role = document.getElementById("candOverviewRole")?.value || "";
  const perPage = document.getElementById("candOverviewPerPage")?.value || 20;
  candOverviewState.perPage = perPage;

  const wrap = document.getElementById("candidatesListWrap");
  wrap.innerHTML = `<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card" style="margin-top:.6rem"></div><div class="skeleton skeleton-card" style="margin-top:.6rem"></div>`;

  try {
    const params = new URLSearchParams({
      page: candOverviewState.page,
      per_page: perPage,
      min_score: minScore,
      job_role: role,
    });

    // ✅ FIX: Added credentials: 'include'
    const res = await fetch(`/api/analytics/overview?${params}`, {
      method: "GET",
      credentials: "include",
    });

    await requireLoggedIn(res);
    const data = await res.json();
    if (!data.success)
      throw new Error(data.error || "Failed to load candidates");

    // ✅ FIX: Safety check to prevent the 'forEach' undefined error
    if (!data.candidates) {
      data.candidates = [];
    }

    renderCandidatesOverview(data);
  } catch (e) {
    wrap.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-title">Couldn't load candidates</div><div class="empty-state-sub">${e.message}</div></div>`;
  }
}

function renderCandidatesOverview(data) {
  candOverviewState.pages = data.pages || 1;
  candOverviewState.total = data.total || 0;
  const wrap = document.getElementById("candidatesListWrap");

  if (!data.candidates || data.candidates.length === 0) {
    wrap.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🗂️</div><div class="empty-state-title">No candidates match these filters</div><div class="empty-state-sub">Run a batch screening, or widen your filters above.</div></div>`;
  } else {
    wrap.innerHTML = `
            <div style="background:var(--card); border:2px solid var(--border-dark); overflow:auto; max-height:560px; border-radius:var(--radius-lg); box-shadow:var(--shadow-hard);">
              <table class="rank-table">
                <thead class="sticky-thead">
                  <tr><th>ID</th><th>Resume File</th><th>AI Score</th><th>Category</th><th>Role</th><th>Experience</th><th>Education</th><th>Tier</th></tr>
                </thead>
                <tbody>
                  ${data.candidates
                    .map(
                      (c) => `
                    <tr class="cand-row" tabindex="0" role="button" aria-label="View ${c.filename} details" onclick="openCandidateDrawer(${c.id})" onkeydown="if(event.key==='Enter')openCandidateDrawer(${c.id})">
                      <td style="font-size:.78rem;color:var(--muted-fg)">#${c.id}</td>
                      <td style="font-weight:500;font-size:.82rem">${c.filename || "—"}</td>
                      <td><span class="score-badge" style="background:rgba(139,92,246,.1);color:var(--accent);border-color:rgba(139,92,246,.3)">${c.ai_score}</span></td>
                      <td style="font-size:.78rem;color:var(--muted-fg)">${c.predicted_category || "—"}</td>
                      <td style="font-size:.78rem;color:var(--muted-fg)">${c.job_role || "—"}</td>
                      <td style="font-size:.82rem;font-weight:600">${c.experience}y</td>
                      <td style="font-size:.82rem;color:var(--muted-fg)">${c.education || "—"}</td>
                      <td><span class="score-badge" style="font-size:.7rem;background:var(--muted);color:var(--muted-fg)">${c.tier || "—"}</span></td>
                    </tr>`,
                    )
                    .join("")}
                </tbody>
              </table>
            </div>`;
  }

  const pagerInfo = document.getElementById("candOverviewPagerInfo");
  if (pagerInfo)
    pagerInfo.textContent = candOverviewState.total
      ? `Page ${candOverviewState.page} of ${candOverviewState.pages} · ${candOverviewState.total} total`
      : "0 results";
  const prevBtn = document.getElementById("candOverviewPrev");
  const nextBtn = document.getElementById("candOverviewNext");
  if (prevBtn) prevBtn.disabled = candOverviewState.page <= 1;
  if (nextBtn)
    nextBtn.disabled = candOverviewState.page >= candOverviewState.pages;
}

function changeCandidatesOverviewPage(delta) {
  const next = Math.max(
    1,
    Math.min(candOverviewState.pages, candOverviewState.page + delta),
  );
  loadCandidatesOverview(next);
}

function openHistoryPage() {
  const historyNavBtn = document.querySelector('.nav-tab[data-nav="history"]');
  showPage("history", historyNavBtn);
}

function toggleMobileNav() {
  const tabs = document.getElementById("navTabs");
  const burger = document.getElementById("navBurger");
  const isOpen = tabs.classList.toggle("mobile-open");
  if (burger) burger.setAttribute("aria-expanded", isOpen ? "true" : "false");
}

// ═══════════════════════════════════════════════════════════════════════
// GLOBAL SEARCH — searches nav destinations + AI feature modules.
// Each entry's action() runs on click/Enter; role filters what's shown.
// ═══════════════════════════════════════════════════════════════════════
function getSearchIndex() {
  const role = localStorage.getItem("resumeai_role");
  const items = [
    {
      icon: "🏠",
      label: "Dashboard",
      meta: "Home",
      action: () => navigateTo("dashboard"),
    },
    {
      icon: "🕘",
      label: "History",
      meta: "Past scans",
      action: () => navigateTo("history"),
    },
    {
      icon: "⚙️",
      label: "Settings",
      meta: "Appearance & account",
      action: () => navigateTo("settings"),
    },
  ];
  if (role === "candidate") {
    items.push(
      {
        icon: "⚡",
        label: "Run Resume Scan",
        meta: "Upload & score",
        action: () => {
          navigateTo("dashboard");
          setTimeout(
            () =>
              document
                .querySelector(".upload-section")
                ?.scrollIntoView({ behavior: "smooth" }),
            150,
          );
        },
      },
      {
        icon: "🎤",
        label: "Interview Q&A",
        meta: "AI module",
        action: () => runFeatureFromSearch("interview"),
      },
      {
        icon: "✉️",
        label: "Cover Letter Generator",
        meta: "AI module",
        action: () => runFeatureFromSearch("cover"),
      },
      {
        icon: "✏️",
        label: "Resume Rewrite",
        meta: "AI module",
        action: () => runFeatureFromSearch("rewrite"),
      },
      {
        icon: "💼",
        label: "LinkedIn Optimizer",
        meta: "AI module",
        action: () => runFeatureFromSearch("linkedin"),
      },
      {
        icon: "💰",
        label: "Salary Estimator",
        meta: "AI module",
        action: () => runFeatureFromSearch("salary"),
      },
      {
        icon: "🗺️",
        label: "90-Day Roadmap",
        meta: "AI module",
        action: () => runFeatureFromSearch("roadmap"),
      },
      {
        icon: "🚩",
        label: "Risk Assessment",
        meta: "AI module",
        action: () => runFeatureFromSearch("redflag"),
      },
    );
  } else if (role === "recruiter") {
    items.push(
      {
        icon: "📁",
        label: "Upload Resume Pack",
        meta: "Batch screening",
        action: () => {
          navigateTo("dashboard");
          setTimeout(
            () =>
              document
                .querySelector(".batch-drop")
                ?.scrollIntoView({ behavior: "smooth" }),
            150,
          );
        },
      },
      {
        icon: "🗂️",
        label: "Candidates",
        meta: "All candidates",
        action: () => navigateTo("candidates"),
      },
      {
        icon: "📊",
        label: "Analytics",
        meta: "Hiring insights",
        action: () => navigateTo("analytics"),
      },
      {
        icon: "⬇",
        label: "Export CSV",
        meta: "Last batch results",
        action: () => exportCSV(),
      },
    );
  }
  return items;
}

function runFeatureFromSearch(type) {
  navigateTo("dashboard");
  if (!currentData) {
    toast("Run a scan first", "error");
    return;
  }
  setTimeout(() => {
    const btn = document.querySelector(`.feat-nav-btn[onclick*="'${type}'"]`);
    if (btn) {
      btn.scrollIntoView({ behavior: "smooth", block: "center" });
      runFeatureDash(type, btn);
    }
  }, 150);
}

function handleGlobalSearch(query) {
  const resultsEl = document.getElementById("navSearchResults");
  const q = query.trim().toLowerCase();
  searchActiveIndex = -1;
  if (!q) {
    resultsEl.classList.remove("open");
    resultsEl.innerHTML = "";
    document
      .getElementById("globalSearch")
      .setAttribute("aria-expanded", "false");
    return;
  }
  const matches = getSearchIndex().filter(
    (item) =>
      item.label.toLowerCase().includes(q) ||
      item.meta.toLowerCase().includes(q),
  );
  currentSearchMatches = matches;
  if (matches.length === 0) {
    resultsEl.innerHTML = `<div class="nav-search-empty">No matches for "${query}"</div>`;
  } else {
    resultsEl.innerHTML = matches
      .map(
        (item, i) => `
            <div class="nav-search-result" role="option" id="nsr-${i}" data-search-idx="${i}">
              <div class="nsr-icon">${item.icon}</div>
              <div>
                <div>${item.label}</div>
                <div class="nsr-meta">${item.meta}</div>
              </div>
            </div>`,
      )
      .join("");
    resultsEl.querySelectorAll(".nav-search-result").forEach((el, i) => {
      el.addEventListener("click", () => selectSearchResult(i));
    });
  }
  resultsEl.classList.add("open");
  document.getElementById("globalSearch").setAttribute("aria-expanded", "true");
}

let currentSearchMatches = [];
let searchActiveIndex = -1;

function selectSearchResult(i) {
  if (!currentSearchMatches[i]) return;
  currentSearchMatches[i].action();
  document.getElementById("navSearchResults").classList.remove("open");
  const input = document.getElementById("globalSearch");
  input.value = "";
  input.setAttribute("aria-expanded", "false");
}

function handleSearchKeydown(e) {
  const resultsEl = document.getElementById("navSearchResults");
  if (
    !resultsEl.classList.contains("open") ||
    currentSearchMatches.length === 0
  ) {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "ArrowDown") {
    e.preventDefault();
    searchActiveIndex = Math.min(
      searchActiveIndex + 1,
      currentSearchMatches.length - 1,
    );
    highlightSearchResult();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    searchActiveIndex = Math.max(searchActiveIndex - 1, 0);
    highlightSearchResult();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (searchActiveIndex >= 0) selectSearchResult(searchActiveIndex);
    else if (currentSearchMatches.length > 0) selectSearchResult(0);
  } else if (e.key === "Escape") {
    resultsEl.classList.remove("open");
    e.target.blur();
  }
}

function highlightSearchResult() {
  document.querySelectorAll(".nav-search-result").forEach((el, i) => {
    el.style.background = i === searchActiveIndex ? "var(--muted)" : "";
  });
  document
    .getElementById(`nsr-${searchActiveIndex}`)
    ?.scrollIntoView({ block: "nearest" });
}

// close search results when clicking outside
document.addEventListener("click", (e) => {
  const wrap = document.getElementById("navSearchWrap");
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById("navSearchResults")?.classList.remove("open");
  }
});

// ═══════════════════════════════════════════════════════════════════════
// FLOATING ACTION BUTTON — quick upload, role-aware
// ═══════════════════════════════════════════════════════════════════════
function handleFabClick() {
  const role = localStorage.getItem("resumeai_role");
  if (role === "recruiter") {
    navigateTo("dashboard");
    setTimeout(() => document.getElementById("batchFiles")?.click(), 150);
  } else {
    navigateTo("dashboard");
    setTimeout(() => document.getElementById("resumeFile")?.click(), 150);
  }
}

// ─── Input toggle ────────────────────────────────────────────────────────
function switchInput(mode, el) {
  inputMode = mode;
  document
    .querySelectorAll(".tab-btn")
    .forEach((b) => b.classList.remove("active"));
  if (el) el.classList.add("active");
  document.getElementById("fileInput").style.display =
    mode === "file" ? "block" : "none";
  document.getElementById("textInput").style.display =
    mode === "text" ? "block" : "none";
}

// ─── Drag-drop ───────────────────────────────────────────────────────────
const dropZone = document.getElementById("dropZone");
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.style.borderColor = "var(--accent)";
  dropZone.style.borderStyle = "solid";
});
dropZone.addEventListener("dragleave", () => {
  dropZone.style.borderColor = "";
  dropZone.style.borderStyle = "dashed";
});
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.style.borderColor = "";
  dropZone.style.borderStyle = "dashed";
  const f = e.dataTransfer.files[0];
  if (f) {
    document.getElementById("resumeFile").files = e.dataTransfer.files;
    document.getElementById("fileName").textContent = "▸ " + f.name;
  }
});
function handleFileSelect(inp) {
  if (inp.files[0])
    document.getElementById("fileName").textContent = "▸ " + inp.files[0].name;
}

// ─── Toast ───────────────────────────────────────────────────────────────
function toast(msg, type = "success") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast " + type + " show";
  setTimeout(() => t.classList.remove("show"), 3000);
}

// ─── Clear ───────────────────────────────────────────────────────────────
function clearAll() {
  document.getElementById("resumeFile").value = "";
  document.getElementById("fileName").textContent = "";
  document.getElementById("resumeText").value = "";
  document.getElementById("resultsSection").classList.remove("show");
  document.getElementById("resultsSection").style.display = "none";
  document.getElementById("featureResult").classList.remove("show");
  currentData = null;
}

// ─── Analyze ─────────────────────────────────────────────────────────────
async function analyzeResume() {
  const role = document.getElementById("jobRole").value;
  const loader = document.getElementById("loader");
  const btn = document.getElementById("analyzeBtn");
  btn.disabled = true;
  loader.classList.add("show");
  document.getElementById("loaderText").textContent =
    "Processing your resume...";
  document.getElementById("resultsSection").style.display = "none";

  try {
    let data;
    // NEW: Grab the JD text if it exists
    const jdText = document.getElementById("jobDescription")
      ? document.getElementById("jobDescription").value.trim()
      : "";

    if (inputMode === "file") {
      const file = document.getElementById("resumeFile").files[0];
      if (!file) {
        toast("No file selected", "error");
        btn.disabled = false;
        loader.classList.remove("show");
        return;
      }

      const fd = new FormData();
      fd.append("file", file);
      fd.append("job_role", role);
      fd.append("job_description", jdText); // <-- Append JD text to the form data

      const res = await fetch("/api/score", { method: "POST", body: fd });
      await requireLoggedIn(res);
      data = await res.json();
    } else {
      const text = document.getElementById("resumeText").value.trim();
      if (!text) {
        toast("No text entered", "error");
        btn.disabled = false;
        loader.classList.remove("show");
        return;
      }

      const res = await fetch("/api/score-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // <-- Add job_description to the JSON payload
        body: JSON.stringify({
          text,
          job_role: role,
          job_description: jdText,
        }),
      });
      await requireLoggedIn(res);
      data = await res.json();
    }
    if (!data.success) throw new Error(data.error || "Scan failed");
    currentData = data;
    renderResults(data);
    toast("Scan complete ✓");
  } catch (e) {
    toast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
    loader.classList.remove("show");
  }
}

// ─── Render results ───────────────────────────────────────────────────────
function renderResults(d) {
  const rs = document.getElementById("resultsSection");
  rs.style.display = "block";
  rs.classList.add("show");
  rs.scrollIntoView({ behavior: "smooth", block: "start" });

  const score = d.ai_score;

  // Motivational banner
  const mv = getMotiveData(score);
  const mb = document.getElementById("motiveBanner");
  mb.style.display = "flex";
  mb.className = "motive-banner " + mv.cls;
  document.getElementById("motiveIcon").textContent = mv.icon;
  document.getElementById("motiveLabel").textContent = mv.label;
  document.getElementById("motiveText").textContent = mv.text;

  // Score ring
  document.getElementById("scoreNum").textContent = score;
  drawRing(score);

  // Title + tier
  document.getElementById("scoreTitle").textContent = d.job_role + " · Report";
  const tierData =
    score >= 85
      ? ["Elite Candidate", "tier-elite"]
      : score >= 70
        ? ["Strong Profile", "tier-strong"]
        : score >= 50
          ? ["Developing", "tier-developing"]
          : ["Needs Work", "tier-needs"];
  const te = document.getElementById("scoreTier");
  te.textContent = "▸ " + tierData[0];
  te.className = "score-tier " + tierData[1];

  // Pills
  document.getElementById("metaPills").innerHTML = [
    ["Exp", d.extracted_experience + "yrs"],
    ["Edu", d.extracted_education || "—"],
    ["ATS", d.ats_score + "%"],
  ]
    .map(([l, v]) => `<div class="pill">${l}: <span>${v}</span></div>`)
    .join("");

  // Section bars
  const barCls = {
    Experience: "bar-exp",
    Education: "bar-edu",
    Projects: "bar-proj",
    Certifications: "bar-cert",
    Skills: "bar-skills",
    "ATS Match": "bar-ats",
  };
  document.getElementById("sectionBars").innerHTML = Object.entries(
    d.section_scores,
  )
    .map(
      ([k, v]) => `
              <div class="section-bar">
                <div class="bar-header">
                  <span class="bar-label">${k}</span>
                  <span class="bar-val" style="color:${v >= 70 ? "var(--quaternary)" : v >= 40 ? "var(--tertiary)" : "var(--danger)"}">${v}</span>
                </div>
                <div class="bar-track"><div class="bar-fill ${barCls[k] || "bar-exp"}" style="width:0%" data-val="${v}"></div></div>
              </div>`,
    )
    .join("");
  setTimeout(() => {
    document
      .querySelectorAll(".bar-fill")
      .forEach((b) => (b.style.width = b.dataset.val + "%"));
  }, 80);

  // Skills
  document.getElementById("foundSkills").innerHTML =
    (d.found_skills || [])
      .map((s) => `<span class="skill-tag skill-found">${s}</span>`)
      .join("") ||
    '<span style="color:var(--muted-fg);font-size:.8rem">None detected</span>';
  document.getElementById("missingSkills").innerHTML =
    (d.missing_skills || [])
      .map((s) => `<span class="skill-tag skill-missing">${s}</span>`)
      .join("") ||
    '<span style="color:var(--quaternary);font-size:.8rem;font-weight:600">Full coverage!</span>';
  document.getElementById("atsHits").innerHTML = (d.ats_hits || [])
    .map((s) => `<span class="ats-hit">${s}</span>`)
    .join("");

  // Charts
  drawRadar(d.section_scores);
  drawDoughnut(d.found_skills?.length || 0, d.missing_skills?.length || 0);
  drawBench(score);
  document.getElementById("featureResult").classList.remove("show");

  // Mirror everything to the new dashboard UI
  setTimeout(() => mirrorToDashboard(d), 100);
}

// ─── Charts ───────────────────────────────────────────────────────────────
function drawRing(score) {
  if (ringInst) ringInst.destroy();
  const c = score >= 70 ? "#34D399" : score >= 45 ? "#60A5FA" : "#EF4444";
  ringInst = new Chart(document.getElementById("ringChart"), {
    type: "doughnut",
    data: {
      datasets: [
        {
          data: [score, 100 - score],
          backgroundColor: [c, "#F1F5F9"],
          borderWidth: 0,
        },
      ],
    },
    options: {
      cutout: "80%",
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      animation: { duration: 1400, easing: "easeOutQuart" },
    },
  });
}

function drawRadar(scores) {
  if (radarInst) radarInst.destroy();
  radarInst = new Chart(document.getElementById("radarChart"), {
    type: "radar",
    data: {
      labels: Object.keys(scores),
      datasets: [
        {
          label: "Score",
          data: Object.values(scores),
          backgroundColor: "rgba(139,92,246,.12)",
          borderColor: "#8B5CF6",
          pointBackgroundColor: "#8B5CF6",
          pointRadius: 5,
          borderWidth: 2.5,
          pointBorderColor: "#FFFFFF",
          pointBorderWidth: 2,
        },
      ],
    },
    options: {
      scales: {
        r: {
          min: 0,
          max: 100,
          grid: { color: "#E2E8F0" },
          pointLabels: {
            color: "#64748B",
            font: { size: 11, weight: "600" },
          },
          ticks: { display: false },
        },
      },
      plugins: { legend: { display: false } },
      animation: { duration: 1000 },
    },
  });
}

function drawDoughnut(found, missing) {
  if (doughInst) doughInst.destroy();
  doughInst = new Chart(document.getElementById("doughnutChart"), {
    type: "doughnut",
    data: {
      labels: ["Matched", "Gaps"],
      datasets: [
        {
          data: [found, missing],
          backgroundColor: ["#34D399", "#FCA5A5"],
          borderColor: ["#FFFFFF", "#FFFFFF"],
          borderWidth: 3,
          hoverOffset: 6,
        },
      ],
    },
    options: {
      plugins: {
        legend: {
          labels: { color: "#64748B", font: { size: 11 }, padding: 14 },
        },
      },
      animation: { duration: 900 },
    },
  });
}

function drawBench(score) {
  if (benchInst) benchInst.destroy();
  const cols = ["#8B5CF6", "#CBD5E1", "#CBD5E1", "#CBD5E1", "#CBD5E1"];
  benchInst = new Chart(document.getElementById("barBenchChart"), {
    type: "bar",
    data: {
      labels: ["YOU", "ENTRY", "MID", "SENIOR", "ELITE"],
      datasets: [
        {
          data: [score, 45, 65, 80, 92],
          backgroundColor: cols,
          borderColor: [
            "#1E293B",
            "transparent",
            "transparent",
            "transparent",
            "transparent",
          ],
          borderWidth: 2,
          borderRadius: 8,
        },
      ],
    },
    options: {
      scales: {
        y: {
          min: 0,
          max: 100,
          grid: { color: "#F1F5F9" },
          ticks: { color: "#64748B" },
        },
        x: {
          grid: { display: false },
          ticks: { color: "#64748B", font: { weight: "600" } },
        },
      },
      plugins: { legend: { display: false } },
      animation: { duration: 900 },
    },
  });
}

// ─── AI Features ──────────────────────────────────────────────────────────
async function runFeature(type) {
  if (!currentData) {
    toast("Run a scan first", "error");
    return;
  }
  const rb = document.getElementById("featureResult");
  const fl = document.getElementById("featureLoader");
  const fc = document.getElementById("featureContent");
  rb.classList.add("show");
  fl.style.display = "block";
  fc.innerHTML = "";
  rb.scrollIntoView({ behavior: "smooth", block: "start" });

  const d = currentData;
  const payload = {
    job_role: d.job_role,
    found_skills: d.found_skills,
    missing_skills: d.missing_skills,
    exp: d.extracted_experience,
    education: d.extracted_education,
    score: d.ai_score,
  };
  const ep = {
    interview: "/api/interview-questions",
    cover: "/api/cover-letter",
    rewrite: "/api/rewrite",
    linkedin: "/api/linkedin-summary",
    salary: "/api/salary",
    roadmap: "/api/roadmap",
  };
  try {
    const res = await fetch(ep[type], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);
    fl.style.display = "none";
    renderFeature(type, data, fc);
  } catch (e) {
    fl.style.display = "none";
    fc.innerHTML = `<p style="color:var(--danger);font-size:.85rem;font-weight:500">Error: ${e.message}</p>`;
  }
}

function renderFeature(type, data, el) {
  if (type === "interview") {
    el.innerHTML =
      '<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--accent)">🎤</div>Interview Questions</div>' +
      (data.questions || [])
        .map(
          (q) => `
                  <div class="q-item">
                    <div class="q-category cat-${q.category}">${q.category.charAt(0).toUpperCase() + q.category.slice(1)}</div>
                    <div class="q-text">${q.question}</div>
                    <div class="q-hint">${q.hint}</div>
                  </div>`,
        )
        .join("");
  } else if (type === "cover") {
    el.innerHTML = `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--secondary)">✉️</div>Cover Letter</div>
            <div class="text-output">${data.cover_letter}</div>
            <button class="btn btn-outline btn-sm" style="margin-top:.85rem" onclick="copyTxt(${JSON.stringify(data.cover_letter)})">📋 Copy to Clipboard</button>`;
  } else if (type === "rewrite") {
    el.innerHTML =
      '<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--tertiary)">✏️</div>Rewrite Suggestions</div>' +
      (data.suggestions || [])
        .map(
          (s) => `
                  <div class="rewrite-item">
                    <div class="rewrite-section">${s.section}</div>
                    <div class="rewrite-issue">⚠ ${s.issue}</div>
                    <div class="rewrite-new">${s.rewritten}</div>
                  </div>`,
        )
        .join("");
  } else if (type === "linkedin") {
    el.innerHTML = `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:#60A5FA">💼</div>LinkedIn Summary</div>
            <div class="text-output">${data.linkedin_summary}</div>
            <button class="btn btn-outline btn-sm" style="margin-top:.85rem" onclick="copyTxt(${JSON.stringify(data.linkedin_summary)})">📋 Copy to Clipboard</button>`;
  } else if (type === "salary") {
    const s = data.salary;
    el.innerHTML = `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--quaternary)">💰</div>Compensation Estimate</div>
            <div class="salary-range">${s.min_salary} — ${s.max_salary} <span style="font-size:.9rem;opacity:.6;font-weight:500">${s.currency}</span></div>
            <div class="score-tier tier-developing" style="display:inline-flex;margin-bottom:.85rem">${s.level}</div>
            <div style="margin-bottom:.5rem;font-family:'Outfit',system-ui;font-size:.72rem;font-weight:800;letter-spacing:.1em;color:var(--muted-fg);text-transform:uppercase">Skills that boost salary</div>
            <div class="skill-wrap">${(s.skills_to_increase_salary || []).map((sk) => `<span class="skill-tag skill-found">${sk}</span>`).join("")}</div>
            <div class="salary-insight">${s.market_insight}</div>`;
  } else if (type === "roadmap") {
    const r = data.roadmap;
    el.innerHTML = `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:#A78BFA">🗺️</div>90-Day Mission Plan</div>
            <div class="roadmap-phases">
              ${["day_1_30", "day_31_60", "day_61_90"]
                .map((k, i) => {
                  const ph = r[k] || {};
                  const labels = [
                    "Phase 1 · Days 1–30",
                    "Phase 2 · Days 31–60",
                    "Phase 3 · Days 61–90",
                  ];
                  const cls = ["phase-1", "phase-2", "phase-3"];
                  return `<div class="phase ${cls[i]}">
                    <div class="phase-label">${labels[i]}</div>
                    <div class="phase-focus">${ph.focus || ""}</div>
                    <ul class="phase-tasks">${(ph.tasks || []).map((t) => `<li>${t}</li>`).join("")}</ul>
                    <div class="phase-resource">${ph.resource || ""}</div>
                  </div>`;
                })
                .join("")}
            <div style="margin-top:1rem;background:rgba(251,191,36,.1);border:2px solid var(--border-dark);padding:.9rem 1.1rem;font-size:.85rem;font-weight:600;color:#92400E;border-radius:var(--radius-md);box-shadow:3px 3px 0 var(--border-dark)">
              🏁 Milestone: ${r.milestone || ""}
            </div>`;
  } else if (type === "redflag") {
    const flags = data.flags || [];
    if (flags.length === 0) {
      el.innerHTML = `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--quaternary)">✅</div>Risk Assessment</div>
            <div style="padding:2rem; text-align:center; background:rgba(52,211,153,.1); border:2px dashed #059669; border-radius:var(--radius-md); color:#065F46; font-weight:600;">No significant red flags detected in this profile.</div>`;
    } else {
      el.innerHTML =
        `<div class="card-title" style="margin-bottom:1rem"><div class="cicon" style="background:var(--danger); color:white;">🚩</div>Risk Assessment</div>` +
        flags
          .map(
            (f) => `
                <div style="background:var(--muted); border:2px solid var(--border); border-left:4px solid ${f.severity === "High" ? "var(--danger)" : f.severity === "Medium" ? "var(--tertiary)" : "var(--secondary)"}; padding:1rem; margin-bottom:.65rem; border-radius:var(--radius-md);">
                  <div style="display:flex; justify-content:space-between; margin-bottom:.3rem;">
                    <span style="font-family:'Outfit',system-ui; font-size:.85rem; font-weight:800; color:var(--fg);">${f.flag}</span>
                    <span style="font-size:.7rem; font-weight:800; text-transform:uppercase; letter-spacing:.05em; color:${f.severity === "High" ? "var(--danger)" : "var(--muted-fg)"}">${f.severity} Risk</span>
                  </div>
                  <div style="color:var(--muted-fg); font-size:.85rem; line-height:1.5;">${f.details}</div>
                </div>
              `,
          )
          .join("");
    }
  } else if (type === "scorecard") {
    const criteria = data.scorecard || [];
    el.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem;">
              <div class="card-title" style="margin-bottom:0;"><div class="cicon" style="background:#1E293B; color:white;">📋</div>Official Scorecard</div>
              <button class="btn btn-outline btn-sm" onclick="window.print()">🖨️ Print / Save PDF</button>
            </div>
            
            <div id="printableScorecard" style="display:flex; flex-direction:column; gap:1rem;">
              <div style="padding:1rem; background:var(--muted); border:2px solid var(--border-dark); border-radius:var(--radius-md); text-align:center; font-family:'Outfit',system-ui; font-weight:800;">
                CANDIDATE EVALUATION: <span style="color:var(--accent)">${document.getElementById("jobRole").value.toUpperCase()}</span>
              </div>
              
              ${criteria
                .map(
                  (c, i) => `
                <div style="border:2px solid var(--border); border-radius:var(--radius-md); overflow:hidden;">
                  <div style="background:var(--muted); padding:.75rem 1rem; font-family:'Outfit',system-ui; font-size:.85rem; font-weight:800; border-bottom:2px solid var(--border); display:flex; justify-content:space-between;">
                    <span>${i + 1}. ${c.competency}</span>
                    <span style="color:var(--muted-fg)">Score: [ 1 - 2 - 3 - 4 - 5 ]</span>
                  </div>
                  <div style="padding:1rem;">
                    <div style="font-size:.85rem; font-weight:700; color:var(--fg); margin-bottom:.5rem;">Q: ${c.question}</div>
                    <div style="font-size:.8rem; color:var(--muted-fg); padding-left:.75rem; border-left:2px solid var(--tertiary);">
                      <strong style="color:var(--fg)">Look for:</strong> ${c.look_for}
                    </div>
                    <div style="margin-top:1rem; border-top:1px dashed var(--border); padding-top:.5rem; font-size:.75rem; color:var(--muted-fg); font-style:italic;">Notes:</div>
                  </div>
                </div>
              `,
                )
                .join("")}
            </div>
          `;
  } else if (type === "outreach") {
    const email = data.email || { subject: "", body: "" };
    const combinedText = `Subject: ${email.subject}\n\n${email.body}`;
    const mailtoLink = `mailto:?subject=${encodeURIComponent(email.subject)}&body=${encodeURIComponent(email.body)}`;

    el.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem;">
              <div class="card-title" style="margin-bottom:0;"><div class="cicon" style="background:#0284C7; color:white;">📨</div>Recruiter Outreach</div>
              <div style="display:flex; gap:.5rem;">
                  <button class="btn btn-outline btn-sm" onclick="copyTxt(${JSON.stringify(combinedText).replace(/"/g, "&quot;")})">📋 Copy</button>
                  <a href="${mailtoLink}" class="btn btn-primary btn-sm" style="text-decoration:none; padding:.4rem 1rem; font-size:.78rem;">✉️ Open in Mail</a>
              </div>
            </div>
            
            <div style="background:var(--card); border:2px solid var(--border-dark); border-radius:var(--radius-md); overflow:hidden; box-shadow:var(--shadow-hard);">
              <div style="padding:.85rem 1rem; background:var(--muted); border-bottom:2px solid var(--border); font-family:'Plus Jakarta Sans',system-ui; font-size:.85rem;">
                  <strong style="color:var(--muted-fg)">Subject:</strong> <span style="color:var(--fg); font-weight:700;">${email.subject}</span>
              </div>
              <div style="padding:1.2rem; font-size:.88rem; line-height:1.8; color:var(--fg); white-space:pre-wrap;">${email.body}</div>
            </div>
          `;
  }
}

function copyTxt(txt) {
  navigator.clipboard.writeText(txt);
  toast("Copied to clipboard ✓");
}

// ─── Batch ───────────────────────────────────────────────────────────────
const MAX_BATCH_FILES = 20;
const MAX_FILE_SIZE_MB = 10;
const MAX_ZIP_SIZE_MB = 50;
const ACCEPTED_EXT = [".pdf", ".docx", ".txt"];

function handleBatchDrop(e) {
  e.preventDefault();
  document.getElementById("batchDropZone").classList.remove("dragover");
  const dropped = Array.from(e.dataTransfer.files);
  ingestBatchFiles(dropped);
}

function handleBatchSelect(inp) {
  ingestBatchFiles(Array.from(inp.files));
}

// Note: ZIP archives are accepted here and expanded server-side (see
// app.py's expand_uploaded_files()). The client can't know how many
// resumes are inside a ZIP without unzipping it itself, so the 20-file
// cap is enforced authoritatively by the backend after extraction —
// this client-side check only catches the easy/cheap cases up front
// (obviously-too-many individual files, oversized files).
function ingestBatchFiles(incoming) {
  const meta = document.getElementById("batchUploadMeta");
  const rejected = [];
  const accepted = [];
  let hasZip = false;

  incoming.forEach((f) => {
    const name = f.name.toLowerCase();
    if (name.endsWith(".zip")) {
      if (f.size > MAX_ZIP_SIZE_MB * 1024 * 1024) {
        rejected.push(`${f.name} (ZIP exceeds ${MAX_ZIP_SIZE_MB}MB)`);
        return;
      }
      hasZip = true;
      accepted.push(f);
      return;
    }
    if (!ACCEPTED_EXT.some((ext) => name.endsWith(ext))) {
      rejected.push(`${f.name} (unsupported file type)`);
      return;
    }
    if (f.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      rejected.push(`${f.name} (exceeds ${MAX_FILE_SIZE_MB}MB)`);
      return;
    }
    accepted.push(f);
  });

  // Only enforce the 20-item cap for non-ZIP uploads — a ZIP's true
  // resume count is unknown until the server extracts it.
  if (!hasZip) {
    batchFiles = [...batchFiles, ...accepted].slice(0, MAX_BATCH_FILES);
  } else {
    batchFiles = [...batchFiles, ...accepted];
  }

  renderBatchFileList();
  updateRecruiterStats({
    total: batchFiles.length,
    status: batchFiles.length ? "Ready to scan" : "Idle",
  });

  if (meta) {
    const parts = [];
    if (batchFiles.length) {
      const zipNote = hasZip ? " (ZIP contents are counted after upload)" : "";
      parts.push(
        `<span style="color:#10895c;font-weight:700;">✓ ${batchFiles.length} item${batchFiles.length === 1 ? "" : "s"} ready${zipNote}</span>`,
      );
    }
    if (rejected.length)
      parts.push(
        `<span style="color:var(--danger);display:block;margin-top:.3rem;">⚠ ${rejected.length} file${rejected.length === 1 ? "" : "s"} skipped: ${rejected.join("; ")}</span>`,
      );
    if (!hasZip && batchFiles.length >= MAX_BATCH_FILES)
      parts.push(
        `<span style="color:var(--danger);display:block;margin-top:.3rem;">Max ${MAX_BATCH_FILES} files per batch reached.</span>`,
      );
    meta.innerHTML = parts.join("");
  }
  if (rejected.length)
    toast(
      `${rejected.length} file(s) skipped — see details below upload`,
      "error",
    );
}

// ─── Searchable job-role selector ──────────────────────────────────────
function filterRoleOptions(query) {
  const select = document.getElementById("batchRole");
  const dropdown = document.getElementById("batchRoleDropdown");
  const q = query.trim().toLowerCase();
  const options = Array.from(select.options).map((o) => o.value);
  const matches = q
    ? options.filter((o) => o.toLowerCase().includes(q))
    : options;
  dropdown.innerHTML = matches.length
    ? matches
        .map(
          (o) =>
            `<div class="nav-search-result" onclick="selectRoleOption('${o.replace(/'/g, "\\'")}')">${o}</div>`,
        )
        .join("")
    : `<div class="nav-search-empty">No matching roles</div>`;
  dropdown.classList.add("open");
}

function selectRoleOption(role) {
  document.getElementById("batchRole").value = role;
  document.getElementById("batchRoleSearch").value = role;
  document.getElementById("batchRoleDropdown").classList.remove("open");
}

document.addEventListener("click", (e) => {
  const dropdown = document.getElementById("batchRoleDropdown");
  const input = document.getElementById("batchRoleSearch");
  if (
    dropdown &&
    input &&
    !input.contains(e.target) &&
    !dropdown.contains(e.target)
  ) {
    dropdown.classList.remove("open");
  }
  const colMenu = document.getElementById("colToggleMenu");
  if (
    colMenu &&
    !e.target.closest("#colToggleMenu") &&
    !e.target.closest("button[onclick*='colToggleMenu']")
  ) {
    colMenu.classList.remove("open");
  }
});

function renderBatchFileList() {
  document.getElementById("batchFileList").innerHTML = batchFiles
    .map(
      (f, i) =>
        `<div class="file-item"><span>▸ ${f.name}</span><span>${(f.size / 1024).toFixed(0)} KB <button type="button" aria-label="Remove ${f.name}" onclick="removeBatchFile(${i})" style="background:none;border:none;color:var(--danger);cursor:pointer;font-weight:700;margin-left:.5rem;">✕</button></span></div>`,
    )
    .join("");
}

function removeBatchFile(idx) {
  batchFiles.splice(idx, 1);
  renderBatchFileList();
  updateRecruiterStats({
    total: batchFiles.length,
    status: batchFiles.length ? "Ready to scan" : "Idle",
  });
}

// ─── Score/Tier thresholds — single source of truth, matches backend
// tier_breakdown buckets (excellent ≥85 | good 70-84 | average 50-69 | rejected <50) ──
let SHORTLIST_THRESHOLD = 50; // ai_score >= this counts as "shortlisted" client-side

function updateRecruiterStats(stats = {}) {
  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  setText("statTotalCandidates", stats.total ?? 0);
  setText("statShortlisted", stats.shortlisted ?? 0);
  setText("statRejected", stats.rejected ?? 0);
  const avg = stats.average;
  setText("statAverageScore", avg === null || avg === undefined ? "--" : avg);
  setText("recruiterHeroScore", avg === null || avg === undefined ? "--" : avg);
  setText(
    "statHighestScore",
    stats.highest === null || stats.highest === undefined
      ? "--"
      : stats.highest,
  );
  setText(
    "statLowestScore",
    stats.lowest === null || stats.lowest === undefined ? "--" : stats.lowest,
  );
  if (stats.status) setText("statProcessingStatus", stats.status);
}

// ═══════════════════════════════════════════════════════════════════════
// RECRUITER ATS DASHBOARD — state
// ═══════════════════════════════════════════════════════════════════════
let currentBatchRunId = null;
let tableState = {
  sortKey: "rank",
  sortDir: "asc",
  search: "",
  page: 1,
  perPage: 10,
  minScore: 0,
  expFilter: "any",
  eduFilter: "any",
  catFilter: "any",
};
let visibleCols = {
  rank: true,
  candidate_id: true,
  filename: true,
  ai_score: true,
  match_pct: true,
  predicted_category: true,
  exp: true,
  education: true,
  skills: true,
  status: true,
};
let analyticsCharts = {}; // name -> Chart instance

const BATCH_POLL_INTERVAL_MS = 600; // was 1500 — scoring itself is fast (no LLM calls per resume), so a long poll interval was adding perceptible delay on top of actual processing time

async function runBatch() {
  if (!batchFiles.length) {
    toast("No files selected", "error");
    return;
  }
  const role = document.getElementById("batchRole").value;
  const loader = document.getElementById("batchLoader");
  loader.classList.add("show");
  document.getElementById("batchResults").style.display = "none";
  updateRecruiterStats({ total: batchFiles.length, status: "Processing…" });

  const hasZip = batchFiles.some((f) => f.name.toLowerCase().endsWith(".zip"));
  // Can't know the real resume count for a ZIP until the server extracts it,
  // so route to the large/async endpoint whenever a ZIP is involved or the
  // upload already has more than 20 items — /api/batch-score's hard cap.
  const useLargeBatch = hasZip || batchFiles.length > 20;

  const fd = new FormData();
  batchFiles.forEach((f) => fd.append("files[]", f));
  fd.append("job_role", role);

  try {
    if (useLargeBatch) {
      await runLargeBatch(fd, role);
    } else {
      await runSmallBatch(fd);
    }
  } catch (e) {
    toast("Error: " + e.message, "error");
    updateRecruiterStats({ total: batchFiles.length, status: "Failed" });
  } finally {
    loader.classList.remove("show");
  }
}

// ─── Small batch: synchronous, ≤20 resumes, single request/response ──────
async function runSmallBatch(fd) {
  const res = await fetch("/api/batch-score", { method: "POST", body: fd });
  await requireLoggedIn(res);
  const data = await res.json();

  // If the server reports the upload actually expanded past 20 resumes
  // (e.g. a non-ZIP path we didn't pre-detect), retry via the large path
  // instead of just failing.
  if (!data.success && /maximum is 20/i.test(data.error || "")) {
    toast("More than 20 resumes detected — switching to large-batch mode…");
    return runLargeBatch(fd);
  }
  if (!data.success) throw new Error(data.error);

  batchCache = data.ranked;
  currentBatchRunId = data.batch_run_id || null;
  tableState.page = 1;
  renderBatch(data);
  toast("Batch scan complete ✓");
  if (currentBatchRunId) loadBatchAnalytics(currentBatchRunId);
}

// ─── Large batch: async job + polling, up to 1000 resumes ────────────────
async function runLargeBatch(fd) {
  const res = await fetch("/api/batch-large", { method: "POST", body: fd });
  await requireLoggedIn(res);
  const data = await res.json();
  if (!data.success) throw new Error(data.error);

  const jobId = data.job_id;
  const total = data.total;
  updateRecruiterStats({ total, status: `Processing 0 / ${total}…` });

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const statusRes = await fetch(`/api/batch-status/${jobId}`);
        await requireLoggedIn(statusRes);
        const job = await statusRes.json();
        if (job.error) {
          reject(new Error(job.error));
          return;
        }

        updateRecruiterStats({
          total: job.total,
          status:
            job.status === "done"
              ? "Completed"
              : `Processing ${job.processed} / ${job.total}…`,
        });

        if (job.status === "done") {
          batchCache = job.results;
          currentBatchRunId = job.batch_run_id || null;
          tableState.page = 1;
          renderBatch({ ranked: job.results, errors: job.errors || [] });
          toast(`Batch scan complete ✓ (${job.total} resumes)`);
          if (currentBatchRunId) loadBatchAnalytics(currentBatchRunId);
          resolve();
        } else {
          setTimeout(poll, BATCH_POLL_INTERVAL_MS);
        }
      } catch (e) {
        reject(e);
      }
    };
    poll();
  });
}

function renderBatch(data) {
  const rankedRows = data.ranked || [];
  computeAndRenderKPIs(rankedRows, "Completed");
  populateFilterOptions(rankedRows);
  renderCandidateTable();
  renderBatchWarnings(data.errors || []);
  document.getElementById("batchResults").style.display = "block";
  document
    .getElementById("batchResults")
    .scrollIntoView({ behavior: "smooth" });
}

// Non-fatal warnings from the upload (e.g. files skipped inside a ZIP,
// a file that failed to parse) — shown without blocking the results.
function renderBatchWarnings(errors) {
  const meta = document.getElementById("batchUploadMeta");
  if (!meta) return;
  if (!errors.length) return;
  const list = errors.map((e) => `${e.filename}: ${e.error}`).join(" · ");
  meta.innerHTML = `<span style="color:var(--danger);display:block;margin-top:.5rem;">⚠ ${errors.length} note${errors.length === 1 ? "" : "s"} from this scan: ${list}</span>`;
}

function computeAndRenderKPIs(rows, status) {
  const scores = rows.map((r) => Number(r.ai_score || 0));
  const avg = scores.length
    ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10
    : null;
  updateRecruiterStats({
    total: rows.length,
    shortlisted: rows.filter(
      (r) => Number(r.ai_score || 0) >= SHORTLIST_THRESHOLD,
    ).length,
    rejected: rows.filter((r) => Number(r.ai_score || 0) < SHORTLIST_THRESHOLD)
      .length,
    average: avg,
    highest: scores.length ? Math.max(...scores) : null,
    lowest: scores.length ? Math.min(...scores) : null,
    status: status,
  });
}

// ─── Education grouping: model produces Diploma/B.Sc/B.Tech/M.Tech/MBA/M.Sc/PhD.
// UI groups these into Any/Bachelor/Master/PhD per the brief's simpler filter. ──
function eduGroup(edu) {
  if (!edu) return "Other";
  if (edu === "PhD") return "PhD";
  if (["M.Tech", "MBA", "M.Sc"].includes(edu)) return "Master";
  if (["B.Tech", "B.Sc"].includes(edu)) return "Bachelor";
  return "Other";
}

function populateFilterOptions(rows) {
  const catSel = document.getElementById("filterCategory");
  if (catSel) {
    const cats = Array.from(
      new Set(rows.map((r) => r.predicted_category).filter(Boolean)),
    ).sort();
    catSel.innerHTML =
      `<option value="any">All categories</option>` +
      cats.map((c) => `<option value="${c}">${c}</option>`).join("");
  }
}

function getFilteredSortedRows() {
  if (!batchCache) return [];
  let rows = batchCache.filter((r) => {
    if (Number(r.ai_score || 0) < tableState.minScore) return false;
    if (tableState.expFilter !== "any") {
      const min = parseInt(tableState.expFilter, 10);
      if (Number(r.exp || 0) < min) return false;
    }
    if (
      tableState.eduFilter !== "any" &&
      eduGroup(r.education) !== tableState.eduFilter
    )
      return false;
    if (
      tableState.catFilter !== "any" &&
      r.predicted_category !== tableState.catFilter
    )
      return false;
    if (tableState.search) {
      const q = tableState.search.toLowerCase();
      const hay =
        `${r.filename} ${r.predicted_category || ""} ${(r.found_skills || []).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  rows.sort((a, b) => {
    const k = tableState.sortKey;
    let av = a[k],
      bv = b[k];
    if (k === "match_pct") {
      av = a.match_pct ?? a.ai_score;
      bv = b.match_pct ?? b.ai_score;
    }
    if (typeof av === "string") {
      av = av.toLowerCase();
      bv = (bv || "").toLowerCase();
    }
    if (av < bv) return tableState.sortDir === "asc" ? -1 : 1;
    if (av > bv) return tableState.sortDir === "asc" ? 1 : -1;
    return 0;
  });
  return rows;
}

function setSort(key) {
  if (tableState.sortKey === key) {
    tableState.sortDir = tableState.sortDir === "asc" ? "desc" : "asc";
  } else {
    tableState.sortKey = key;
    tableState.sortDir = "asc";
  }
  renderCandidateTable();
}

function setTableSearch(val) {
  tableState.search = val;
  tableState.page = 1;
  renderCandidateTable();
}

function setTableFilter(kind, val) {
  if (kind === "minScore") {
    tableState.minScore = Number(val);
    SHORTLIST_THRESHOLD = Number(val); // Add this line so the badges update!
  }
  if (kind === "exp") tableState.expFilter = val;
  if (kind === "edu") tableState.eduFilter = val;
  if (kind === "cat") tableState.catFilter = val;
  tableState.page = 1;
  renderCandidateTable();
}

function changeTablePage(delta) {
  tableState.page = Math.max(1, tableState.page + delta);
  renderCandidateTable();
}

function toggleColumn(col, checked) {
  visibleCols[col] = checked;
  renderCandidateTable();
}

const COL_DEFS = [
  { key: "rank", label: "Rank" },
  { key: "candidate_id", label: "ID" },
  { key: "filename", label: "Resume File" },
  { key: "ai_score", label: "AI Score" },
  { key: "match_pct", label: "Match %" },
  { key: "predicted_category", label: "Category" },
  { key: "exp", label: "Experience" },
  { key: "education", label: "Education" },
  { key: "skills", label: "Top Skills" },
  { key: "status", label: "Status" },
];

function renderCandidateTable() {
  if (!batchCache) return;
  const filtered = getFilteredSortedRows();
  const totalPages = Math.max(
    1,
    Math.ceil(filtered.length / tableState.perPage),
  );
  tableState.page = Math.min(tableState.page, totalPages);
  const start = (tableState.page - 1) * tableState.perPage;
  const pageRows = filtered.slice(start, start + tableState.perPage);

  // header
  const theadRow = document.getElementById("candTableHeadRow");
  if (theadRow) {
    theadRow.innerHTML = COL_DEFS.filter((c) => visibleCols[c.key])
      .map((c) => {
        const arrow =
          tableState.sortKey === c.key
            ? tableState.sortDir === "asc"
              ? " ▲"
              : " ▼"
            : "";
        const sortable = !["skills", "status"].includes(c.key);
        return `<th ${sortable ? `style="cursor:pointer" onclick="setSort('${c.key === "match_pct" ? "match_pct" : c.key}')"` : ""}>${c.label}${arrow}</th>`;
      })
      .join("");
  }

  const tbody = document.getElementById("rankTableBody");
  if (pageRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10"><div class="empty-state"><div class="empty-state-icon">🔍</div><div class="empty-state-title">No candidates match these filters</div><div class="empty-state-sub">Try lowering the score threshold or clearing filters.</div></div></td></tr>`;
  } else {
    tbody.innerHTML = pageRows
      .map((r) => {
        const shortlisted = Number(r.ai_score || 0) >= SHORTLIST_THRESHOLD;
        const cells = {
          rank: `<td><span class="rank-num">#${r.rank}</span></td>`,
          candidate_id: `<td style="font-size:.78rem;color:var(--muted-fg)">#${r.candidate_id ?? "—"}</td>`,
          filename: `<td style="font-weight:500;font-size:.82rem">${r.filename}</td>`,
          ai_score: `<td><span class="score-badge" style="background:rgba(139,92,246,.1);color:var(--accent);border-color:rgba(139,92,246,.3)">${r.ai_score}</span></td>`,
          match_pct: `<td style="font-size:.82rem;font-weight:600">${r.match_pct ?? r.ai_score}%</td>`,
          predicted_category: `<td style="font-size:.78rem;color:var(--muted-fg)">${r.predicted_category || "—"}</td>`,
          exp: `<td style="font-size:.82rem;font-weight:600">${r.exp}y</td>`,
          education: `<td style="font-size:.82rem;color:var(--muted-fg)">${r.education || "—"}</td>`,
          skills: `<td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted-fg);font-size:.75rem">${(r.found_skills || []).slice(0, 4).join(", ")}</td>`,
          status: `<td><span class="score-badge" style="font-size:.7rem;background:${shortlisted ? "rgba(110,231,183,.15)" : "rgba(248,113,113,.12)"};color:${shortlisted ? "#10895c" : "#dc4747"};border-color:${shortlisted ? "rgba(110,231,183,.4)" : "rgba(248,113,113,.35)"}">${shortlisted ? "Shortlisted" : "Rejected"}</span></td>`,
        };
        const tds = COL_DEFS.filter((c) => visibleCols[c.key])
          .map((c) => cells[c.key])
          .join("");
        return `<tr class="cand-row" tabindex="0" role="button" aria-label="View ${r.filename} details" onclick="openCandidateDrawer(${r.candidate_id})" onkeydown="if(event.key==='Enter')openCandidateDrawer(${r.candidate_id})">${tds}</tr>`;
      })
      .join("");
  }

  const pagerInfo = document.getElementById("tablePagerInfo");
  if (pagerInfo)
    pagerInfo.textContent = filtered.length
      ? `${start + 1}-${Math.min(start + tableState.perPage, filtered.length)} of ${filtered.length}`
      : "0 of 0";
  const prevBtn = document.getElementById("tablePagerPrev");
  const nextBtn = document.getElementById("tablePagerNext");
  if (prevBtn) prevBtn.disabled = tableState.page <= 1;
  if (nextBtn) nextBtn.disabled = tableState.page >= totalPages;

  renderBatchBarChart(filtered);
  renderAIInsights(filtered);
}

function renderBatchBarChart(ranked) {
  const canvas = document.getElementById("batchBarChart");
  if (!canvas) return;
  if (batchBarInst) batchBarInst.destroy();
  const top = ranked.slice(0, 25); // keep the bar chart readable
  const cols = top.map((r) =>
    r.ai_score >= 85
      ? "#34D399"
      : r.ai_score >= 70
        ? "#60A5FA"
        : r.ai_score >= 50
          ? "#F472B6"
          : "#FCA5A5",
  );
  const style = getComputedStyle(document.documentElement);
  const fgColor = style.getPropertyValue("--fg").trim() || "#1E293B";
  const mutedColor = style.getPropertyValue("--muted-fg").trim() || "#64748B";
  const borderColor = style.getPropertyValue("--border").trim() || "#E2E8F0";
  batchBarInst = new Chart(canvas, {
    type: "bar",
    data: {
      labels: top.map((r) => r.filename.replace(/\.[^.]+$/, "")),
      datasets: [
        {
          label: "Score",
          data: top.map((r) => r.ai_score),
          backgroundColor: cols,
          borderRadius: 8,
          borderSkipped: false,
        },
      ],
    },
    options: {
      indexAxis: "y",
      scales: {
        x: {
          min: 0,
          max: 100,
          grid: { color: borderColor },
          ticks: { color: mutedColor },
        },
        y: {
          grid: { display: false },
          ticks: { color: "var(--fg)", font: { size: 11, weight: "600" } },
        },
      },
      plugins: { legend: { display: false } },
      animation: { duration: 600 },
    },
  });
}

// ═══════════════════════════════════════════════════════════════════════
// AI INSIGHTS — derived from real predicted_category counts + a threshold
// recommendation computed from the actual score distribution in view.
// No numbers are invented; everything traces back to batchCache.
// ═══════════════════════════════════════════════════════════════════════
function renderAIInsights(filteredRows) {
  const wrap = document.getElementById("aiInsightsWrap");
  if (!wrap || !batchCache) return;
  const rows = batchCache;
  const catCounts = {};
  rows.forEach((r) => {
    const c = r.predicted_category || "Unclassified";
    catCounts[c] = (catCounts[c] || 0) + 1;
  });
  const sortedCats = Object.entries(catCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);

  // Threshold recommendation: find the highest threshold (multiple of 5) that
  // still keeps at least ~30% of candidates, capped between 50-90.
  const scores = rows.map((r) => Number(r.ai_score || 0)).sort((a, b) => b - a);
  let recommendedThreshold = 50;
  let keptAtRecommended = rows.length;
  for (let t = 90; t >= 50; t -= 5) {
    const kept = scores.filter((s) => s >= t).length;
    if (kept >= Math.max(1, Math.round(rows.length * 0.25))) {
      recommendedThreshold = t;
      keptAtRecommended = kept;
      break;
    }
  }

  wrap.innerHTML = `
          <div style="display:flex; flex-direction:column; gap:.6rem; margin-bottom:1rem;">
            ${sortedCats
              .map(
                ([cat, count]) => `
              <div style="display:flex; align-items:center; gap:.6rem; font-size:.85rem;">
                <span style="width:8px;height:8px;border-radius:50%;background:var(--accent);flex-shrink:0;"></span>
                <span><strong>${count}</strong> candidate${count === 1 ? "" : "s"} match <strong>${cat}</strong> profile</span>
              </div>`,
              )
              .join("")}
          </div>
          <div style="background:var(--muted); border:2px solid var(--border); border-radius:var(--radius-md); padding:1rem;">
            <div style="font-weight:700; font-size:.85rem; margin-bottom:.3rem;">💡 Recommended threshold: ${recommendedThreshold}</div>
            <div style="font-size:.78rem; color:var(--muted-fg);">Keeps ${keptAtRecommended} of ${rows.length} candidates (${Math.round((keptAtRecommended / rows.length) * 100)}%) while filtering out the lowest-fit resumes.</div>
            <button class="btn btn-outline btn-sm" style="margin-top:.7rem" onclick="applyRecommendedThreshold(${recommendedThreshold})">Apply this threshold</button>
          </div>`;
}

function applyRecommendedThreshold(t) {
  tableState.minScore = t;
  const slider = document.getElementById("filterMinScore");
  const label = document.getElementById("filterMinScoreLabel");
  if (slider) slider.value = t;
  if (label) label.textContent = t;
  tableState.page = 1;
  renderCandidateTable();
  toast(`Threshold set to ${t}`, "success");
}

// ═══════════════════════════════════════════════════════════════════════
// ANALYTICS SECTION — backed by /api/analytics/batch/<id>
// ═══════════════════════════════════════════════════════════════════════
async function loadBatchAnalytics(batchRunId) {
  const wrap = document.getElementById("analyticsChartsWrap");
  if (wrap)
    wrap.innerHTML =
      `<div class="skeleton skeleton-card" style="height:280px"></div>`.repeat(
        2,
      );
  try {
    // ✅ FIX: Added credentials: 'include'
    const res = await fetch(`/api/analytics/batch/${batchRunId}`, {
        method: 'GET',
        credentials: 'include'
    });
    
    await requireLoggedIn(res);
    const data = await res.json();
    if (!data.success)
      throw new Error(data.error || "Failed to load analytics");
    renderAnalyticsCharts(data);
  } catch (e) {
    if (wrap)
      wrap.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📉</div><div class="empty-state-title">Analytics unavailable</div><div class="empty-state-sub">${e.message}</div></div>`;
  }
}

function ensureAnalyticsCanvases() {
  const wrap = document.getElementById("analyticsChartsWrap");
  if (!wrap) return;
  wrap.innerHTML = `
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">AI Score Distribution</div><canvas id="chartScoreDist" style="max-height:240px"></canvas></div>
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">Shortlisted vs Rejected</div><canvas id="chartTierBreakdown" style="max-height:240px"></canvas></div>
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">Category Distribution</div><canvas id="chartCategoryDist" style="max-height:240px"></canvas></div>
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">Top Skills Frequency</div><canvas id="chartTopSkills" style="max-height:240px"></canvas></div>
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">Experience Distribution</div><canvas id="chartExpDist" style="max-height:240px"></canvas></div>
          <div class="chart-card"><div class="card-title" style="margin-bottom:.75rem">Education Distribution</div><canvas id="chartEduDist" style="max-height:240px"></canvas></div>`;
}

function destroyAnalyticsCharts() {
  Object.values(analyticsCharts).forEach((c) => c && c.destroy());
  analyticsCharts = {};
}

function renderAnalyticsCharts(data) {
  destroyAnalyticsCharts();
  ensureAnalyticsCanvases();
  const palette = [
    "#8B5CF6",
    "#F9A8D4",
    "#FCD34D",
    "#6EE7B7",
    "#60A5FA",
    "#FCA5A5",
    "#A78BFA",
    "#34D399",
  ];

  // 1. Score distribution (histogram via bar)
  const scoreDist = data.score_distribution || {};
  analyticsCharts.scoreDist = new Chart(
    document.getElementById("chartScoreDist"),
    {
      type: "bar",
      data: {
        labels: Object.keys(scoreDist),
        datasets: [
          {
            label: "Candidates",
            data: Object.values(scoreDist),
            backgroundColor: "#8B5CF6",
            borderRadius: 6,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    },
  );

  // 2. Tier breakdown (shortlisted vs rejected, derived from tier_breakdown)
  const tb = data.tier_breakdown || {};
  const shortlistedCount = (tb.excellent || 0) + (tb.good || 0);
  const rejectedCount = (tb.average || 0) + (tb.rejected || 0);
  analyticsCharts.tierBreakdown = new Chart(
    document.getElementById("chartTierBreakdown"),
    {
      type: "bar",
      data: {
        labels: ["Shortlisted", "Rejected"],
        datasets: [
          {
            data: [shortlistedCount, rejectedCount],
            backgroundColor: ["#6EE7B7", "#FCA5A5"],
            borderRadius: 8,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    },
  );

  // 3. Category distribution (pie)
  const catDist = data.predicted_category_distribution || {};
  analyticsCharts.categoryDist = new Chart(
    document.getElementById("chartCategoryDist"),
    {
      type: "pie",
      data: {
        labels: Object.keys(catDist),
        datasets: [{ data: Object.values(catDist), backgroundColor: palette }],
      },
      options: {
        plugins: {
          legend: {
            position: "bottom",
            labels: { boxWidth: 10, font: { size: 10 } },
          },
        },
      },
    },
  );

  // 4. Top skills frequency (bar)
  const topTech = (data.top_technologies || []).slice(0, 10);
  analyticsCharts.topSkills = new Chart(
    document.getElementById("chartTopSkills"),
    {
      type: "bar",
      data: {
        labels: topTech.map((t) => t.skill),
        datasets: [
          {
            label: "Mentions",
            data: topTech.map((t) => t.count),
            backgroundColor: "#60A5FA",
            borderRadius: 6,
          },
        ],
      },
      options: {
        indexAxis: "y",
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    },
  );

  // 5. Experience distribution (bar)
  const expDist = data.experience_distribution || {};
  analyticsCharts.expDist = new Chart(document.getElementById("chartExpDist"), {
    type: "bar",
    data: {
      labels: Object.keys(expDist),
      datasets: [
        {
          label: "Candidates",
          data: Object.values(expDist),
          backgroundColor: "#FCD34D",
          borderRadius: 6,
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });

  // 6. Education distribution (bar)
  const eduDist = data.education_distribution || {};
  analyticsCharts.eduDist = new Chart(document.getElementById("chartEduDist"), {
    type: "bar",
    data: {
      labels: Object.keys(eduDist),
      datasets: [
        {
          label: "Candidates",
          data: Object.values(eduDist),
          backgroundColor: "#F9A8D4",
          borderRadius: 6,
        },
      ],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

// ═══════════════════════════════════════════════════════════════════════
// CANDIDATE DETAILS DRAWER — backed by /api/resume-summary/<id>
// ═══════════════════════════════════════════════════════════════════════
// ─── CANDIDATE DRAWER LOGIC ──────────────────────────────────────────────
let drawerRadarInst = null;

window.openCandidateDrawer = function (candidateId) {
  const overlay = document.getElementById("candDrawerOverlay");
  const panel = document.getElementById("candDrawerContent");
  if (!overlay || !panel) return;

  // 1. Find the candidate in our current batch memory
  const candidate = batchCache.find(
    (c) => c.candidate_id == candidateId || c.filename == candidateId,
  );
  if (!candidate) {
    toast("Candidate data not found.", "error");
    return;
  }

  // 2. Open overlay
  overlay.classList.add("open");
  document.body.style.overflow = "hidden";

  // 3. Inject the HTML structure dynamically
  const recColor =
    candidate.ai_score >= 70
      ? "#10895c"
      : candidate.ai_score >= 50
        ? "#b8860b"
        : "#dc4747";
  const recText =
    candidate.ai_score >= 70
      ? "Shortlist"
      : candidate.ai_score >= 50
        ? "Hold"
        : "Reject";
  const skillsHtml = (candidate.found_skills || [])
    .slice(0, 12)
    .map(
      (s) =>
        `<span class="badge" style="background:var(--muted); color:var(--fg); padding:4px 8px; border-radius:4px; font-size:0.75rem; margin-right:4px; margin-bottom:4px; display:inline-block;">${s}</span>`,
    )
    .join("");

  panel.innerHTML = `
        <div style="padding:1.5rem; display:flex; flex-direction:column; gap:1.1rem;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <div>
                    <div style="font-family:'Outfit',system-ui; font-weight:800; font-size:1.15rem;">${candidate.filename.replace(/\.[^.]+$/, "")}</div>
                    <div style="color:var(--muted-fg); font-size:.82rem; margin-top:.2rem;">${candidate.predicted_category || "Unclassified"}</div>
                </div>
                <button onclick="closeCandidateDrawer()" aria-label="Close" style="background:none;border:2px solid var(--border-dark);border-radius:8px;width:32px;height:32px;cursor:pointer;font-size:1rem;">✕</button>
            </div>

            <div style="display:flex; gap:.75rem;">
                <div style="flex:1;background:var(--muted);border-radius:var(--radius-md);padding:.85rem;text-align:center;">
                    <div style="font-family:'Outfit';font-weight:800;font-size:1.4rem;color:var(--accent)">${candidate.ai_score}%</div>
                    <div style="font-size:.7rem;color:var(--muted-fg);">AI Score</div>
                </div>
                <div style="flex:1;background:var(--muted);border-radius:var(--radius-md);padding:.85rem;text-align:center;">
                    <div style="font-family:'Outfit';font-weight:800;font-size:1rem;color:${recColor}">${recText}</div>
                    <div style="font-size:.7rem;color:var(--muted-fg);">Recommendation</div>
                </div>
            </div>

            <div>
                <div style="font-weight:700;font-size:.82rem;margin-bottom:.4rem;">Experience &amp; Education</div>
                <div style="font-size:.82rem;color:var(--muted-fg);line-height:1.6;">${candidate.exp} Years<br/>${candidate.education || "Not specified"}</div>
            </div>

            <div>
                <div style="font-weight:700;font-size:.82rem;margin-bottom:.4rem;">Top Skills</div>
                <div>${skillsHtml || "<span style='color:var(--muted-fg);font-size:0.8rem;'>No skills detected</span>"}</div>
            </div>
            
            <div>
                <div style="font-weight:700;font-size:.82rem;margin-bottom:.4rem;">Profile Radar</div>
                <div style="background:var(--muted); border-radius:var(--radius-md); padding:1rem; height: 250px;">
                    <canvas id="drawerRadarChart"></canvas>
                </div>
            </div>
            
            <div style="font-size:.72rem;color:var(--muted-fg);text-align:center;padding-top:.5rem;border-top:1px solid var(--border);">
              Original resume preview is not available in batch mode.
            </div>
        </div>
    `;

  // 4. Render the Radar Chart into the newly created canvas
  setTimeout(() => {
    renderDrawerRadar(candidate.section_scores);
  }, 50);
};

window.closeCandidateDrawer = function () {
  const overlay = document.getElementById("candDrawerOverlay");
  if (overlay) {
    overlay.classList.remove("open");
    document.body.style.overflow = "";
  }
};

function renderDrawerRadar(scores) {
  const canvas = document.getElementById("drawerRadarChart");
  if (!canvas || !scores) return;
  if (drawerRadarInst) drawerRadarInst.destroy();

  const style = getComputedStyle(document.documentElement);
  const fgColor = style.getPropertyValue("--fg").trim() || "#1E293B";
  const borderColor = style.getPropertyValue("--border").trim() || "#E2E8F0";
  const accentColor = style.getPropertyValue("--accent").trim() || "#8B5CF6";

  const labels = [
    "Skills",
    "Experience",
    "Education",
    "Projects",
    "ATS Match",
    "Certifications",
  ];
  const dataPts = [
    scores["Skills"] || 0,
    scores["Experience"] || 0,
    scores["Education"] || 0,
    scores["Projects"] || 0,
    scores["ATS Match"] || 0,
    scores["Certifications"] || 0,
  ];

  drawerRadarInst = new Chart(canvas, {
    type: "radar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Profile Strength",
          data: dataPts,
          backgroundColor: "rgba(139, 92, 246, 0.2)",
          borderColor: accentColor,
          pointBackgroundColor: accentColor,
          pointBorderColor: "#fff",
          borderWidth: 2,
        },
      ],
    },
    options: {
      scales: {
        r: {
          min: 0,
          max: 100,
          grid: { color: borderColor },
          angleLines: { color: borderColor },
          pointLabels: { color: fgColor, font: { size: 10, weight: "600" } },
          ticks: { display: false },
        },
      },
      plugins: { legend: { display: false } },
      maintainAspectRatio: false,
    },
  });
}

// close drawer on Escape or backdrop click
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeCandidateDrawer();
});

// ═══════════════════════════════════════════════════════════════════════
// EXPORTS — CSV (existing) + Excel (new, client-side, SheetJS-free CSV-as-xls
// fallback isn't used; we build true XLSX via a tiny hand-rolled writer is
// overkill for a chat artifact, so Excel export uses a CSV with .xls-friendly
// formatting Excel opens natively). PDF batch report intentionally NOT
// included — no backend route exists for it yet.
// ═══════════════════════════════════════════════════════════════════════
function exportCSV() {
  if (!batchCache) return;
  const rows = getFilteredSortedRows();
  const header = [
    "Rank",
    "Candidate ID",
    "Filename",
    "AI Score",
    "Match %",
    "Predicted Category",
    "Experience",
    "Education",
    "Top Skills",
    "Status",
  ];
  const body = rows.map((r) => [
    r.rank,
    r.candidate_id,
    r.filename,
    r.ai_score,
    r.match_pct ?? r.ai_score,
    r.predicted_category,
    r.exp,
    r.education,
    (r.found_skills || []).join("; "),
    Number(r.ai_score || 0) >= SHORTLIST_THRESHOLD ? "Shortlisted" : "Rejected",
  ]);
  downloadDelimited([header, ...body], "candidate_ranking.csv", ",");
  toast("CSV exported ✓");
}

function exportExcel() {
  if (!batchCache) return;
  const rows = getFilteredSortedRows();
  const header = [
    "Rank",
    "Candidate ID",
    "Filename",
    "AI Score",
    "Match %",
    "Predicted Category",
    "Experience",
    "Education",
    "Top Skills",
    "Status",
  ];
  const body = rows.map((r) => [
    r.rank,
    r.candidate_id,
    r.filename,
    r.ai_score,
    r.match_pct ?? r.ai_score,
    r.predicted_category,
    r.exp,
    r.education,
    (r.found_skills || []).join("; "),
    Number(r.ai_score || 0) >= SHORTLIST_THRESHOLD ? "Shortlisted" : "Rejected",
  ]);
  // Tab-separated .xls is opened natively by Excel without needing a binary XLSX writer.
  downloadDelimited([header, ...body], "candidate_ranking.xls", "\t");
  toast("Excel file exported ✓");
}

function downloadDelimited(rows, filename, delim) {
  const esc = (v) => {
    const s = String(v ?? "");
    return delim === "," && /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = rows.map((r) => r.map(esc).join(delim)).join("\n");
  const mime = filename.endsWith(".xls")
    ? "application/vnd.ms-excel"
    : "text/csv";
  const blob = new Blob(["\ufeff" + text], { type: mime + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Full PDF batch report — summary + analytics + selected/rejected
// lists, generated server-side from /api/analytics/batch/<id>/export-pdf.
// Uses the same threshold currently applied in Screening Configuration so
// the PDF always matches what's on screen.
async function exportPDFReport() {
  if (!currentBatchRunId) {
    toast("Run a batch scan first", "error");
    return;
  }
  toast("Generating PDF report…");
  try {
    const threshold =
      tableState.minScore > 0 ? tableState.minScore : SHORTLIST_THRESHOLD;
    const res = await fetch(
      `/api/analytics/batch/${currentBatchRunId}/export-pdf?threshold=${threshold}`,
    );
    await requireLoggedIn(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || "Failed to generate PDF");
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `batch_${currentBatchRunId}_report.pdf`;
    a.click();
    URL.revokeObjectURL(url);
    toast("PDF report downloaded ✓", "success");
  } catch (e) {
    toast("Error: " + e.message, "error");
  }
}

// ─── Authentication Logic ──────────────────────────────────────────────────
let isSignUpMode = false;

document.addEventListener("DOMContentLoaded", () => {
  initSession();
});

async function initSession() {
  try {
    const res = await fetch("/api/me");
    const data = await res.json();
    if (!res.ok || !data.authenticated) throw new Error("Not signed in");
    localStorage.setItem("resumeai_role", data.role);
    document.getElementById("roleGateway").classList.remove("active");
    document.getElementById("sessionStatus").textContent =
      data.role === "recruiter" ? "Recruiter" : "Candidate";
    document.getElementById("logoutBtn").style.display = "inline-flex";
    applyRoleUI(data.role);
  } catch (e) {
    localStorage.removeItem("resumeai_role");
    document.getElementById("sessionStatus").textContent = "Offline";
    document.getElementById("logoutBtn").style.display = "none";
    document.getElementById("roleGateway").classList.add("active");
  }
}

async function requireLoggedIn(response) {
  if (response.status !== 401) return;
  localStorage.removeItem("resumeai_role");
  document.getElementById("sessionStatus").textContent = "Offline";
  document.getElementById("logoutBtn").style.display = "none";
  document.getElementById("roleGateway").classList.add("active");
  throw new Error("Please log in first.");
}

function toggleAuthMode() {
  isSignUpMode = !isSignUpMode;
  document.getElementById("authSubtitle").textContent = isSignUpMode
    ? "Create your workspace"
    : "Sign in to your workspace";
  document.getElementById("authBtn").textContent = isSignUpMode
    ? "Create Account"
    : "Login";
  document.getElementById("authToggleText").textContent = isSignUpMode
    ? "Already have an account?"
    : "Need an account?";
  document.getElementById("authToggleBtn").textContent = isSignUpMode
    ? "Login"
    : "Sign Up";
  document.getElementById("roleSelectBlock").style.display = isSignUpMode
    ? "block"
    : "none";
}

async function handleAuth() {
  const email = document.getElementById("authEmail").value.trim();
  const password = document.getElementById("authPassword").value;
  const role = document.getElementById("authRole").value;

  if (!email || !password) {
    toast("Please enter email and password", "error");
    return;
  }

  const endpoint = isSignUpMode ? "/api/signup" : "/api/login";
  const payload = isSignUpMode
    ? { email, password, role }
    : { email, password };

  document.getElementById("authBtn").disabled = true;
  document.getElementById("authBtn").textContent = "Processing...";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: 'include'
    });
    const data = await res.json();

    if (!res.ok || !data.success)
      throw new Error(data.error || "Authentication failed");

    localStorage.setItem("resumeai_role", data.role);
    document.getElementById("roleGateway").classList.remove("active");
    document.getElementById("sessionStatus").textContent =
      data.role === "recruiter" ? "Recruiter" : "Candidate";
    document.getElementById("logoutBtn").style.display = "inline-flex";
    applyRoleUI(data.role);
    toast("Welcome to ResumeAI ✓", "success");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    document.getElementById("authBtn").disabled = false;
    document.getElementById("authBtn").textContent = isSignUpMode
      ? "Create Account"
      : "Login";
  }
}

async function logoutUser() {
  await fetch("/api/logout", { method: "POST" });
  localStorage.removeItem("resumeai_role");
  document.getElementById("sessionStatus").textContent = "Offline";
  document.getElementById("logoutBtn").style.display = "none";
  location.reload();
}

function applyRoleUI(role) {
  const dashboardNavBtn = document.querySelector(
    '.nav-tab[data-nav="dashboard"]',
  );
  document.body.classList.remove("role-candidate", "role-recruiter");
  document.body.classList.add(
    role === "recruiter" ? "role-recruiter" : "role-candidate",
  );

  // recruiter-only nav items (Candidates, Analytics) + in-page recruiter features
  document.querySelectorAll(".recruiter-only-feat").forEach((el) => {
    el.style.display =
      role === "recruiter"
        ? el.classList.contains("nav-tab")
          ? "inline-flex"
          : "flex"
        : "none";
  });

  if (role === "candidate") {
    navigateTo("dashboard", dashboardNavBtn);
  } else if (role === "recruiter") {
    navigateTo("dashboard", dashboardNavBtn);
  }
}

// Quick developer tool: Call this in console to reset role `resetRole()`
function resetRole() {
  localStorage.removeItem("resumeai_role");
  location.reload();
}

// ─── History Database Logic ──────────────────────────────────────────────
async function loadHistory() {
  const tbody = document.getElementById("historyTableBody");
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem;"><div class="geo-spinner" style="width:30px;height:30px;margin:0 auto;"></div></td></tr>`;

  try {
    // ✅ FIX: Added credentials: 'include'
    const res = await fetch("/api/history", {
      method: "GET",
      credentials: "include",
    });

    await requireLoggedIn(res);
    const data = await res.json();

    if (!data.success) throw new Error(data.error);

    // ✅ FIX: Safety check
    if (!data.history) {
      data.history = [];
    }

    if (data.history.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--muted-fg);">No database records found. Run a scan first!</td></tr>`;
      return;
    }

    // ... (keep the rest of your tbody.innerHTML = data.history.map(...) code exactly the same)

    tbody.innerHTML = data.history
      .map((row) => {
        // Smart routing: Render differently for Recruiter Batches vs Candidate Scans
        if (row.type === "batch") {
          return `
                <tr>
                  <td style="color:var(--muted-fg); font-size:.75rem;">${row.created_at}</td>
                  <td style="font-weight:700; color:var(--fg);">${row.job_role}</td>
                  <td style="font-size:.8rem;">${row.total_candidates} Candidates</td>
                  <td><span class="score-badge" style="background:rgba(52,211,153,.1);color:#10895c;border-color:rgba(52,211,153,.3)">Avg: ${row.avg_score}</span></td>
                  <td><span class="score-badge" style="background:var(--muted);color:var(--muted-fg);font-size:.72rem">Batch Scan</span></td>
                  <td>
                      <button class="btn btn-outline btn-sm" style="padding:.2rem .6rem; font-size:.7rem;" onclick='viewHistoricBatch(${JSON.stringify(row.details).replace(/'/g, "&apos;")})'>View Batch</button>
                  </td>
                </tr>
              `;
        } else {
          return `
                <tr>
                  <td style="color:var(--muted-fg); font-size:.75rem;">${row.created_at}</td>
                  <td style="font-weight:700; color:var(--fg);">${row.job_role}</td>
                  <td style="font-size:.8rem;">${row.target_company}</td>
                  <td><span class="score-badge" style="background:rgba(139,92,246,.1);color:var(--accent);border-color:rgba(139,92,246,.3)">${row.ai_score}</span></td>
                  <td><span class="score-badge" style="background:var(--muted);color:var(--muted-fg);font-size:.72rem">${row.tier}</span></td>
                  <td>
                      <button class="btn btn-outline btn-sm" style="padding:.2rem .6rem; font-size:.7rem;" onclick='viewHistoricScan(${JSON.stringify(row.details).replace(/'/g, "&apos;")})'>View Report</button>
                  </td>
                </tr>
              `;
        }
      })
      .join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--danger);">Error loading history: ${e.message}</td></tr>`;
    toast("Failed to load history", "error");
  }
}

// Existing Candidate view function
function viewHistoricScan(details) {
  currentData = details;
  renderResults(details);
  navigateTo("dashboard");
  toast("Historic report loaded", "success");
}

// NEW: Recruiter batch view function
function viewHistoricBatch(details) {
  batchCache = details.ranked;
  currentBatchRunId = details.batch_run_id || null;
  tableState.page = 1;
  renderBatch(details);
  navigateTo("dashboard");
  toast("Historic batch loaded", "success");
  if (currentBatchRunId) loadBatchAnalytics(currentBatchRunId);
}

function viewHistoricScan(details) {
  // Populate the global state and push user to the main dashboard
  currentData = details;
  renderResults(details);

  // Safely target the Dashboard nav button
  navigateTo("dashboard");

  toast("Historic report loaded", "success");
}

// ─── Show/Hide Password Toggle ───────────────────────────────────────────
function togglePasswordVisibility() {
  const pwdInput = document.getElementById("authPassword");
  const toggleBtn = document.getElementById("togglePasswordBtn");
  
  if (pwdInput.type === "password") {
    pwdInput.type = "text";
    toggleBtn.textContent = "🙈"; // Hide icon
  } else {
    pwdInput.type = "password";
    toggleBtn.textContent = "👁️"; // Show icon
  }
}
