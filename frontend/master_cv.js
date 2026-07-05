// ── Master CV Builder ─────────────────────────────────────────────────────────
// Provides renderMasterCV() called from dashboard.html handleRouting()

let _cvData = null;

async function renderMasterCV() {
  const view = document.getElementById('appView');
  view.innerHTML = `<div class="slide-in"><div class="text-center py-16"><span class="loader"></span><p class="mt-4 text-xs text-ink-700/60">Loading Master CV…</p></div></div>`;

  try {
    const res = await fetch('/api/user/master-cv');
    const data = await res.json();
    if (data.ok) _cvData = data.cv;
    else { view.innerHTML = `<div class="sm-card p-8 text-rose-700">Error: ${data.error}</div>`; return; }
  } catch (e) { view.innerHTML = `<div class="sm-card p-8 text-rose-700">Failed to load CV: ${e.message}</div>`; return; }

  _renderCVForm();
}

function _renderCVForm() {
  const cv = _cvData;
  const p = cv.personal || {};
  document.getElementById('appView').innerHTML = `
  <div class="slide-in" style="max-width:900px">
    <div class="flex items-end justify-between flex-wrap gap-3 mb-6">
      <div>
        <div class="text-[12px] font-semibold tracking-widest text-brand-700">MASTER CV BUILDER</div>
        <h1 class="font-display text-3xl font-bold mt-1">Your Professional Profile</h1>
        <p class="text-[13px] text-ink-700/70 mt-1">Fill once — powers every application, auto-fill, and tailored resume.</p>
      </div>
      <div class="flex gap-2">
        <button onclick="_parseResumeModal()" class="px-4 py-2 bg-white border border-brand-200 text-brand-700 text-xs font-bold rounded-xl hover:bg-brand-50 transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          Import from Resume
        </button>
        <button onclick="_saveMasterCV()" id="cvSaveBtn" class="px-5 py-2 bg-ink-900 text-white text-xs font-bold rounded-xl hover:bg-brand-700 transition">Save CV</button>
      </div>
    </div>
    <div id="cvSaveStatus" class="text-xs font-semibold mb-4 hidden"></div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 overflow-x-auto pb-1" id="cvTabs"></div>

    <div id="cvTabContent" class="sm-card p-6"></div>
  </div>`;

  // Attach dynamic input event listener to validate form on-the-fly
  const container = document.getElementById('appView');
  container.addEventListener('input', (e) => {
    if (e.target.classList.contains('cv-input') || e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      _readCurrentTab();
      _updateWizardButtons();
    }
  });

  _switchCVTab(0);
}

let _currentCVTab = 0;

function _isTabValid(idx) {
  if (!_cvData) return false;
  if (idx === 0) { // Personal
    const p = _cvData.personal || {};
    return !!(
      (p.name || '').trim() &&
      (p.last_name || '').trim() &&
      (p.email || '').trim() &&
      (p.phone || '').trim() &&
      (p.linkedin_url || '').trim() &&
      (p.summary || '').trim()
    );
  }
  if (idx === 1) { // Education
    const items = _cvData.education || [];
    if (items.length === 0) return false;
    return items.every(item =>
      (item.degree || '').trim() &&
      (item.field_of_study || '').trim() &&
      (item.institute || '').trim() &&
      (item.gpa_or_percentage || '').trim() &&
      (item.start_year || '').trim() &&
      (item.end_year || '').trim()
    );
  }
  if (idx === 2) { // Experience
    const items = _cvData.experience || [];
    return items.every(item =>
      (item.company || '').trim() &&
      (item.role || '').trim() &&
      (item.start_date || '').trim() &&
      (item.end_date || '').trim() &&
      item.responsibilities &&
      item.responsibilities.length > 0 &&
      item.responsibilities.every(b => b.trim())
    );
  }
  if (idx === 3) { // Internships
    const items = _cvData.internships || [];
    return items.every(item =>
      (item.company || '').trim() &&
      (item.role || '').trim() &&
      (item.start_date || '').trim() &&
      (item.end_date || '').trim() &&
      item.responsibilities &&
      item.responsibilities.length > 0 &&
      item.responsibilities.every(b => b.trim())
    );
  }
  if (idx === 4) { // Coursework
    const items = _cvData.coursework || [];
    return items.length > 0;
  }
  if (idx === 5) { // POR
    const items = _cvData.positions_of_responsibility || [];
    return items.every(item =>
      (item.title || '').trim() &&
      (item.organization || '').trim() &&
      (item.start_date || '').trim() &&
      (item.end_date || '').trim() &&
      item.bullets &&
      item.bullets.length > 0 &&
      item.bullets.every(b => b.trim())
    );
  }
  if (idx === 6) { // Certifications
    const items = _cvData.certifications || [];
    return items.every(item =>
      (item.title || '').trim() &&
      (item.issuer || '').trim() &&
      (item.date || '').trim() &&
      (item.description || '').trim()
    );
  }
  if (idx === 7) { // Hobbies
    const items = _cvData.hobbies || [];
    return items.length > 0;
  }
  return true;
}

