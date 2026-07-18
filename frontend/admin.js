/* admin.js — Hybrid API-Integrated & Mock Offline Admin Console for IITIIMJobAssistant */
const API = window.location.origin;
let TOKEN = '';
let ADMIN = {};
let charts = {};
let isMockMode = false;

/* ── Mock Data (Template fallback) ── */
const QUEUE = [
  { id: 1, user_name: 'Rohan', user_last_name: 'Mehta', user_email: 'rohan.m@gmail.com', linkedin_url: 'linkedin.com/in/rohan-mehta-iitd', ago: '18 min ago', user_avatar: 'RM', created_at: new Date(Date.now() - 18 * 60000).toISOString() },
  { id: 2, user_name: 'Kavya', user_last_name: 'Reddy', user_email: 'kavya.r@iimb.ac.in', linkedin_url: 'linkedin.com/in/kavya-reddy-iimb', ago: '1 hr ago', user_avatar: 'KR', created_at: new Date(Date.now() - 60 * 60000).toISOString() },
  { id: 3, user_name: 'Arjun', user_last_name: 'Singh', user_email: 'arjun.s99@yahoo.com', linkedin_url: 'linkedin.com/in/arjun-singh-99', ago: '2 hrs ago', user_avatar: 'AS', created_at: new Date(Date.now() - 120 * 60000).toISOString() },
  { id: 4, user_name: 'Meera', user_last_name: 'Krishnan', user_email: 'meera.k@iitm.ac.in', linkedin_url: 'linkedin.com/in/meera-krishnan', ago: '3 hrs ago', user_avatar: 'MK', created_at: new Date(Date.now() - 180 * 60000).toISOString() },
  { id: 5, user_name: 'Siddharth', user_last_name: 'Patel', user_email: 'sid.patel@hotmail.com', linkedin_url: 'linkedin.com/in/siddharth-patel', ago: '4 hrs ago', user_avatar: 'SP', created_at: new Date(Date.now() - 240 * 60000).toISOString() },
  { id: 6, user_name: 'Tanvi', user_last_name: 'Agarwal', user_email: 'tanvi.a@iimc.ac.in', linkedin_url: 'linkedin.com/in/tanvi-agarwal-iimc', ago: '5 hrs ago', user_avatar: 'TA', created_at: new Date(Date.now() - 300 * 60000).toISOString() },
  { id: 7, user_name: 'Kiran', user_last_name: 'Bhat', user_email: 'kiran.b@iitk.ac.in', linkedin_url: 'linkedin.com/in/kiran-bhat-iitk', ago: '6 hrs ago', user_avatar: 'KB', created_at: new Date(Date.now() - 360 * 60000).toISOString() }
];