function _canAccessTab(idx) {
  return true;
}

function _renderTabHeaders() {
  const tabsList = ['Personal','Education','Experience','Internships','Coursework','POR','Certifications','Hobbies','Generate Resume'];
  const tabsContainer = document.getElementById('cvTabs');
  if (!tabsContainer) return;

  tabsContainer.innerHTML = tabsList.map((t, i) => {
    const isActive = i === _currentCVTab;
    
    if (isActive) {
      return `<button class="cv-tab px-3 py-1.5 rounded-lg text-[12px] font-semibold whitespace-nowrap transition bg-ink-900 text-white" disabled>${t}</button>`;
    } else {
      return `<button onclick="_switchCVTab(${i})" class="cv-tab px-3 py-1.5 rounded-lg text-[12px] font-semibold whitespace-nowrap transition bg-ink-900/5 text-ink-700 hover:bg-ink-900/10">${t}</button>`;
    }
  }).join('');
}

function _switchCVTab(idx) {
  _currentCVTab = idx;
  
  _renderTabHeaders();

  const el = document.getElementById('cvTabContent');
  const tabs = [
    _renderPersonal,
    _renderEducation,
    _renderExperience,
    _renderInternships,
    _renderCoursework,
    _renderPOR,
    _renderCertifications,
    _renderHobbies,
    _renderGenerateResume
  ];
  
  tabs[idx](el);
  _appendWizardFooter(el, idx);
}

function _appendWizardFooter(el, idx) {
  const isFirst = idx === 0;
  const isLast = idx === 8;

  let footerHtml = `<div class="flex justify-between items-center mt-6 pt-4 border-t border-ink-900/5">`;

  if (!isFirst) {
    footerHtml += `<button onclick="_prevCVTab()" class="px-4 py-2 bg-ink-900/5 text-ink-700 text-xs font-bold rounded-xl hover:bg-ink-900/10 transition">Back</button>`;
  } else {
    footerHtml += `<div></div>`;
  }

  if (!isLast) {
    footerHtml += `
      <div class="flex items-center gap-3">
        <button onclick="_nextCVTab()" id="cvNextBtn" class="px-5 py-2 bg-ink-900 text-white text-xs font-bold rounded-xl hover:bg-brand-700 transition">
          Next
        </button>
      </div>`;
  } else {
    footerHtml += `<div></div>`;
  }

  footerHtml += `</div>`;
  el.insertAdjacentHTML('beforeend', footerHtml);
}

function _nextCVTab() {
  _readCurrentTab();
  _saveMasterCVQuietly();
  _switchCVTab(_currentCVTab + 1);
}

function _prevCVTab() {
  _readCurrentTab();
  _switchCVTab(_currentCVTab - 1);
}

function _updateWizardButtons() {
  _renderTabHeaders();
}

async function _saveMasterCVQuietly() {
  try {
    await fetch('/api/user/master-cv', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cv: _cvData})
    });
  } catch (e) {
    console.error('[Quiet Save] failed:', e);
  }
}

function _renderGenerateResume(el) {
  const headline = (_cvData.personal || {}).headline || '';
  el.innerHTML = `
    <div class="text-center py-6 border-b border-ink-900/5 mb-6">
      <div class="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-3">
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <h3 class="font-display font-bold text-lg text-ink-900">Your Master CV is Complete!</h3>
      <p class="text-[12px] text-ink-700/60 mt-1">All sections have been successfully filled out. You are now ready to generate tailored resumes.</p>
    </div>

    <!-- AI Headline Container -->
    <div class="mb-6 p-4 bg-brand-50/50 border border-brand-100 rounded-xl text-left">
      <div class="flex justify-between items-center mb-2 gap-3 flex-wrap">
        <div>
          <h4 class="text-xs font-bold text-brand-800 uppercase tracking-wide">AI-Generated Professional Headline</h4>
          <p class="text-[11px] text-ink-700/60 mt-0.5">Auto-generated summary based on your details (max 50-75 words).</p>
        </div>
        <button onclick="_generateHeadline()" id="cvGenHeadlineBtn" class="px-3 py-1.5 bg-white border border-brand-200 text-brand-700 text-[11px] font-bold rounded-lg hover:bg-brand-50 transition shrink-0">
          Regenerate
        </button>
      </div>
      <div id="cvHeadlineVal" class="text-xs text-ink-900 font-medium leading-relaxed bg-white/60 p-3 rounded-lg border border-brand-100/30 italic">
        ${headline ? _esc(headline) : '<span class="text-ink-700/40">Generating headline...</span>'}
      </div>
    </div>

    <div>
      <h3 class="font-display font-bold text-sm mb-1 text-ink-900">Tailor for a Specific Job Description</h3>
      <p class="text-[12px] text-ink-700/60 mb-4">Paste a job description below and our AI will generate a custom PDF resume optimized specifically for that role.</p>
      <textarea id="cvJdInput" rows="5" class="w-full px-4 py-3 border border-ink-900/10 rounded-xl text-xs focus:outline-none focus:ring-2 focus:ring-brand-500/30 resize-none bg-ink-900/[0.01]" placeholder="Paste the full job description here…"></textarea>
      
      <div class="flex items-center gap-3 mt-4">
        <button onclick="_generateTailoredPDF()" id="cvGenBtn" class="px-5 py-2.5 bg-gradient-to-r from-brand-600 to-brand-700 text-white text-xs font-bold rounded-xl hover:from-brand-700 hover:to-brand-800 transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          Generate Tailored PDF
        </button>
        
        <button onclick="_generateBasePDF()" id="cvGenBaseBtn" class="px-5 py-2.5 bg-white border border-ink-900/10 text-ink-700 text-xs font-bold rounded-xl hover:bg-ink-900/5 transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 16v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1m-4-4-4 4m0 0-4-4m4 4V4"/></svg>
          Download Base Resume PDF
        </button>
        
        <span id="cvGenStatus" class="text-[11px] font-semibold text-ink-700/50"></span>
      </div>
    </div>
  `;

  // Auto-generate if empty
  if (!headline) {
    _generateHeadline();
  }
}

async function _generateHeadline() {
  const btn = document.getElementById('cvGenHeadlineBtn');
  const valContainer = document.getElementById('cvHeadlineVal');
  if (btn) btn.disabled = true;
  if (valContainer) valContainer.innerHTML = '<span class="text-ink-700/40">Generating headline using AI…</span>';

  try {
    const res = await fetch('/api/user/master-cv/generate-headline', {
      method: 'POST'
    });
    const data = await res.json();
    if (data.ok) {
      if (!_cvData.personal) _cvData.personal = {};
      _cvData.personal.headline = data.headline;
      if (valContainer) valContainer.textContent = data.headline;
    } else {
      if (valContainer) valContainer.innerHTML = `<span class="text-rose-600">Error: ${data.error}</span>`;
    }
  } catch(e) {
    if (valContainer) valContainer.innerHTML = `<span class="text-rose-600">Error: ${e.message}</span>`;
  }
  if (btn) btn.disabled = false;
}

async function _generateBasePDF() {
  _readCurrentTab();
  // Save first
  await fetch('/api/user/master-cv', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({cv:_cvData})
  });

  const btn = document.getElementById('cvGenBaseBtn');
  const status = document.getElementById('cvGenStatus');
  btn.disabled = true; btn.textContent = 'Generating…';
  status.textContent = 'Generating PDF from Master CV…';

  try {
    const res = await fetch('/api/user/master-cv/generate-tailored', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jd_text: ''})
    });
    if (res.ok && res.headers.get('content-type')?.includes('pdf')) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url;
      a.download = 'base_resume.pdf'; a.click(); URL.revokeObjectURL(url);
      status.textContent = '✓ Base PDF downloaded!';
    } else {
      const data = await res.json();
      status.textContent = 'Error: '+(data.error||'Generation failed');
    }
  } catch(e) { status.textContent = 'Error: '+e.message; }
  btn.disabled = false; btn.innerHTML = '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 16v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1m-4-4-4 4m0 0-4-4m4 4V4"/></svg> Download Base Resume PDF';
  setTimeout(() => { status.textContent = ''; }, 5000);
}