const USERS = [
  { id: 101, name: 'Aarav', last_name: 'Kulkarni', email: 'aarav.k@iitb.ac.in', inst: 'IIT Bombay', grad: "'22", status: 'approved', subscription_status: 'active', sub: '3-month · ₹2,500/mo', la: '6 min ago', last_login_at: new Date(Date.now() - 6 * 60000).toISOString(), login_count: 142, agent_usage_count: 15, total_applications: 142, last_activity_at: new Date(Date.now() - 6 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/aarav-kulkarni' },
  { id: 102, name: 'Sneha', last_name: 'Agarwal', email: 'sneha.a@iimb.ac.in', inst: 'IIM Bangalore', grad: "'21", status: 'approved', subscription_status: 'active', sub: '6-month · ₹2,000/mo', la: '2 hrs ago', last_login_at: new Date(Date.now() - 120 * 60000).toISOString(), login_count: 89, agent_usage_count: 12, total_applications: 89, last_activity_at: new Date(Date.now() - 120 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/sneha-agarwal' },
  { id: 103, name: 'Rahul', last_name: 'Verma', email: 'rahul.v@iitk.ac.in', inst: 'IIT Kanpur', grad: "'23", status: 'approved', subscription_status: 'active', sub: '1-month · ₹3,000/mo', la: '1 day ago', last_login_at: new Date(Date.now() - 1440 * 60000).toISOString(), login_count: 38, agent_usage_count: 5, total_applications: 38, last_activity_at: new Date(Date.now() - 1440 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/rahul-verma' },
  { id: 104, name: 'Pooja', last_name: 'Iyer', email: 'pooja.i@iima.ac.in', inst: 'IIM Ahmedabad', grad: "'20", status: 'approved', subscription_status: 'inactive', sub: '—', la: '3 days ago', last_login_at: new Date(Date.now() - 3 * 1440 * 60000).toISOString(), login_count: 12, agent_usage_count: 0, total_applications: 0, last_activity_at: new Date(Date.now() - 3 * 1440 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/pooja-iyer' },
  { id: 105, name: 'Aman', last_name: 'Gupta', email: 'aman.g@iitd.ac.in', inst: 'IIT Delhi', grad: "'24", status: 'pending', subscription_status: 'inactive', sub: '—', la: 'Just now', last_login_at: new Date().toISOString(), login_count: 1, agent_usage_count: 0, total_applications: 0, last_activity_at: new Date().toISOString(), linkedin_url: 'linkedin.com/in/aman-gupta' },
  { id: 106, name: 'Divya', last_name: 'Nambiar', email: 'divya.n@iitm.ac.in', inst: 'IIT Madras', grad: "'22", status: 'approved', subscription_status: 'active', sub: '3-month · ₹2,500/mo', la: '4 hrs ago', last_login_at: new Date(Date.now() - 240 * 60000).toISOString(), login_count: 112, agent_usage_count: 22, total_applications: 112, last_activity_at: new Date(Date.now() - 240 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/divya-nambiar' },
  { id: 107, name: 'Harsh', last_name: 'Malhotra', email: 'harsh.m@gmail.com', inst: 'Unknown', grad: '—', status: 'rejected', subscription_status: 'inactive', sub: '—', la: '5 days ago', last_login_at: new Date(Date.now() - 5 * 1440 * 60000).toISOString(), login_count: 2, agent_usage_count: 0, total_applications: 0, last_activity_at: new Date(Date.now() - 5 * 1440 * 60000).toISOString(), linkedin_url: 'linkedin.com/in/harsh-malhotra' }
];

const AUDIT = [
  { timestamp: new Date(Date.now() - 10 * 60000).toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_APPROVED', target_user_name: 'Ananya Sharma', reason: 'Valid IIM Ahmedabad profile' },
  { timestamp: new Date(Date.now() - 90 * 60000).toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_REJECTED', target_user_name: 'Harsh Malhotra', reason: 'No IIT/IIM education found on profile' },
  { timestamp: new Date(Date.now() - 120 * 60000).toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_APPROVED', target_user_name: 'Divya Nambiar', reason: 'Valid IIT Madras profile' },
  { timestamp: new Date(Date.now() - 150 * 60000).toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_APPROVED', target_user_name: 'Ishita Roy', reason: 'Valid IIM Calcutta profile' },
  { timestamp: new Date(Date.now() - 1440 * 60000).toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_REJECTED', target_user_name: 'Vikram Rao', reason: 'LinkedIn URL invalid or inaccessible' }
];

let pendingQueue = [...QUEUE];
let rejectTargetId = null;

// Load real submissions from localStorage
function loadRealSubmissions() {
  try {
    const stored = JSON.parse(localStorage.getItem('iitiim_pending') || '[]');
    if (!stored.length) return;
    const existingIds = new Set(pendingQueue.map(u => u.id));
    stored.forEach(s => {
      if (!existingIds.has(s.id)) {
        const mins = Math.round((Date.now() - new Date(s.submittedAt || s.submitted_at || Date.now()).getTime()) / 60000);
        let ago = mins < 1 ? 'Just now' : mins < 60 ? `${mins} min ago` : mins < 1440 ? `${Math.floor(mins/60)} hr ago` : `${Math.floor(mins/1440)} days ago`;
        pendingQueue.unshift({
          id: s.id,
          user_name: s.name || s.user_name || '—',
          user_last_name: s.last_name || s.user_last_name || '',
          user_email: s.email || s.user_email || '—',
          linkedin_url: s.linkedin_url || s.li || '',
          ago: ago,
          user_avatar: (s.name || '??').split(' ').map(n=>n[0]).join('').slice(0,2).toUpperCase(),
          created_at: s.submittedAt || s.submitted_at || new Date().toISOString(),
          _real: true
        });
      }
    });
  } catch(e) { console.error(e); }
}

/* ── Auth helpers ── */
function getToken() { return sessionStorage.getItem('admin_token') || ''; }
function setToken(token, admin, mode) {
  TOKEN = token;
  ADMIN = admin;
  isMockMode = (mode === 'mock');
  sessionStorage.setItem('admin_token', token);
  sessionStorage.setItem('admin_info', JSON.stringify(admin));
  sessionStorage.setItem('admin_mode', isMockMode ? 'mock' : 'api');
}
function clearToken() {
  TOKEN = '';
  ADMIN = {};
  isMockMode = false;
  sessionStorage.removeItem('admin_token');
  sessionStorage.removeItem('admin_info');
  sessionStorage.removeItem('admin_mode');
}
function authHeaders() { return { 'Authorization': 'Bearer ' + getToken(), 'Content-Type': 'application/json' }; }

async function apiFetch(url, opts = {}) {
  if (isMockMode) return {};
  opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
  const r = await fetch(API + url, opts);
  if (r.status === 401) {
    clearToken();
    showLogin();
    throw new Error('Unauthorized');
  }
  return r.json();
}

/* ── Login Actions ── */
async function doLogin() {
  const email = document.getElementById('l-email').value.trim();
  const pwd = document.getElementById('l-pwd').value.trim();
  const btn = document.querySelector('#view-login .btn-primary');
  const errEl = document.getElementById('login-error');
  if (!email || !pwd) { errEl.textContent = 'Email and password required'; errEl.classList.remove('hidden'); return; }
  btn.textContent = 'Signing in…'; btn.disabled = true; errEl.classList.add('hidden');

  try {
    const res = await fetch(API + '/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: pwd })
    });
    const data = await res.json();
    if (!data.ok) {
      errEl.textContent = data.error || 'Login failed';
      errEl.classList.remove('hidden');
      btn.textContent = 'Sign in to Console';
      btn.disabled = false;
      return;
    }
    setToken(data.token, data.admin, 'api');
    showApp();
  } catch (e) {
    // If Flask is unreachable, fallback to static credentials check
    if (email === 'admin@iitiim.ai' && pwd === 'admin123') {
      toast('Server offline. Logging into Demo/Offline Mode.', 'warn');
      setToken('mock-jwt-token', { name: 'Demo Admin', email: 'admin@iitiim.ai', role: 'SUPER_ADMIN' }, 'mock');
      showApp();
    } else {
      errEl.textContent = 'Server unreachable. Use admin@iitiim.ai / admin123 for Offline Mode.';
      errEl.classList.remove('hidden');
    }
  }
  btn.textContent = 'Sign in to Console'; btn.disabled = false;
}

function enterMockMode() {
  setToken('mock-jwt-token', { name: 'Demo Admin', email: 'admin@iitiim.ai', role: 'SUPER_ADMIN' }, 'mock');
  showApp();
  toast('Entered Demo/Offline Mode', 'ok');
}

function showLogin() {
  document.getElementById('view-login').classList.add('active');
  document.getElementById('app-shell').style.display = 'none';
}

function showApp() {
  document.getElementById('view-login').classList.remove('active');
  document.getElementById('app-shell').style.display = 'flex';
  const info = ADMIN.name || ADMIN.email || 'Admin';
  document.getElementById('admin-name').textContent = info;
  document.getElementById('admin-email').textContent = ADMIN.email || '';
  document.getElementById('admin-avatar').textContent = (info[0] || 'A').toUpperCase();

  // Mode badge rendering
  const mBadge = document.getElementById('mode-badge');
  if (mBadge) {
    if (isMockMode) {
      mBadge.innerHTML = '<span style="background:#FEF3C7;color:#92400e;border:1px solid #fde68a;" class="badge"><span class="dot dot-warn pulse"></span>Demo Mode</span>';
    } else {
      mBadge.innerHTML = '<span style="background:#DCFCE7;color:#15803d;border:1px solid #bbf7d0;" class="badge"><span class="dot dot-ok pulse"></span>Live Database</span>';
    }
  }

  // Get role and permissions
  const isSuper = ADMIN.role === 'SUPER_ADMIN';
  const permsStr = ADMIN.permissions || '';
  const perms = permsStr.split(',').map(p => p.trim()).filter(Boolean);

  // Hide/show navbar items based on permissions
  document.querySelectorAll('.nav-item').forEach(el => {
    const view = el.getAttribute('data-view');
    if (isSuper) {
      el.style.display = '';
    } else {
      // For standard admins, check specific permissions, admins is SUPER_ADMIN only
      if (view !== 'admins' && perms.includes(view)) {
        el.style.display = '';
      } else {
        el.style.display = 'none';
      }
    }
  });

  // Decide starting view
  if (isSuper) {
    loadRealSubmissions();
    navigate('dashboard');
    refreshPendingCount();
  } else {
    // Standard admin
    loadRealSubmissions();
    if (perms.length > 0) {
      navigate(perms[0]);
    } else {
      navigate('users');
    }
  }

  updateDate();
  setInterval(updateDate, 60000);
}

async function refreshPendingCount() {
  try {
    if (isMockMode) {
      const c = pendingQueue.length;
      const pc = document.getElementById('pending-count'); if (pc) pc.textContent = c;
      const qb = document.getElementById('queue-badge'); if (qb) { qb.textContent = c; qb.style.display = c > 0 ? '' : 'none'; }
      return;
    }
    const d = await apiFetch('/admin/verifications?status=PENDING&per_page=1');
    const c = d.total || 0;
    const pc = document.getElementById('pending-count'); if (pc) pc.textContent = c;
    const qb = document.getElementById('queue-badge'); if (qb) { qb.textContent = c; qb.style.display = c > 0 ? '' : 'none'; }
  } catch(e) {}
}

function doLogout() { clearToken(); showLogin(); }
function updateDate() {
  const d = new Date();
  document.getElementById('live-date').textContent = d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }) + ' · ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

/* ── Navigation ── */
function navigate(view) {
  const isSuper = ADMIN.role === 'SUPER_ADMIN';
  const permsStr = ADMIN.permissions || '';
  const perms = permsStr.split(',').map(p => p.trim()).filter(Boolean);

  if (!isSuper) {
    if (view === 'admins' || !perms.includes(view)) {
      view = perms.length > 0 ? perms[0] : 'users';
    }
  }

  document.querySelectorAll('#app-shell .view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const el = document.getElementById('view-' + view);
  if (el) el.classList.add('active');
  const ni = document.querySelector(`.nav-item[data-view="${view}"]`);
  if (ni) ni.classList.add('active');

  const titles = { dashboard: 'Dashboard', queue: 'Approval Queue', users: 'User Directory', database: 'User Database', audit: 'Audit Log', admins: 'Admin Accounts' };
  document.getElementById('page-title').textContent = titles[view] || view;

  if (view === 'dashboard') loadDashboard();
  if (view === 'queue') loadQueue();
  if (view === 'users') loadUsers();
  if (view === 'database') renderDatabase();
  if (view === 'audit') loadAudit();
  if (view === 'admins') loadAdmins();
}

/* ── Dashboard stats & charts ── */
async function loadDashboard() {
  if (isMockMode) {
    const verifiedCount = USERS.filter(u => u.status === 'approved').length;
    const pendingCount = pendingQueue.length;
    const rejectedCount = USERS.filter(u => u.status === 'rejected').length;
    const totalCount = USERS.length + pendingCount;
    const activeSubCount = USERS.filter(u => u.subscription_status === 'active').length;
    const inactiveSubCount = USERS.filter(u => u.subscription_status === 'inactive').length;
    const passRate = Math.round((verifiedCount / (verifiedCount + rejectedCount || 1)) * 100);
    const convRate = Math.round((activeSubCount / (verifiedCount || 1)) * 100);

    document.getElementById('s-total').textContent = totalCount;
    document.getElementById('s-verified').textContent = verifiedCount;
    document.getElementById('s-pending').textContent = pendingCount;
    document.getElementById('s-rejected').textContent = rejectedCount;
    document.getElementById('s-active').textContent = activeSubCount;
    document.getElementById('s-inactive').textContent = inactiveSubCount;
    document.getElementById('s-passrate').textContent = passRate + '%';
    document.getElementById('s-conversion').textContent = convRate + '%';

    initMockCharts(verifiedCount, rejectedCount, pendingCount);
  } else {
    try {
      const d = await apiFetch('/admin/dashboard');
      document.getElementById('s-total').textContent = d.total_users;
      document.getElementById('s-verified').textContent = d.verified_users;
      document.getElementById('s-pending').textContent = d.pending_users;
      document.getElementById('s-rejected').textContent = d.rejected_users;
      document.getElementById('s-active').textContent = d.total_subscribers || d.active_subscribers;
      document.getElementById('s-inactive').textContent = d.inactive_subscribers || 0;
      document.getElementById('s-passrate').textContent = d.verification_pass_rate + '%';
      document.getElementById('s-conversion').textContent = d.subscription_conversion_rate + '%';
      
      loadSignupChart();
      initFunnelChart(d.verified_users, d.rejected_users, d.pending_users);
    } catch(e) { console.error('Dashboard load error', e); }
  }
}

async function loadSignupChart() {
  try {
    const d = await apiFetch('/admin/dashboard/signups?days=30');
    const labels = d.signups.map(s => s.date ? s.date.slice(5) : '');
    const data = d.signups.map(s => s.count);
    renderSignupLineChart(labels, data);
  } catch(e) { console.error('Chart error', e); }
}

function renderSignupLineChart(labels, data) {
  const ctx = document.getElementById('signupChart');
  if (!ctx) return;
  if (charts.s) {
    charts.s.data.labels = labels;
    charts.s.data.datasets[0].data = data;
    charts.s.update();
    return;
  }
  const g = ctx.getContext('2d').createLinearGradient(0, 0, 0, 195);
  g.addColorStop(0, 'rgba(91,102,232,0.18)');
  g.addColorStop(1, 'rgba(91,102,232,0)');
  charts.s = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Signups', data, borderColor: '#5B66E8', backgroundColor: g, borderWidth: 2, fill: true, tension: 0.4, pointBackgroundColor: '#5B66E8', pointRadius: 3, pointHoverRadius: 5 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(15,16,51,0.05)' }, ticks: { color: '#9CA3AF', font: { size: 11 } } },
        y: { grid: { color: 'rgba(15,16,51,0.05)' }, ticks: { color: '#9CA3AF', font: { size: 11 } } }
      }
    }
  });
}

function initFunnelChart(verified, rejected, pending) {
  const fCtx = document.getElementById('funnelChart');
  if (!fCtx) return;
  const total = (verified + rejected + pending) || 1;
  const pV = ((verified / total) * 100).toFixed(1);
  const pR = ((rejected / total) * 100).toFixed(1);
  const pP = ((pending / total) * 100).toFixed(1);

  if (charts.f) {
    charts.f.data.datasets[0].data = [pV, pR, pP];
    charts.f.update();
    renderFunnelLegend(pV, pR, pP);
    return;
  }

  charts.f = new Chart(fCtx.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: ['Verified', 'Rejected', 'Pending'],
      datasets: [{ data: [pV, pR, pP], backgroundColor: ['#22c55e', '#ef4444', '#f59e0b'], borderWidth: 0, hoverOffset: 4 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '70%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#fff',
          borderColor: 'rgba(15,16,51,0.1)',
          borderWidth: 1,
          titleColor: '#6B7280',
          bodyColor: '#0B0D1F',
          padding: 10,
          callbacks: { label: c => ` ${c.label}: ${c.raw}%` }
        }
      }
    }
  });
  renderFunnelLegend(pV, pR, pP);
}

function renderFunnelLegend(pV, pR, pP) {
  const legend = document.getElementById('funnel-legend');
  if (!legend) return;
  legend.innerHTML = `
    <div style="display:flex;justify-content:between;font-size:12px">
      <span style="color:#22c55e;font-weight:600">● Verified: ${pV}%</span>
      <span style="color:#ef4444;font-weight:600">● Rejected: ${pR}%</span>
      <span style="color:#f59e0b;font-weight:600">● Pending: ${pP}%</span>
    </div>
  `;
}

function initMockCharts(verified, rejected, pending) {
  renderSignupLineChart(['Apr 13', 'Apr 14', 'Apr 15', 'Apr 16', 'Apr 17', 'Apr 18', 'Apr 19'], [38, 52, 41, 67, 71, 58, 84]);
  initFunnelChart(verified, rejected, pending);
}

/* ── Approval Queue ── */
let queueTab = 'PENDING';
async function loadQueue(status) {
  if (status) queueTab = status;
  const container = document.getElementById('queue-content');
  container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#9CA3AF">Loading…</div>';

  if (isMockMode) {
    let items = [];
    if (queueTab === 'PENDING') {
      items = pendingQueue;
      const pc = document.getElementById('pending-count');
      if (pc) pc.textContent = items.length;
      if (!items.length) {
        container.innerHTML = `<div class="text-center p-8"><div style="font-size:40px;margin-bottom:12px">✓</div><div class="font-display font-bold text-lg mb-1">All clear!</div><div class="text-sm" style="color:#9CA3AF">No pending verifications.</div></div>`;
        return;
      }
      container.innerHTML = items.map(v => renderQueueCard(v)).join('');
    } else {
      const matchStatus = queueTab === 'APPROVED' ? 'approved' : 'rejected';
      items = USERS.filter(u => u.status === matchStatus);
      if (!items.length) {
        container.innerHTML = `<div class="text-center p-8"><div class="text-sm" style="color:#9CA3AF">No ${queueTab.toLowerCase()} verifications.</div></div>`;
        return;
      }
      container.innerHTML = `
        <div class="card overflow-hidden">
          <table>
            <thead><tr><th>User</th><th>LinkedIn</th><th>Details</th><th>Status</th></tr></thead>
            <tbody>
              ${items.map(v => `
                <tr>
                  <td><div class="font-medium text-sm">${v.name || ''} ${v.last_name || ''}</div><div class="text-xs" style="color:#9CA3AF">${v.email || ''}</div></td>
                  <td class="text-xs break-all" style="color:#4B52D1;max-width:200px">${v.linkedin_url || '—'}</td>
                  <td class="text-xs" style="color:#6B7280">${v.inst || '—'} · Grad ${v.grad || '—'}</td>
                  <td class="text-xs"><span class="badge ${v.status === 'approved' ? 'badge-ok' : 'badge-err'}">${v.status}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }
  } else {
    try {
      const d = await apiFetch(`/admin/verifications?status=${queueTab}&per_page=50`);
      const items = d.verifications || [];
      const pc = document.getElementById('pending-count');
      if (queueTab === 'PENDING' && pc) pc.textContent = d.total;
      
      if (!items.length) {
        container.innerHTML = `<div class="text-center p-8"><div style="font-size:40px;margin-bottom:12px">✓</div><div class="font-display font-bold text-lg mb-1">All clear!</div><div class="text-sm" style="color:#9CA3AF">No ${queueTab.toLowerCase()} verifications.</div></div>`;
        return;
      }
      
      if (queueTab === 'PENDING') {
        container.innerHTML = items.map(v => renderQueueCard(v)).join('');
      } else {
        container.innerHTML = `
          <div class="card overflow-hidden">
            <table>
              <thead><tr><th>User</th><th>LinkedIn</th><th>${queueTab === 'REJECTED' ? 'Reason' : 'Reviewed By'}</th><th>Date</th></tr></thead>
              <tbody>
                ${items.map(v => `
                  <tr>
                    <td><div class="font-medium text-sm">${v.user_name || ''} ${v.user_last_name || ''}</div><div class="text-xs" style="color:#9CA3AF">${v.user_email || ''}</div></td>
                    <td class="text-xs break-all" style="color:#4B52D1;max-width:200px">${v.linkedin_url || '—'}</td>
                    <td class="text-xs" style="color:#6B7280;max-width:200px">${queueTab === 'REJECTED' ? (v.rejection_reason || '—') : (v.reviewer_name || '—')}</td>
                    <td class="text-xs whitespace-nowrap" style="color:#9CA3AF">${fmtDate(v.reviewed_at || v.created_at)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      }
    } catch(e) { container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#dc2626">Failed to load verifications queue</div>'; }
  }
}

function renderQueueCard(v) {
  const li = v.linkedin_url ? (v.linkedin_url.startsWith('http') ? v.linkedin_url : 'https://' + v.linkedin_url) : '#';
  return `
    <div class="card p-6 fade-up mb-4" id="qc-${v.id}">
      <div class="flex gap-4" style="align-items:flex-start">
        <div style="width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;background:linear-gradient(135deg,#5B66E8,#A3ACFF);flex-shrink:0">${(v.user_avatar || '??').slice(0,2)}</div>
        <div style="flex:1;min-width:0">
          <div class="flex items-center gap-2 flex-wrap mb-1">
            <span class="font-display font-bold text-base">${v.user_name || ''} ${v.user_last_name || ''}</span>
            ${v._real ? `<span class="badge" style="background:#DCFCE7;color:#15803d;border:1px solid #bbf7d0;"><span class="dot dot-ok pulse"></span>New signup</span>` : ''}
            <span class="badge badge-warn"><span class="dot dot-warn"></span>Pending Review</span>
            <span class="ml-auto text-xs" style="color:#9CA3AF">${v.ago || fmtDate(v.created_at)}</span>
          </div>
          <div class="text-sm mb-4" style="color:#9CA3AF">${v.user_email || ''}</div>
          <div class="mb-4 p-4" style="background:linear-gradient(135deg,#EEF0FF,#F5F6FD);border:1.5px solid #C3CAFF;border-radius:12px;display:flex;align-items:center;gap:16px">
            <div style="width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:#0A66C2;flex-shrink:0"><svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M16 8a6 6 0 016 6v7h-4v-7a2 2 0 00-4 0v7h-4v-7a6 6 0 016-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg></div>
            <div style="flex:1;min-width:0"><div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color:#9CA3AF">LinkedIn Profile</div><a href="${li}" target="_blank" class="text-sm font-semibold break-all" style="color:#4B52D1">${v.linkedin_url || '—'}</a></div>
            <a href="${li}" target="_blank" class="btn-brand" style="text-decoration:none;flex-shrink:0;font-size:13px;padding:8px 16px">Verify credentials</a>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <button class="btn-ok" onclick="approveVerif(${v.id})"><svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>Approve access</button>
            <button class="btn-err" onclick="openRejectModal(${v.id},'${(v.user_name||'').replace(/'/g,"\\'")} ${(v.user_last_name||'').replace(/'/g,"\\'")}','${(v.user_email||'').replace(/'/g,"\\'")}')"><svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>Reject</button>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function approveVerif(id) {
  if (!confirm('Approve this verification request?')) return;
  if (isMockMode) {
    const u = pendingQueue.find(x => x.id === id);
    if (!u) return;
    pendingQueue = pendingQueue.filter(x => x.id !== id);
    // Move or update status in mock USERS
    const existing = USERS.find(x => x.email === u.user_email);
    if (existing) {
      existing.status = 'approved';
    } else {
      USERS.unshift({
        id: u.id,
        name: u.user_name,
        last_name: u.user_last_name,
        email: u.user_email,
        inst: 'IIT Delhi', grad: "'23",
        status: 'approved',
        subscription_status: 'inactive',
        sub: '—', la: 'Just now',
        last_login_at: new Date().toISOString(),
        login_count: 1, agent_usage_count: 0, total_applications: 0,
        linkedin_url: u.linkedin_url
      });
    }
    // Remove from localstorage pending
    try {
      const stored = JSON.parse(localStorage.getItem('iitiim_pending') || '[]');
      localStorage.setItem('iitiim_pending', JSON.stringify(stored.filter(s => s.id !== id)));
    } catch(e){}
    AUDIT.unshift({ timestamp: new Date().toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_APPROVED', target_user_name: `${u.user_name} ${u.user_last_name}`, reason: 'Admin verified LinkedIn profile — IIT/IIM confirmed' });
    toast(`✓ Approved ${u.user_name}`, 'ok');
    loadQueue();
    refreshPendingCount();
  } else {
    try {
      const r = await apiFetch(`/admin/verifications/${id}/approve`, { method: 'POST' });
      if (r.ok) { toast('Verification approved', 'ok'); loadQueue(); refreshPendingCount(); }
      else toast(r.error || 'Failed to approve', 'warn');
    } catch(e) { toast('Error approving verification', 'warn'); }
  }
}

let rejectId = null;
function openRejectModal(id, name, email) {
  rejectId = id;
  document.getElementById('rej-title').textContent = 'Reject — ' + name;
  document.getElementById('rej-sub').textContent = email;
  document.getElementById('rej-reason-sel').value = '';
  document.getElementById('rej-notes').value = '';
  document.getElementById('reject-modal').classList.add('open');
}
function closeRejectModal() { document.getElementById('reject-modal').classList.remove('open'); rejectId = null; }

async function confirmReject() {
  const sel = document.getElementById('rej-reason-sel').value;
  const notes = document.getElementById('rej-notes').value.trim();
  const reason = sel || notes || 'No reason provided';
  if (!reason) { toast('Reason is required', 'warn'); return; }

  if (isMockMode) {
    const u = pendingQueue.find(x => x.id === rejectId);
    if (!u) return;
    pendingQueue = pendingQueue.filter(x => x.id !== rejectId);
    // Update status in mock USERS
    const existing = USERS.find(x => x.email === u.user_email);
    if (existing) {
      existing.status = 'rejected';
    } else {
      USERS.unshift({
        id: u.id,
        name: u.user_name,
        last_name: u.user_last_name,
        email: u.user_email,
        inst: 'Unknown', grad: '—',
        status: 'rejected',
        subscription_status: 'inactive',
        sub: '—', la: 'Just now',
        last_login_at: new Date().toISOString(),
        login_count: 1, agent_usage_count: 0, total_applications: 0,
        linkedin_url: u.linkedin_url
      });
    }
    // Remove from localstorage pending
    try {
      const stored = JSON.parse(localStorage.getItem('iitiim_pending') || '[]');
      localStorage.setItem('iitiim_pending', JSON.stringify(stored.filter(s => s.id !== rejectId)));
    } catch(e){}
    AUDIT.unshift({ timestamp: new Date().toISOString(), admin_email: 'Superadmin', action: 'VERIFICATION_REJECTED', target_user_name: `${u.user_name} ${u.user_last_name}`, reason: reason });
    toast(`✗ Rejected ${u.user_name}`, 'warn');
    closeRejectModal();
    loadQueue();
    refreshPendingCount();
  } else {
    try {
      const r = await apiFetch(`/admin/verifications/${rejectId}/reject`, { method: 'POST', body: JSON.stringify({ reason }) });
      if (r.ok) { toast('Verification rejected', 'warn'); closeRejectModal(); loadQueue(); refreshPendingCount(); }
      else toast(r.error || 'Failed to reject', 'warn');
    } catch(e) { toast('Error rejecting verification', 'warn'); }
  }
}

/* ── User Directory ── */
let usersPage = 1, usersSearch = '', usersStatus = '', usersSub = '', usersSort = 'submitted_at', usersSortDir = 'DESC';
async function loadUsers() {
  const tbody = document.getElementById('users-tbody');
  const info = document.getElementById('users-info');
  tbody.innerHTML = '<tr><td colspan="7" class="text-center p-8 text-sm" style="color:#9CA3AF">Loading…</td></tr>';

  if (isMockMode) {
    let data = [...USERS];
    if (usersSearch) {
      const q = usersSearch.toLowerCase();
      data = data.filter(u => `${u.name} ${u.last_name}`.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || u.inst.toLowerCase().includes(q));
    }
    if (usersStatus) {
      data = data.filter(u => u.status === usersStatus);
    }
    if (usersSub) {
      data = data.filter(u => u.subscription_status === usersSub);
    }
    
    info.textContent = `Showing 1–${data.length} of ${data.length}`;
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="7" class="text-center p-8 text-sm" style="color:#9CA3AF">No users found</td></tr>'; return; }

    tbody.innerHTML = data.map((u, idx) => {
      const av = ((u.name || '?')[0] + (u.last_name || '?')[0]).toUpperCase();
      const stBadge = { pending: '<span class="badge badge-warn"><span class="dot dot-warn"></span>Pending</span>', approved: '<span class="badge badge-ok"><span class="dot dot-ok"></span>Verified</span>', rejected: '<span class="badge badge-err"><span class="dot dot-err"></span>Rejected</span>' }[u.status] || '<span class="badge badge-mute">Unknown</span>';
      const subBadge = u.subscription_status === 'active' ? `<span class="badge badge-blue">${u.sub || 'Active'}</span>` : '<span class="text-xs" style="color:#9CA3AF">—</span>';
      return `
        <tr onclick="openUserDetail(${idx})">
          <td>
            <div class="flex items-center gap-3">
              <div style="width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;background:linear-gradient(135deg,#5B66E8,#A3ACFF);flex-shrink:0">${av}</div>
              <div><div class="font-semibold text-sm">${u.name || ''} ${u.last_name || ''}</div><div class="text-xs" style="color:#9CA3AF">${u.email || ''}</div></div>
            </div>
          </td>
          <td>${stBadge}</td>
          <td>${subBadge}</td>
          <td class="text-xs whitespace-nowrap" style="color:#9CA3AF">${u.la || '1 day ago'}</td>
          <td class="text-xs whitespace-nowrap" style="color:#9CA3AF">${u.la || '1 day ago'}</td>
          <td class="text-xs" style="color:#6B7280">${u.login_count || 0} logins</td>
          <td><button class="btn-ghost text-xs" style="padding:4px 10px" onclick="event.stopPropagation();openUserDetail(${idx})">View</button></td>
        </tr>
      `;
    }).join('');
    document.getElementById('users-prev').disabled = true;
    document.getElementById('users-next').disabled = true;
  } else {
    try {
      const params = new URLSearchParams({ page: usersPage, per_page: 20, search: usersSearch, status: usersStatus, subscription: usersSub, sort_by: usersSort, sort_dir: usersSortDir });
      const d = await apiFetch('/admin/users?' + params);
      const users = d.users || [];
      const total = d.total || 0;
      info.textContent = `Showing ${(usersPage - 1) * 20 + 1}–${Math.min(usersPage * 20, total)} of ${total}`;
      
      if (!users.length) { tbody.innerHTML = '<tr><td colspan="7" class="text-center p-8 text-sm" style="color:#9CA3AF">No users found</td></tr>'; return; }
      
      tbody.innerHTML = users.map(u => {
        const av = ((u.name || '?')[0] + (u.last_name || '?')[0]).toUpperCase();
        const stBadge = { pending: '<span class="badge badge-warn"><span class="dot dot-warn"></span>Pending</span>', approved: '<span class="badge badge-ok"><span class="dot dot-ok"></span>Verified</span>', rejected: '<span class="badge badge-err"><span class="dot dot-err"></span>Rejected</span>' }[u.status] || '<span class="badge badge-mute">Unknown</span>';
        const subBadge = u.subscription_status === 'active' ? '<span class="badge badge-ok">Active</span>' : '<span class="text-xs" style="color:#9CA3AF">—</span>';
        return `
          <tr onclick="openUserDetail(${u.id})">
            <td>
              <div class="flex items-center gap-3">
                <div style="width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;background:linear-gradient(135deg,#5B66E8,#A3ACFF);flex-shrink:0">${av}</div>
                <div><div class="font-semibold text-sm">${u.name || ''} ${u.last_name || ''}</div><div class="text-xs" style="color:#9CA3AF">${u.email || ''}</div></div>
              </div>
            </td>
            <td>${stBadge}</td>
            <td>${subBadge}</td>
            <td class="text-xs whitespace-nowrap" style="color:#9CA3AF">${fmtDate(u.submitted_at)}</td>
            <td class="text-xs whitespace-nowrap" style="color:#9CA3AF">${fmtDate(u.last_login_at)}</td>
            <td class="text-xs" style="color:#6B7280">${u.login_count || 0} logins</td>
            <td><button class="btn-ghost text-xs" style="padding:4px 10px" onclick="event.stopPropagation();openUserDetail(${u.id})">View</button></td>
          </tr>
        `;
      }).join('');
      document.getElementById('users-prev').disabled = usersPage <= 1;
      document.getElementById('users-next').disabled = usersPage * 20 >= total;
    } catch(e) { tbody.innerHTML = '<tr><td colspan="7" class="text-center p-8 text-sm" style="color:#dc2626">Failed to load users</td></tr>'; }
  }
}

function usersPagePrev() { if (usersPage > 1) { usersPage--; loadUsers(); } }
function usersPageNext() { usersPage++; loadUsers(); }
let _usersDebounce;
function onUsersSearch(v) { clearTimeout(_usersDebounce); _usersDebounce = setTimeout(() => { usersSearch = v; usersPage = 1; loadUsers(); }, 300); }
function onUsersStatus(v) { usersStatus = v; usersPage = 1; loadUsers(); }
function onUsersSub(v) { usersSub = v; usersPage = 1; loadUsers(); }

/* ── User Detail Modal ── */
async function openUserDetail(idxOrId) {
  const modal = document.getElementById('user-modal');
  document.getElementById('um-name').textContent = 'Loading…';
  document.getElementById('um-email').textContent = '';
  document.getElementById('um-badge').innerHTML = '';
  document.getElementById('um-stats').innerHTML = '';
  document.getElementById('um-rows').innerHTML = '';
  modal.classList.add('open');

  if (isMockMode) {
    const u = USERS[idxOrId];
    if (!u) return;
    const av = ((u.name || '?')[0] + (u.last_name || '?')[0]).toUpperCase();
    document.getElementById('um-avatar').textContent = av;
    document.getElementById('um-name').textContent = `${u.name} ${u.last_name}`;
    document.getElementById('um-email').textContent = u.email;
    const stBadge = { pending: '<span class="badge badge-warn"><span class="dot dot-warn"></span>Pending</span>', approved: '<span class="badge badge-ok"><span class="dot dot-ok"></span>Verified</span>', rejected: '<span class="badge badge-err"><span class="dot dot-err"></span>Rejected</span>' }[u.status] || '';
    document.getElementById('um-badge').innerHTML = stBadge;
    document.getElementById('um-stats').innerHTML = [
      ['Last Login', u.la],
      ['Login Count', u.login_count],
      ['Subscription', u.sub]
    ].map(([k, v]) => `<div class="card-inner p-3 text-center"><div class="text-xs mb-1" style="color:#9CA3AF">${k}</div><div class="text-sm font-semibold">${v}</div></div>`).join('');
    document.getElementById('um-rows').innerHTML = [
      ['Verification Status', stBadge],
      ['LinkedIn URL', u.linkedin_url ? `<a href="https://${u.linkedin_url}" target="_blank" class="text-sm" style="color:#4B52D1">${u.linkedin_url}</a>` : '—'],
      ['Signup Date', '<span class="font-medium">1 day ago</span>'],
      ['Agent Usage', `<span class="font-medium">${u.agent_usage_count} executions</span>`],
      ['Total Applications', `<span class="font-medium">${u.total_applications}</span>`],
      ['Last Activity', '<span class="font-medium">6 min ago</span>']
    ].map(([k, v]) => `<div class="flex items-center justify-between" style="padding:10px 0;border-bottom:1px solid rgba(15,16,51,0.05)"><span class="text-sm" style="color:#9CA3AF">${k}</span>${v}</div>`).join('');
  } else {
    try {
      const d = await apiFetch(`/admin/users/${idxOrId}`);
      const u = d.user;
      const av = ((u.name || '?')[0] + (u.last_name || '?')[0]).toUpperCase();
      document.getElementById('um-avatar').textContent = av;
      document.getElementById('um-name').textContent = `${u.name || ''} ${u.last_name || ''}`;
      document.getElementById('um-email').textContent = u.email || '';
      const stBadge = { pending: '<span class="badge badge-warn"><span class="dot dot-warn"></span>Pending</span>', approved: '<span class="badge badge-ok"><span class="dot dot-ok"></span>Verified</span>', rejected: '<span class="badge badge-err"><span class="dot dot-err"></span>Rejected</span>' }[u.status] || '';
      document.getElementById('um-badge').innerHTML = stBadge;
      const buyer = u.agent_buyer;
      document.getElementById('um-stats').innerHTML = [
        ['Last Login', fmtDate(u.last_login_at) || 'Never'],
        ['Login Count', u.login_count || 0],
        ['Subscription', buyer ? buyer.subscription_status : 'None']
      ].map(([k, v]) => `<div class="card-inner p-3 text-center"><div class="text-xs mb-1" style="color:#9CA3AF">${k}</div><div class="text-sm font-semibold">${v}</div></div>`).join('');
      document.getElementById('um-rows').innerHTML = [
        ['Verification Status', stBadge],
        ['LinkedIn URL', u.linkedin_url ? `<a href="${u.linkedin_url.startsWith('http') ? u.linkedin_url : 'https://' + u.linkedin_url}" target="_blank" class="text-sm" style="color:#4B52D1">${u.linkedin_url}</a>` : '—'],
        ['Signup Date', `<span class="font-medium">${fmtDate(u.submitted_at)}</span>`],
        ['Agent Usage', `<span class="font-medium">${u.agent_usage_count || 0} executions</span>`],
        ['Total Applications', `<span class="font-medium">${u.total_applications || 0}</span>`],
        ['Last Activity', `<span class="font-medium">${fmtDate(u.last_activity_at) || 'Never'}</span>`]
      ].map(([k, v]) => `<div class="flex items-center justify-between" style="padding:10px 0;border-bottom:1px solid rgba(15,16,51,0.05)"><span class="text-sm" style="color:#9CA3AF">${k}</span>${v}</div>`).join('');
    } catch(e) { document.getElementById('um-name').textContent = 'Error loading user'; }
  }
}
function closeUserModal() { document.getElementById('user-modal').classList.remove('open'); }

/* ── Audit Log ── */
let auditPage = 1, auditSearch = '', auditAction = '', auditDateFrom = '', auditDateTo = '';
async function loadAudit() {
  const container = document.getElementById('audit-list');
  container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#9CA3AF">Loading…</div>';

  if (isMockMode) {
    let data = [...AUDIT];
    if (auditSearch) {
      const q = auditSearch.toLowerCase();
      data = data.filter(e => e.admin_email.toLowerCase().includes(q) || e.target_user_name.toLowerCase().includes(q) || e.reason.toLowerCase().includes(q));
    }
    if (auditAction) {
      data = data.filter(e => e.action === auditAction);
    }
    document.getElementById('audit-info').textContent = `${data.length} entries`;
    if (!data.length) { container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#9CA3AF">No audit entries found</div>'; return; }

    const iconMap = {
      VERIFICATION_APPROVED: { bg: '#DCFCE7', bo: '#bbf7d0', sc: '#16a34a', path: '<polyline points="20 6 9 17 4 12"/>' },
      VERIFICATION_REJECTED: { bg: '#FEE2E2', bo: '#fecaca', sc: '#dc2626', path: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' }
    };
    const defaultIcon = { bg: '#F3F4F6', bo: '#E5E7EB', sc: '#6B7280', path: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' };
    const labelMap = { VERIFICATION_APPROVED: 'Approved', VERIFICATION_REJECTED: 'Rejected' };

    container.innerHTML = data.map(e => {
      const ic = iconMap[e.action] || defaultIcon;
      return `
        <div class="audit-row">
          <div class="audit-icon" style="background:${ic.bg};border:1px solid ${ic.bo}"><svg width="14" height="14" fill="none" stroke="${ic.sc}" stroke-width="2.5" viewBox="0 0 24 24">${ic.path}</svg></div>
          <div>
            <div class="text-sm" style="line-height:1.4"><span class="font-semibold">${e.admin_email}</span> <span style="color:#9CA3AF">· ${labelMap[e.action] || e.action}</span> <span class="font-semibold">${e.target_user_name}</span></div>
            <div class="text-xs mt-1" style="color:#9CA3AF">${e.reason || ''}</div>
          </div>
          <div class="text-xs whitespace-nowrap" style="color:#9CA3AF;padding-top:2px">${fmtDate(e.timestamp)}</div>
        </div>
      `;
    }).join('');
  } else {
    try {
      const params = new URLSearchParams({ page: auditPage, per_page: 50, search: auditSearch, action: auditAction, date_from: auditDateFrom, date_to: auditDateTo });
      const d = await apiFetch('/admin/audit-logs?' + params);
      const logs = d.logs || [];
      const total = d.total || 0;
      document.getElementById('audit-info').textContent = `${total} entries`;
      if (!logs.length) { container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#9CA3AF">No audit entries found</div>'; return; }
      
      const iconMap = {
        VERIFICATION_APPROVED: { bg: '#DCFCE7', bo: '#bbf7d0', sc: '#16a34a', path: '<polyline points="20 6 9 17 4 12"/>' },
        VERIFICATION_REJECTED: { bg: '#FEE2E2', bo: '#fecaca', sc: '#dc2626', path: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' },
        ADMIN_LOGIN: { bg: '#EEF0FF', bo: '#C3CAFF', sc: '#5B66E8', path: '<path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>' },
        ADMIN_CREATED: { bg: '#EEF0FF', bo: '#C3CAFF', sc: '#5B66E8', path: '<path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>' }
      };
      const defaultIcon = { bg: '#F3F4F6', bo: '#E5E7EB', sc: '#6B7280', path: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' };
      const labelMap = { VERIFICATION_APPROVED: 'Approved', VERIFICATION_REJECTED: 'Rejected', ADMIN_LOGIN: 'Logged in', ADMIN_CREATED: 'Created admin' };
      
      container.innerHTML = logs.map(e => {
        const ic = iconMap[e.action] || defaultIcon;
        const userName = e.target_user_name || e.target_user_email || '';
        return `
          <div class="audit-row">
            <div class="audit-icon" style="background:${ic.bg};border:1px solid ${ic.bo}"><svg width="14" height="14" fill="none" stroke="${ic.sc}" stroke-width="2.5" viewBox="0 0 24 24">${ic.path}</svg></div>
            <div>
              <div class="text-sm" style="line-height:1.4"><span class="font-semibold">${e.admin_email || 'System'}</span> <span style="color:#9CA3AF">· ${labelMap[e.action] || e.action}</span>${userName ? ' <span class="font-semibold">' + userName + '</span>' : ''}</div>
              <div class="text-xs mt-1" style="color:#9CA3AF">${e.reason || ''}</div>
            </div>
            <div class="text-xs whitespace-nowrap" style="color:#9CA3AF;padding-top:2px">${fmtDate(e.timestamp)}</div>
          </div>
        `;
      }).join('');
    } catch(e) { container.innerHTML = '<div class="text-center p-8 text-sm" style="color:#dc2626">Failed to load audit logs</div>'; }
  }
}

let _auditDebounce;
function onAuditSearch(v) { clearTimeout(_auditDebounce); _auditDebounce = setTimeout(() => { auditSearch = v; auditPage = 1; loadAudit(); }, 300); }
function onAuditAction(v) { auditAction = v; auditPage = 1; loadAudit(); }

/* ── User Database ── */
let _dbSource = 'localStorage';
async function getAllSignups() {
  if (isMockMode) {
    _dbSource = 'localStorage';
    try { return JSON.parse(localStorage.getItem('iitiim_pending') || '[]'); }
    catch(e) { return []; }
  } else {
    try {
      const res = await fetch(`${API}/api/users`, {
        headers: authHeaders(),
        signal: AbortSignal.timeout(1500)
      });
      if (res.ok) {
        _dbSource = 'api';
        return await res.json();
      }
    } catch(_) {}
    _dbSource = 'localStorage';
    try { return JSON.parse(localStorage.getItem('iitiim_pending') || '[]'); }
    catch(e) { return []; }
  }
}

async function renderDatabase() {
  const tbody = document.getElementById('db-tbody');
  const empty = document.getElementById('db-empty');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8 text-gray-300 text-sm">Loading…</td></tr>';
  if (empty) empty.classList.add('hidden');

  const all = await getAllSignups();
  const q = (document.getElementById('db-search')?.value || '').toLowerCase();

  const norm = all.map(u => ({
    id: u.id,
    name: u.name || '—',
    email: u.email || '—',
    passwordHash: u.password_hash || null,
    passwordRaw: u.password || null,
    li: u.linkedin_url || u.li || '',
    av: u.avatar || (u.name || '??').split(' ').map(n=>n[0]).join('').slice(0,2).toUpperCase(),
    submittedAt: u.submitted_at || u.submittedAt || null,
    status: u.status || 'pending'
  }));

  const data = q ? norm.filter(u => [u.name, u.email, u.li].some(s => s && s.toLowerCase().includes(q))) : norm;

  const srcEl = document.getElementById('db-source-badge');
  if (srcEl) {
    if (_dbSource === 'api') {
      srcEl.innerHTML = '<span style="background:#DCFCE7;color:#15803d;border:1px solid #bbf7d0;" class="badge"><span class="dot dot-ok"></span>Live — SQLite via Flask</span>';
    } else {
      srcEl.innerHTML = '<span class="badge badge-warn"><span class="dot dot-warn"></span>Offline — localStorage only</span>';
    }
  }

  document.getElementById('db-total').textContent = norm.length;
  document.getElementById('db-withpwd').textContent = norm.filter(u => u.passwordHash || (u.passwordRaw && u.passwordRaw !== '(no password)' && u.passwordRaw !== '(not set)')).length;
  document.getElementById('db-withli').textContent = norm.filter(u => u.li && u.li.trim()).length;
  document.getElementById('db-pending').textContent = norm.filter(u => u.status === 'pending').length;
  document.getElementById('db-count').textContent = `${data.length} of ${norm.length} user${norm.length !== 1 ? 's' : ''}`;

  if (!data.length) {
    tbody.innerHTML = '';
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');

  tbody.innerHTML = data.map(u => {
    const fullLi = u.li ? (u.li.startsWith('http') ? u.li : 'https://' + u.li) : '#';
    const mins = u.submittedAt ? Math.round((Date.now() - new Date(u.submittedAt).getTime()) / 60000) : -1;
    const when = mins < 0 ? '—' : mins < 1 ? 'Just now' : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.floor(mins/60)}h ago` : `${Math.floor(mins/1440)}d ago`;

    let pwdCell;
    if (u.passwordHash) {
      const short = u.passwordHash.slice(0, 12) + '…';
      pwdCell = `<span class="font-mono text-xs text-gray-500 cursor-pointer hover:text-brand-600" title="SHA-256: ${u.passwordHash}\nClick to copy" onclick="navigator.clipboard.writeText('${u.passwordHash}').then(()=>toast('Hash copied','ok'))">${short}</span> <span class="text-gray-300 text-xs ml-1">(SHA-256)</span>`;
    } else if (u.passwordRaw && u.passwordRaw !== '(no password)' && u.passwordRaw !== '(not set)') {
      pwdCell = `<span class="pwd-mask" data-val="${encodeURIComponent(u.passwordRaw)}" onclick="togglePwd(this)" title="Click to reveal" style="cursor:pointer;letter-spacing:.1em;">••••••••</span>`;
    } else {
      pwdCell = '<span class="text-gray-300 text-xs">—</span>';
    }

    const stBadge = {
      pending: '<span class="badge badge-warn"><span class="dot dot-warn"></span>Pending</span>',
      approved: '<span class="badge badge-ok"><span class="dot dot-ok"></span>Approved</span>',
      rejected: '<span class="badge badge-err"><span class="dot dot-err"></span>Rejected</span>'
    }[u.status] || '<span class="badge badge-mute">Unknown</span>';

    return `
      <tr>
        <td>
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold text-white flex-shrink-0" style="background:linear-gradient(135deg,#5B66E8,#A3ACFF);">${u.av}</div>
            <div class="font-semibold text-ink-900 text-sm">${u.name}</div>
          </div>
        </td>
        <td class="text-sm text-gray-600">${u.email}</td>
        <td>${pwdCell}</td>
        <td>${u.li ? `<a href="${fullLi}" target="_blank" rel="noopener noreferrer" class="text-xs text-brand-600 font-mono hover:underline break-all">${u.li}</a>` : '<span class="text-gray-300 text-xs">—</span>'}</td>
        <td class="text-xs text-gray-400 whitespace-nowrap">${when}</td>
        <td>${stBadge}</td>
      </tr>
    `;
  }).join('');
}

function togglePwd(el) {
  const val = decodeURIComponent(el.dataset.val || '');
  if (el.textContent === '••••••••') {
    el.textContent = val; el.style.letterSpacing = 'normal'; el.title = 'Click to hide';
  } else {
    el.textContent = '••••••••'; el.style.letterSpacing = '.1em'; el.title = 'Click to reveal';
  }
}

function exportDatabase() {
  if (_dbSource === 'api') {
    window.open(`${API}/api/export?token=${getToken()}`, '_blank');
    toast('CSV download started', 'ok');
    return;
  }
  const all = JSON.parse(localStorage.getItem('iitiim_pending') || '[]');
  if (!all.length) { toast('No data to export', 'warn'); return; }
  const header = ['Name', 'Gmail ID', 'Password (plain)', 'LinkedIn URL', 'Registered At', 'Status'];
  const rows = all.map(u => [`"${u.name}"`, `"${u.email}"`, `"${u.password || ''}"`, `"${u.li || ''}"`, `"${u.submittedAt || ''}"`, '"Pending"'].join(','));
  const csv = [header.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'iitiim_users_' + new Date().toISOString().slice(0,10) + '.csv';
  link.click();
  toast('CSV exported (localStorage)', 'ok');
}

async function clearDatabase() {
  if (!confirm('Delete ALL signup records from the database? This cannot be undone.')) return;
  if (_dbSource === 'api') {
    try {
      await fetch(`${API}/api/users`, {
        method: 'DELETE',
        headers: authHeaders()
      });
    } catch(_) {}
  }
  try { localStorage.removeItem('iitiim_pending'); } catch(e) {}
  pendingQueue = [...QUEUE];
  await renderDatabase();
  toast('Database cleared', 'warn');
}

/* ── Sub-tabs navigation ── */
function queueSubTab(status, el) {
  document.querySelectorAll('#view-queue .pg-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  loadQueue(status);
}

/* ── Helpers ── */
function fmtDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    if (diff < 604800000) return Math.floor(diff / 86400000) + 'd ago';
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch(e) { return iso; }
}

function toast(msg, type = 'ok') {
  const tc = document.getElementById('toast-wrap');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<svg width="14" height="14" fill="none" stroke="${type==='ok'?'#16a34a':'#d97706'}" stroke-width="2.5" viewBox="0 0 24 24">${type==='ok'?'<polyline points="20 6 9 17 4 12"/>':'<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/>'}</svg><span>${msg}</span>`;
  tc.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', () => {
  const saved = sessionStorage.getItem('admin_token');
  if (saved) {
    TOKEN = saved;
    try { ADMIN = JSON.parse(sessionStorage.getItem('admin_info') || '{}'); } catch(e){}
    isMockMode = (sessionStorage.getItem('admin_mode') === 'mock');
    showApp();
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('view-login').classList.contains('active')) doLogin();
  if (e.key === 'Escape') {
    closeRejectModal();
    closeUserModal();
    closeCreateAdminModal();
    closeAdminSuccessModal();
  }
});
document.addEventListener('click', e => {
  if (e.target.id === 'reject-modal') closeRejectModal();
  if (e.target.id === 'user-modal') closeUserModal();
  if (e.target.id === 'create-admin-modal') closeCreateAdminModal();
  if (e.target.id === 'admin-success-modal') closeAdminSuccessModal();
});

function toggleSidebarCollapse() {
  const isCollapsed = document.body.classList.toggle('sidebar-collapsed');
  localStorage.setItem('sidebarCollapsed', isCollapsed ? 'true' : 'false');
}

/* ── Admin Management ── */
async function loadAdmins() {
  const tbody = document.getElementById('admins-tbody');
  const empty = document.getElementById('admins-empty');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="6" class="text-center py-8 text-gray-300 text-sm">Loading…</td></tr>';
  if (empty) empty.classList.add('hidden');

  if (isMockMode) {
    tbody.innerHTML = `
      <tr>
        <td>
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-full bg-brand-500 text-white flex items-center justify-center font-bold text-xs">SA</div>
            <span class="font-semibold text-ink-900">Demo Super Admin</span>
          </div>
        </td>
        <td>admin@iitiim.ai</td>
        <td><span style="background:#EEF0FF;color:#4B52D1;" class="badge">SUPER_ADMIN</span></td>
        <td>All sections</td>
        <td>Just now</td>
        <td>Just now</td>
      </tr>
    `;
    return;
  }

  try {
    const data = await apiFetch('/admin/admins');
    if (!data.ok) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-red-500 text-sm">Failed to load admins: ${data.error || 'Unknown error'}</td></tr>`;
      return;
    }
    const list = data.admins || [];
    if (list.length === 0) {
      tbody.innerHTML = '';
      if (empty) empty.classList.remove('hidden');
      return;
    }

    const permLabels = {
      dashboard: 'Dashboard',
      queue: 'Approval Queue',
      users: 'User Directory',
      database: 'User Database',
      audit: 'Audit Log'
    };

    tbody.innerHTML = list.map(a => {
      const av = (a.name || 'A').split(' ').map(n=>n[0]).join('').slice(0,2).toUpperCase();
      const isSuperAdmin = a.role === 'SUPER_ADMIN';
      const badgeStyle = isSuperAdmin ? 'background:#EEF0FF;color:#4B52D1;' : 'background:#F3F4F6;color:#4B5563;';

      const permsList = (a.permissions || '').split(',').map(p => p.trim()).filter(Boolean);
      const permsDisplay = isSuperAdmin
        ? 'All sections'
        : permsList.map(p => permLabels[p] || p).join(', ') || 'None';

      return `
        <tr>
          <td>
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded-full text-white flex items-center justify-center font-bold text-xs" style="background:linear-gradient(135deg,#5B66E8,#A3ACFF);">${av}</div>
              <span class="font-semibold text-ink-900">${a.name || '—'}</span>
            </div>
          </td>
          <td>${a.email}</td>
          <td><span style="${badgeStyle}" class="badge">${a.role}</span></td>
          <td class="text-xs text-gray-400 max-w-[200px] truncate" title="${permsDisplay}">${permsDisplay}</td>
          <td>${fmtDate(a.created_at)}</td>
          <td>${fmtDate(a.last_login_at)}</td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-red-500 text-sm">Failed to load: ${err.message}</td></tr>`;
  }
}

function openCreateAdminModal() {
  document.getElementById('ca-name').value = '';
  document.getElementById('ca-email').value = '';
  document.querySelectorAll('.ca-perm').forEach(c => c.checked = false);
  document.getElementById('ca-error').classList.add('hidden');
  document.getElementById('create-admin-modal').classList.add('open');
}

function closeCreateAdminModal() {
  document.getElementById('create-admin-modal').classList.remove('open');
}

async function submitCreateAdmin() {
  const name = document.getElementById('ca-name').value.trim();
  const email = document.getElementById('ca-email').value.trim();
  const errEl = document.getElementById('ca-error');
  const btn = document.getElementById('ca-submit-btn');

  if (!name || !email) {
    errEl.textContent = 'Name and email are required';
    errEl.classList.remove('hidden');
    return;
  }

  const checkedPerms = [];
  document.querySelectorAll('.ca-perm:checked').forEach(c => checkedPerms.push(c.value));
  const permissions = checkedPerms.join(',');

  btn.disabled = true;
  btn.textContent = 'Creating…';
  errEl.classList.add('hidden');

  if (isMockMode) {
    btn.disabled = false;
    btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Create Admin Account`;
    closeCreateAdminModal();
    openAdminSuccessModal(email, 'mockPassword123!', true);
    return;
  }

  try {
    const res = await fetch(API + '/admin/admins', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ name, email, role: 'ADMIN', permissions })
    });
    const data = await res.json();
    if (!data.ok) {
      errEl.textContent = data.error || 'Failed to create admin';
      errEl.classList.remove('hidden');
      btn.disabled = false;
      btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Create Admin Account`;
      return;
    }

    closeCreateAdminModal();
    openAdminSuccessModal(email, data.generated_password, data.email_sent);
    loadAdmins();
  } catch (err) {
    errEl.textContent = 'Server error. Please try again.';
    errEl.classList.remove('hidden');
  }

  btn.disabled = false;
  btn.innerHTML = `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>Create Admin Account`;
}

let lastGeneratedPassword = '';

function openAdminSuccessModal(email, password, emailSent) {
  lastGeneratedPassword = password;
  document.getElementById('as-email').textContent = email;
  document.getElementById('as-password').textContent = password;
  const statusEl = document.getElementById('as-email-status');
  if (emailSent) {
    statusEl.innerHTML = '<span class="text-green-600 font-semibold flex items-center gap-1"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>Sent successfully</span>';
  } else {
    statusEl.innerHTML = '<span class="text-amber-600 font-semibold flex items-center gap-1"><svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/></svg>Skipped/Failed (logged on server)</span>';
  }
  document.getElementById('admin-success-modal').classList.add('open');
}

function closeAdminSuccessModal() {
  document.getElementById('admin-success-modal').classList.remove('open');
  lastGeneratedPassword = '';
}

function copySuccessPassword() {
  if (!lastGeneratedPassword) return;
  navigator.clipboard.writeText(lastGeneratedPassword).then(() => {
    toast('Password copied to clipboard', 'ok');
  }).catch(() => {
    toast('Failed to copy password', 'warn');
  });
}