// ── Personal ──
function _renderPersonal(el) {
  const p = _cvData.personal || {};
  el.innerHTML = `
    <h3 class="font-bold text-sm mb-4">Personal Details</h3>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      ${_field('cv_p_name','First Name',p.name)}
      ${_field('cv_p_last','Last Name',p.last_name)}
      ${_field('cv_p_email','Email',p.email,'email')}
      ${_field('cv_p_phone','Phone',p.phone,'tel')}
      ${_field('cv_p_linkedin','LinkedIn URL',p.linkedin_url,'url')}
      ${_field('cv_p_github','GitHub URL',p.github_url,'url')}
      ${_field('cv_p_portfolio','Portfolio URL',p.portfolio_url,'url')}
    </div>
    <div class="mt-4">
      <label class="text-[11px] font-bold text-ink-700/60 uppercase tracking-wide block mb-1">Professional Summary</label>
      <textarea id="cv_p_summary" rows="3" class="cv-input w-full resize-none">${_esc(p.summary||'')}</textarea>
    </div>`;
}

function _readPersonal() {
  const g = id => (document.getElementById(id)||{}).value||'';
  const existingHeadline = (_cvData.personal || {}).headline || '';
  _cvData.personal = {
    name: g('cv_p_name'),
    last_name: g('cv_p_last'),
    email: g('cv_p_email'),
    phone: g('cv_p_phone'),
    headline: existingHeadline,
    linkedin_url: g('cv_p_linkedin'),
    github_url: g('cv_p_github'),
    portfolio_url: g('cv_p_portfolio'),
    summary: g('cv_p_summary')
  };
}

// ── Repeatable Section Helpers ──
function _renderRepeatable(el, title, items, fields, sectionKey, addLabel) {
  let html = `<div class="flex items-center justify-between mb-4"><h3 class="font-bold text-sm">${title}</h3>
    <button onclick="_addEntry('${sectionKey}')" class="px-3 py-1.5 bg-brand-50 text-brand-700 text-[11px] font-bold rounded-lg hover:bg-brand-100 transition">+ ${addLabel||'Add Entry'}</button></div>`;
  if (!items.length) {
    html += `<div class="text-center py-8 text-ink-700/40 text-xs">No entries yet. Click "+ ${addLabel||'Add Entry'}" to begin.</div>`;
  }
  items.forEach((item, i) => {
    html += `<div class="p-4 border border-ink-900/5 rounded-xl mb-3 bg-ink-900/[0.01]">
      <div class="flex items-center justify-between mb-3">
        <span class="text-[11px] font-bold text-ink-700/50">#${i+1}</span>
        <div class="flex gap-1">
          ${i>0?`<button onclick="_moveEntry('${sectionKey}',${i},-1)" class="w-6 h-6 rounded border border-ink-900/10 grid place-items-center text-ink-700/50 hover:bg-ink-900/5 text-[10px]">↑</button>`:''}
          ${i<items.length-1?`<button onclick="_moveEntry('${sectionKey}',${i},1)" class="w-6 h-6 rounded border border-ink-900/10 grid place-items-center text-ink-700/50 hover:bg-ink-900/5 text-[10px]">↓</button>`:''}
          <button onclick="_removeEntry('${sectionKey}',${i})" class="w-6 h-6 rounded border border-rose-200 grid place-items-center text-rose-500 hover:bg-rose-50 text-[10px]">✕</button>
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        ${fields.filter(f=>f.type!=='bullets').map(f => _field(`cv_${sectionKey}_${i}_${f.key}`, f.label, item[f.key]||'', f.type||'text')).join('')}
      </div>
      ${fields.filter(f=>f.type==='bullets').map(f => _renderBullets(sectionKey, i, f.key, f.label, item[f.key]||[])).join('')}
    </div>`;
  });
  el.innerHTML = html;
}

function _renderBullets(section, idx, key, label, bullets) {
  let html = `<div class="mt-3"><label class="text-[11px] font-bold text-ink-700/60 uppercase tracking-wide block mb-1">${label}</label>`;
  bullets.forEach((b,bi) => {
    html += `<div class="flex gap-2 mb-1.5"><input class="cv-input flex-1" id="cv_${section}_${idx}_${key}_${bi}" value="${_esc(b)}"/>
      <button onclick="_removeBullet('${section}',${idx},'${key}',${bi})" class="text-rose-400 hover:text-rose-600 text-xs shrink-0">✕</button></div>`;
  });
  html += `<button onclick="_addBullet('${section}',${idx},'${key}')" class="text-[11px] text-brand-600 font-semibold hover:text-brand-800 mt-1">+ Add bullet</button></div>`;
  return html;
}

function _readRepeatable(sectionKey, fields) {
  const items = _cvData[sectionKey] || [];
  items.forEach((item, i) => {
    fields.forEach(f => {
      if (f.type === 'bullets') {
        const bullets = item[f.key] || [];
        item[f.key] = bullets.map((_, bi) => (document.getElementById(`cv_${sectionKey}_${i}_${f.key}_${bi}`)||{}).value||'').filter(v=>v.trim());
      } else {
        item[f.key] = (document.getElementById(`cv_${sectionKey}_${i}_${f.key}`)||{}).value||'';
      }
    });
  });
}

function _addEntry(sectionKey) {
  _readCurrentTab();
  const templates = {
    education: {degree:'',field_of_study:'',institute:'',gpa_or_percentage:'',start_year:'',end_year:''},
    experience: {company:'',role:'',project_title:'',start_date:'',end_date:'',responsibilities:[]},
    internships: {company:'',role:'',project_title:'',start_date:'',end_date:'',responsibilities:[]},
    positions_of_responsibility: {title:'',organization:'',start_date:'',end_date:'',bullets:[]},
    certifications: {title:'',issuer:'',date:'',description:''}
  };
  if (!_cvData[sectionKey]) _cvData[sectionKey] = [];
  _cvData[sectionKey].push({...(templates[sectionKey]||{})});
  _switchCVTab(_currentCVTab);
}

function _removeEntry(sectionKey, idx) {
  _readCurrentTab();
  _cvData[sectionKey].splice(idx, 1);
  _switchCVTab(_currentCVTab);
}

function _moveEntry(sectionKey, idx, dir) {
  _readCurrentTab();
  const arr = _cvData[sectionKey];
  const ni = idx + dir;
  if (ni < 0 || ni >= arr.length) return;
  [arr[idx], arr[ni]] = [arr[ni], arr[idx]];
  _switchCVTab(_currentCVTab);
}

function _addBullet(section, idx, key) {
  _readCurrentTab();
  if (!_cvData[section][idx][key]) _cvData[section][idx][key] = [];
  _cvData[section][idx][key].push('');
  _switchCVTab(_currentCVTab);
}

function _removeBullet(section, idx, key, bi) {
  _readCurrentTab();
  _cvData[section][idx][key].splice(bi, 1);
  _switchCVTab(_currentCVTab);
}

// ── Education ──
const _eduFields = [
  {key:'degree',label:'Degree'},{key:'field_of_study',label:'Field of Study'},
  {key:'institute',label:'Institute'},{key:'gpa_or_percentage',label:'GPA / Percentage'},
  {key:'start_year',label:'Start Year'},{key:'end_year',label:'End Year'}
];
function _renderEducation(el) { _renderRepeatable(el,'Education',_cvData.education||[],_eduFields,'education','Add Education'); }

// ── Experience ──
const _expFields = [
  {key:'company',label:'Company'},{key:'role',label:'Role / Title'},
  {key:'project_title',label:'Project Title'},{key:'start_date',label:'Start Date'},
  {key:'end_date',label:'End Date'},{key:'responsibilities',label:'Responsibilities & Achievements',type:'bullets'}
];
function _renderExperience(el) { _renderRepeatable(el,'Work Experience',_cvData.experience||[],_expFields,'experience','Add Experience'); }

// ── Internships ──
function _renderInternships(el) { _renderRepeatable(el,'Summer Internships',_cvData.internships||[],_expFields,'internships','Add Internship'); }

// ── POR ──
const _porFields = [
  {key:'title',label:'Title / Role'},{key:'organization',label:'Organization'},
  {key:'start_date',label:'Start Date'},{key:'end_date',label:'End Date'},
  {key:'bullets',label:'Key Contributions',type:'bullets'}
];
function _renderPOR(el) { _renderRepeatable(el,'Positions of Responsibility',_cvData.positions_of_responsibility||[],_porFields,'positions_of_responsibility','Add Position'); }

// ── Certifications ──
const _certFields = [
  {key:'title',label:'Certificate / Award Title'},{key:'issuer',label:'Issuing Organization'},
  {key:'date',label:'Date'},{key:'description',label:'Description'}
];
function _renderCertifications(el) { _renderRepeatable(el,'Awards & Certifications',_cvData.certifications||[],_certFields,'certifications','Add Certificate'); }

// ── Coursework (chips) ──
function _renderCoursework(el) { _renderChips(el, 'Coursework & Electives', 'coursework', 'e.g. Data Structures, Machine Learning'); }

// ── Hobbies (chips) ──
function _renderHobbies(el) { _renderChips(el, 'Hobbies & Interests', 'hobbies', 'e.g. Chess, Hiking, Photography'); }

function _renderChips(el, title, key, placeholder) {
  const items = _cvData[key] || [];
  let html = `<h3 class="font-bold text-sm mb-4">${title}</h3>
    <div class="flex flex-wrap gap-2 mb-4" id="cv_chips_${key}">`;
  items.forEach((item, i) => {
    html += `<span class="inline-flex items-center gap-1 px-3 py-1.5 bg-brand-50 text-brand-800 text-[12px] font-semibold rounded-full border border-brand-100">
      ${_esc(item)} <button onclick="_removeChip('${key}',${i})" class="text-brand-400 hover:text-rose-500 ml-0.5">✕</button></span>`;
  });
  html += `</div>
    <div class="flex gap-2"><input id="cv_chip_input_${key}" class="cv-input flex-1" placeholder="${placeholder}" onkeydown="if(event.key==='Enter'){event.preventDefault();_addChip('${key}')}"/>
    <button onclick="_addChip('${key}')" class="px-4 py-2 bg-ink-900/5 text-ink-700 text-[11px] font-bold rounded-lg hover:bg-ink-900/10 transition">Add</button></div>`;
  el.innerHTML = html;
}

function _addChip(key) {
  const inp = document.getElementById(`cv_chip_input_${key}`);
  const val = (inp.value||'').trim();
  if (!val) return;
  if (!_cvData[key]) _cvData[key] = [];
  _cvData[key].push(val);
  inp.value = '';
  _switchCVTab(_currentCVTab);
}

function _removeChip(key, idx) {
  _cvData[key].splice(idx, 1);
  _switchCVTab(_currentCVTab);
}

// ── Read current tab data before switching or saving ──
function _readCurrentTab() {
  const readers = [
    () => _readPersonal(),
    () => _readRepeatable('education', _eduFields),
    () => _readRepeatable('experience', _expFields),
    () => _readRepeatable('internships', _expFields),
    () => {}, // coursework — chips are already in _cvData
    () => _readRepeatable('positions_of_responsibility', _porFields),
    () => _readRepeatable('certifications', _certFields),
    () => {}, // hobbies — chips are already in _cvData
  ];
  if (readers[_currentCVTab]) readers[_currentCVTab]();
}

// ── Save ──
async function _saveMasterCV() {
  _readCurrentTab();
  const btn = document.getElementById('cvSaveBtn');
  const status = document.getElementById('cvSaveStatus');
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const res = await fetch('/api/user/master-cv', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({cv: _cvData})
    });
    const data = await res.json();
    status.classList.remove('hidden','text-rose-700'); status.classList.add('text-emerald-700');
    status.textContent = data.ok ? '✓ Master CV saved successfully!' : 'Error: '+(data.error||'Unknown');
    if (!data.ok) { status.classList.replace('text-emerald-700','text-rose-700'); }
  } catch(e) {
    status.classList.remove('hidden','text-emerald-700'); status.classList.add('text-rose-700');
    status.textContent = 'Save failed: '+e.message;
  }
  btn.disabled = false; btn.textContent = 'Save CV';
  setTimeout(() => status.classList.add('hidden'), 4000);
}

// ── Resume Parser Modal ──
function _parseResumeModal() {
  const existing = document.getElementById('cvParseModal');
  if (existing) existing.remove();
  document.body.insertAdjacentHTML('beforeend', `
  <div id="cvParseModal" class="fixed inset-0 bg-ink-900/50 backdrop-blur-sm z-50 flex items-center justify-center p-4" onclick="if(event.target===this)this.remove()">
    <div class="bg-white rounded-2xl w-full max-w-md shadow-2xl border border-ink-900/5 overflow-hidden slide-in" onclick="event.stopPropagation()">
      <div class="px-6 py-5 border-b border-ink-900/5 flex items-center justify-between">
        <div><h3 class="font-display font-bold text-base">Import from Resume</h3>
        <p class="text-[11px] text-ink-700/60 mt-0.5">Upload your resume to auto-fill the CV form using AI.</p></div>
        <button onclick="document.getElementById('cvParseModal').remove()" class="w-8 h-8 rounded-full border border-ink-900/10 hover:bg-ink-900/5 grid place-items-center text-ink-700">✕</button>
      </div>
      <div class="p-6">
        <label class="block w-full p-8 border-2 border-dashed border-brand-200 rounded-xl text-center cursor-pointer hover:border-brand-400 hover:bg-brand-50/30 transition">
          <input type="file" accept=".pdf,.doc,.docx" class="hidden" onchange="_parseResumeFile(this)"/>
          <svg class="mx-auto mb-2 text-brand-400" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <div class="text-[13px] font-semibold">Click to choose a resume file</div>
          <div class="text-[11px] text-ink-700/50 mt-0.5">PDF or DOCX · Max 5 MB</div>
        </label>
        <div id="cvParseStatus" class="mt-3 text-[12px] font-semibold text-center hidden"></div>
      </div>
    </div>
  </div>`);
}

async function _parseResumeFile(input) {
  if (!input.files || !input.files.length) return;
  const status = document.getElementById('cvParseStatus');
  status.classList.remove('hidden','text-emerald-700','text-rose-700');
  status.classList.add('text-brand-700'); status.textContent = '🤖 Parsing with AI… this may take 10-20 seconds';

  const formData = new FormData();
  formData.append('resume', input.files[0]);
  try {
    const res = await fetch('/api/user/master-cv/parse-resume', {method:'POST', body:formData});
    const data = await res.json();
    if (data.ok && data.cv) {
      _cvData = data.cv;
      status.classList.replace('text-brand-700','text-emerald-700');
      status.textContent = '✓ Resume parsed! Closing…';
      setTimeout(() => { document.getElementById('cvParseModal')?.remove(); _renderCVForm(); }, 1200);
    } else {
      status.classList.replace('text-brand-700','text-rose-700');
      status.textContent = 'Error: '+(data.error||'Parse failed');
    }
  } catch(e) {
    status.classList.replace('text-brand-700','text-rose-700');
    status.textContent = 'Error: '+e.message;
  }
}

// ── Tailored PDF ──
async function _generateTailoredPDF() {
  _readCurrentTab();
  // Save first
  await fetch('/api/user/master-cv', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({cv:_cvData})
  });

  const btn = document.getElementById('cvGenBtn');
  const status = document.getElementById('cvGenStatus');
  const jd = (document.getElementById('cvJdInput')||{}).value||'';
  btn.disabled = true; btn.textContent = 'Generating…';
  status.textContent = jd ? 'Tailoring with AI + generating PDF…' : 'Generating PDF from Master CV…';

  try {
    const res = await fetch('/api/user/master-cv/generate-tailored', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({jd_text: jd})
    });
    if (res.ok && res.headers.get('content-type')?.includes('pdf')) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url;
      a.download = 'tailored_resume.pdf'; a.click(); URL.revokeObjectURL(url);
      status.textContent = '✓ PDF downloaded!';
    } else {
      const data = await res.json();
      status.textContent = 'Error: '+(data.error||'Generation failed');
    }
  } catch(e) { status.textContent = 'Error: '+e.message; }
  btn.disabled = false; btn.innerHTML = '<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> Generate PDF';
  setTimeout(() => { status.textContent = ''; }, 5000);
}

// ── Helpers ──
function _field(id, label, value, type) {
  type = type || 'text';
  return `<div><label class="text-[11px] font-bold text-ink-700/60 uppercase tracking-wide block mb-1">${label}</label>
    <input type="${type}" id="${id}" value="${_esc(value||'')}" class="cv-input w-full"/></div>`;
}

function _esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
