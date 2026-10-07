'use strict';
/* Vues complementaires : topologie, inventaire, configurations, rapport, administration, historique, notes, appareils. */
VIEWS.push('topology', 'inventory', 'configs', 'report', 'admin');
Object.assign(S, {me: null, prange: 'live', hcache: {}, repDays: 7, rep: null, repAt: 0, cfg: {ip: null, list: [], view: '', title: '', mode: ''}, audit: null, auditAt: 0});

const ROLE_LVL = {viewer: 0, tech: 1, admin: 2};
const can = r => (ROLE_LVL[S.me && S.me.role] ?? 0) >= ROLE_LVL[r];
async function api(path, opts) {
  const r = await fetch(path, Object.assign({cache: 'no-store'}, opts));
  if (r.status === 401) { location.reload(); throw new Error('auth'); }
  return r.json();
}
const fdate = t => t ? new Date(t * 1000).toLocaleString('fr-FR', {day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit'}) : '-';
const dur = s => s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : s < 172800 ? (s / 3600).toFixed(1) + ' h' : (s / 86400).toFixed(1) + ' j';

/* ---------- constructeur (indicatif, prefixes courants) ---------- */
const OUI = {
  '00:50:56': 'VMware', '00:0c:29': 'VMware', '00:05:69': 'VMware', '00:15:5d': 'Microsoft Hyper-V',
  '78:24:59': 'Alcatel-Lucent Ent.', '00:80:9f': 'Alcatel-Lucent Ent.', '6c:d6:e3': 'Cisco',
  '70:4c:a5': 'Fortinet', '38:c0:ea': 'Fortinet', '00:08:9b': 'QNAP', '24:5e:be': 'QNAP', 'b4:45:06': 'Dell',
};
function vendor(mac) {
  const m = mac.toLowerCase();
  if (OUI[m.slice(0, 8)]) return OUI[m.slice(0, 8)];
  if ('26ae'.includes(m[1])) return 'Adresse privée (mobile)';
  return '';
}

/* ---------- hooks vers app.js ---------- */
window.drawerExtra = (sw, p) => {
  const body = p.note ? `<div style="white-space:pre-wrap">${esc(p.note)}</div>` : '<div class="muted">Aucune note.</div>';
  const btn = can('tech') ? `<button class="btn alt" style="margin:8px 0 0" data-note="${esc(sw.ip + '|' + p.name)}">✎ ${p.note ? 'Modifier' : 'Ajouter'} la note</button>` : '';
  const nb = p.nb && (p.nb.name || p.nb.owner) ? `<div class="muted" style="margin-top:6px">Voisin LLDP : ${esc(p.nb.owner || p.nb.name)}</div>` : '';
  return sec('Note', body + btn + nb);
};
window.metaExtra = sw => {
  let h = '';
  if (sw.note) h += `<span>Note <b style="font-weight:500">${esc(sw.note)}</b></span>`;
  h += `<span>Config <b>${sw.last_backup ? fdate(sw.last_backup) : 'jamais sauvegardee'}</b></span>`;
  if (can('tech')) h += `<a data-note="${esc(sw.ip)}">✎ ${sw.note ? 'Modifier' : 'Ajouter'} une note</a>`;
  return h;
};

/* ---------- notes ---------- */
function openNote(key) {
  const [ip, port] = key.split('|'), sw = S.data.switches.find(s => s.ip === ip);
  if (!sw) return;
  const p = port && sw.ports.find(x => x.name === port), cur = (port ? p && p.note : sw.note) || '';
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">Note - ${esc(sw.name)}${port ? ' - port ' + esc(port) : ''}</h2><div class="muted">Visible par tous les utilisateurs (500 caracteres max).</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    <textarea id="noteText" class="note" maxlength="500" rows="5" placeholder="Ex : prise B12, salle de reunion. Baie 2, U14.">${esc(cur)}</textarea>
    <div style="display:flex;gap:8px;margin-top:10px"><button class="btn" data-notesave="${esc(key)}">Enregistrer</button><button class="btn alt" id="mclose2">Annuler</button></div>`;
  $('modal').hidden = false;
  $('noteText').focus();
}
async function saveNote(key) {
  const r = await api('/api/note', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key, text: $('noteText').value})});
  if (!r.ok) { alert('Enregistrement impossible (droits insuffisants ?)'); return; }
  closeModal(); poll();
}

/* ---------- appareils (constructeur, premiere vue, deplacements) ---------- */
RENDER.devices = function (d) {
  const q = $('devSearch').value.trim().toLowerCase(), hide = $('devHide').checked, rows = [];
  d.switches.forEach((sw, si) => sw.ports.forEach(p => {
    if (p.status !== 'up' || (hide && p.mac_count > 8)) return;
    (p.macs || []).forEach(m => rows.push({si, sw, p, mac: m.mac, vlan: m.vlan, first: m.first, moves: m.moves, ven: vendor(m.mac)}));
  }));
  const f = rows.filter(r => !q || (r.mac + ' ' + r.vlan + ' ' + r.sw.name + ' ' + r.p.name + ' ' + r.p.desc + ' ' + r.ven).toLowerCase().includes(q));
  $('devCount').textContent = `${f.length} appareil${f.length > 1 ? 's' : ''}` + (f.length > 500 ? ' (500 affiches, affinez la recherche)' : '');
  $('devTbl').innerHTML = '<colgroup><col style="width:150px"><col style="width:160px"><col style="width:60px"><col style="width:150px"><col style="width:80px"><col><col style="width:120px"><col style="width:80px"></colgroup><tr><th>Adresse MAC</th><th>Constructeur</th><th>VLAN</th><th>Switch</th><th>Port</th><th>Nom / voisin</th><th>Vu depuis</th><th>Deplace</th></tr>' +
    f.slice(0, 500).map(r => `<tr class="row" data-open="${r.si}|${r.p.n}"><td><code>${esc(r.mac)}</code></td><td>${esc(r.ven)}</td><td>${r.vlan}</td><td>${esc(r.sw.name)}</td><td class="mono">${esc(r.p.name)}</td><td>${esc(r.p.desc)}${r.p.note ? ' <span class="chip2" title="' + esc(r.p.note) + '">note</span>' : ''}</td><td>${r.first ? fdate(r.first) : '-'}</td><td class="${r.moves ? 'warn' : ''}">${r.moves ? r.moves + ' fois' : '-'}</td></tr>`).join('');
};

/* ---------- performance : live ou historique ---------- */
const _perfLive = RENDER.perf;
RENDER.perf = function (d) {
  document.querySelectorAll('#perfRange .chip').forEach(b => b.classList.toggle('on', b.dataset.p === S.prange));
  _perfLive(d);
  if (S.prange === 'live') return;
  const c = S.hcache[S.prange];
  if (!c || Date.now() - c.at > 30000) {
    if (!c || !c.loading) {
      S.hcache[S.prange] = Object.assign(c || {}, {loading: true});
      api('/api/history?range=' + S.prange).then(r => { S.hcache[S.prange] = {at: Date.now(), data: r}; if (S.view === 'perf') render(); });
    }
  }
  const h = S.hcache[S.prange] && S.hcache[S.prange].data;
  if (!h || h.demo) return;
  const ips = d.switches.map((s, i) => ({s, c: PALETTE[i % PALETTE.length], rows: h.series[s.ip] || []})).filter(x => x.rows.length > 1);
  if (!ips.length) { $('chPerfCpu').innerHTML = $('chPerfTemp').innerHTML = '<text x="20" y="30">Pas encore assez de mesures enregistrees pour cette periode.</text>'; return; }
  const times = [...new Set(ips.flatMap(x => x.rows.map(r => r[0])))].sort((a, b) => a - b);
  const ser = col => ips.map(x => { const m = new Map(x.rows.map(r => [r[0], r[col]])); let last = x.rows[0][col]; return {c: x.c, v: times.map(t => { if (m.has(t)) last = m.get(t); return last; })}; });
  $('perfLegend').innerHTML = ips.map(x => `<span><i style="background:${x.c}"></i>${esc(x.s.name)}</span>`).join('');
  const t0 = times[0], t1 = times[times.length - 1];
  lineChart($('chPerfCpu'), ser(3), {max: 100, fmt: v => Math.round(v) + '%', t0, t1, marks: [{v: 90, c: css('--crit')}]});
  lineChart($('chPerfTemp'), ser(4), {max: 100, fmt: v => Math.round(v) + '°', t0, t1, marks: [{v: 75, c: css('--crit')}, {v: 62, c: css('--warn')}]});
};

/* ---------- inventaire ---------- */
RENDER.inventory = function (d) {
  const fw = {};
  d.switches.forEach(s => { if (s.firmware) fw[s.firmware] = (fw[s.firmware] || 0) + 1; });
  const main = (Object.entries(fw).sort((a, b) => b[1] - a[1])[0] || [])[0];
  const nch = d.switches.reduce((n, s) => n + s.chassis.length, 0);
  $('invSummary').textContent = `${d.switches.length} switches - ${nch} chassis - firmware : ${Object.keys(fw).length > 1 ? Object.entries(fw).map(([k, v]) => k + ' x' + v).join(', ') + ' (versions differentes)' : (main || 'inconnu') + ' (uniforme)'}`;
  $('invTbl').innerHTML = '<colgroup><col style="width:160px"><col style="width:140px"><col style="width:140px"><col style="width:150px"><col><col style="width:110px"><col style="width:170px"></colgroup><tr><th>Switch</th><th>IP</th><th>Modele</th><th>Firmware</th><th>Chassis (numero de serie)</th><th>Uptime</th><th>Derniere sauvegarde</th></tr>' +
    d.switches.map((s, i) => `<tr class="row" data-i="${i}"><td><i class="dot ${s.reach === false ? 'crit' : 'ok'}"></i>${esc(s.name)}</td><td class="mono">${esc(s.ip)}</td><td>${esc(s.model)}</td>
      <td>${esc(s.firmware || '-')}${s.firmware && main && s.firmware !== main ? ' <span class="badge">different</span>' : ''}</td>
      <td title="${esc(s.chassis.map(c => c.model + ' ' + c.serial + ' fab. ' + c.mfg).join(' | '))}">${s.chassis.map(c => `${c.role === 'Master' ? '' : ''}#${c.id} <code>${esc(c.serial)}</code> ${esc(c.status === 'UP' ? '' : c.status)}`).join(' &nbsp; ') || '-'}</td>
      <td>${s.reach === false ? '-' : uptime(s.uptime)}</td><td>${s.last_backup ? fdate(s.last_backup) : '<span class="muted">jamais</span>'}</td></tr>`).join('');
};
function exportCsv() {
  const rows = [['Switch', 'IP', 'Modele', 'Firmware', 'Chassis', 'Role', 'Numero de serie', 'Reference', 'Revision', 'Fabrication', 'Statut']];
  S.data.switches.forEach(s => (s.chassis.length ? s.chassis : [{}]).forEach(c => rows.push([s.name, s.ip, c.model || s.model, s.firmware, c.id, c.role, c.serial, c.part, c.hw, c.mfg, c.status])));
  const csv = '﻿' + rows.map(r => r.map(v => { let t = String(v ?? ''); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; }).join(';')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  a.download = 'inventaire-switches.csv'; a.click(); URL.revokeObjectURL(a.href);
}

/* ---------- configurations ---------- */
RENDER.configs = function (d) {
  $('cfgList').innerHTML = d.switches.map((s, i) => `<button class="sitem ${i === S.sw ? 'on' : ''}" data-i="${i}"><div class="n"><span>${esc(s.name)}</span></div><div class="m">${s.last_backup ? 'sauvegarde ' + fdate(s.last_backup) : 'jamais sauvegardee'}</div></button>`).join('');
  const sw = d.switches[S.sw];
  $('cfgTitle').textContent = 'Sauvegardes - ' + sw.name;
  $('cfgBackup').hidden = !can('tech');
  syncCfgButtons();
  if (!can('tech')) { $('cfgHist').innerHTML = '<div class="pad muted">Les configurations sont reservees aux techniciens (role tech ou admin).</div>'; return; }
  if (S.cfg.ip !== sw.ip) {
    S.cfg = {ip: sw.ip, list: [], view: '', title: '', mode: '', loading: true};
    $('cfgView').textContent = ''; $('cfgViewTitle').textContent = 'Contenu';
    loadCfgList(sw.ip);
  }
  const L = S.cfg.list;
  $('cfgHist').innerHTML = S.cfg.loading ? '<div class="pad muted">Chargement...</div>' : !L.length ? '<div class="pad muted">Aucune sauvegarde. Une sauvegarde automatique est faite une fois par jour, ou cliquez sur « Sauvegarder maintenant ».</div>' :
    '<table class="tbl"><colgroup><col style="width:170px"><col style="width:90px"><col><col style="width:380px"></colgroup><tr><th>Date</th><th>Taille</th><th>Etat</th><th></th></tr>' +
    L.map((c, k) => `<tr><td>${fdate(c.t)}</td><td>${(c.size / 1024).toFixed(1)} Ko</td><td class="${k < L.length - 1 ? 'warn' : ''}">${k === L.length - 1 ? 'premiere sauvegarde' : 'modifiee par rapport a la precedente'}</td>
      <td><button class="chip" data-cfgview="${c.id}">Voir</button> <button class="chip" data-cfgdl="${c.id}">Télécharger</button> ${k < L.length - 1 ? `<button class="chip" data-cfgdiff="${L[k + 1].id}|${c.id}">Voir les changements</button>` : ''}</td></tr>`).join('') + '</table>';
};
async function loadCfgList(ip) {
  try { const l = await api('/api/configs?ip=' + encodeURIComponent(ip)); if (S.cfg.ip === ip) { S.cfg.list = Array.isArray(l) ? l : []; S.cfg.loading = false; if (S.view === 'configs') render(); } }
  catch (e) { /* session expiree : rechargement gere par api() */ }
}
async function showCfg(id) {
  const r = await api('/api/config?id=' + id);
  $('cfgViewTitle').textContent = r.error ? 'Erreur' : `Configuration - ${r.name} - ${fdate(r.t)}`;
  $('cfgView').textContent = r.error || r.text;
  S.cfg.shown = r.error ? null : {text: r.text, file: `${fileSafe(r.name)}-${stamp(r.t)}.txt`};
  syncCfgButtons();
}
async function showDiff(spec) {
  const [a, b] = spec.split('|'), r = await api(`/api/diff?a=${a}&b=${b}`);
  $('cfgViewTitle').textContent = 'Changements (rouge = retire, vert = ajoute)';
  S.cfg.shown = r.error || !r.diff ? null : {text: r.diff, file: `changements-${fileSafe(S.data.switches[S.sw].name)}-${stamp(Date.now() / 1000)}.txt`};
  syncCfgButtons();
  $('cfgView').innerHTML = r.error ? esc(r.error) : (r.diff ? r.diff.split('\n').map(l => `<span class="${l.startsWith('+') ? 'dp' : l.startsWith('-') ? 'dm' : l.startsWith('@@') ? 'dh2' : ''}">${esc(l)}</span>`).join('\n') : 'Aucune difference.');
}

/* ---------- rapport ---------- */
RENDER.report = function () {
  document.querySelectorAll('#repRange .chip').forEach(b => b.classList.toggle('on', +b.dataset.r === S.repDays));
  if (!S.rep || S.rep.days !== S.repDays || Date.now() - S.repAt > 60000) {
    if (!S.repLoading) {
      S.repLoading = true;
      api('/api/report?days=' + S.repDays).then(r => { S.rep = r; S.repAt = Date.now(); }).finally(() => { S.repLoading = false; if (S.view === 'report') RENDER.report(); });
    }
  }
  const r = S.rep;
  if (!r || r.demo) { $('repKpis').innerHTML = ''; $('repNote').textContent = r && r.demo ? 'Disponible en mode reel uniquement.' : 'Chargement...'; return; }
  $('repNote').textContent = `Periode : ${r.days} jours - mesures disponibles depuis ${dur(r.observed)}`;
  const k = (cls, l, v, s) => `<div class="kpi ${cls}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
  const minAv = Math.min(...r.switches.map(x => x.avail));
  $('repKpis').innerHTML = k('', 'Incidents', r.total, 'alertes ouvertes sur la periode') + k(r.crit ? 'crit' : 'ok', 'Critiques', r.crit, '') + k('', 'Resolution moyenne', r.total ? dur(r.mttr) : '-', 'duree moyenne d\'un incident') +
    k(minAv < 99 ? 'warn' : 'ok', 'Disponibilite mini', minAv.toFixed(2) + ' %', 'switch le moins joignable') + k('', 'Switches', r.switches.length, '') + k('', 'Ports instables', r.unstable.length, 'avec au moins une coupure');
  $('repTbl').innerHTML = '<colgroup><col><col style="width:90px"><col style="width:90px"><col style="width:130px"><col style="width:130px"></colgroup><tr><th>Switch</th><th>Critiques</th><th>Alertes</th><th>Resolution moy.</th><th>Disponibilite</th></tr>' +
    r.switches.map(x => `<tr><td>${esc(x.name)}</td><td class="${x.crit ? 'crit' : ''}">${x.crit}</td><td class="${x.warn ? 'warn' : ''}">${x.warn}</td><td>${x.crit + x.warn ? dur(x.mttr) : '-'}</td><td class="${x.avail < 99 ? 'warn' : 'ok'}">${x.avail.toFixed(2)} %</td></tr>`).join('');
  $('repUnst').innerHTML = r.unstable.length ? '<colgroup><col><col style="width:90px"><col style="width:100px"></colgroup><tr><th>Switch</th><th>Port</th><th>Coupures</th></tr>' + r.unstable.map(x => `<tr><td>${esc(x.sw)}</td><td class="mono">${esc(x.port)}</td><td class="warn">${x.n}</td></tr>`).join('') : '<tr><td class="muted">Aucune coupure de port sur la periode.</td></tr>';
  const KIND = {port_down: 'Port down', errors: 'Erreurs sur un port', util: 'Saturation de lien', flap: 'Port instable', duplex: 'Half-duplex', temp: 'Temperature', cpu: 'CPU', speed: 'Lien en 10 Mb/s', unreach: 'Switch injoignable'};
  const mx = Math.max(1, ...r.kinds.map(x => x.n));
  $('repKinds').innerHTML = r.kinds.length ? r.kinds.map(x => `<div class="dl" style="padding:6px 14px"><span>${KIND[x.kind] || x.kind}</span><b>${bar(x.n / mx * 100, 'warn')}${x.n}</b></div>`).join('') : '<div class="pad muted">Aucun incident sur la periode.</div>';
};

/* ---------- administration ---------- */
RENDER.admin = function () {
  if (!can('admin')) { $('admUsers').innerHTML = '<tr><td class="muted">Reserve aux administrateurs.</td></tr>'; return; }
  if (!S.audit || Date.now() - S.auditAt > 15000) {
    if (!S.auditLoading) {
      S.auditLoading = true;
      api('/api/audit').then(r => { S.audit = r; S.auditAt = Date.now(); }).finally(() => { S.auditLoading = false; if (S.view === 'admin') RENDER.admin(); });
    }
  }
  const a = S.audit;
  if (!a) return;
  const RL = {viewer: 'Lecture seule', tech: 'Technicien', admin: 'Administrateur'};
  $('admUsers').innerHTML = '<tr><th>Utilisateur</th><th>Role</th></tr>' + a.users.map(u => `<tr><td>${esc(u.user)}</td><td>${RL[u.role] || u.role}</td></tr>`).join('');
  const AC = {user_create: 'Compte cree', password: 'Mot de passe change', password_echec: 'Echec changement de mot de passe', login: 'Connexion', login_echec: 'Echec de connexion', logout: 'Deconnexion', note: 'Note modifiee', backup: 'Sauvegarde de config', config_view: 'Consultation de config'};
  $('admAudit').innerHTML = '<colgroup><col style="width:140px"><col style="width:110px"><col style="width:170px"><col><col style="width:110px"></colgroup><tr><th>Date</th><th>Utilisateur</th><th>Action</th><th>Detail</th><th>Adresse IP</th></tr>' +
    a.audit.map(x => `<tr><td class="mono">${fdate(x.t)}</td><td>${esc(x.user)}</td><td class="${x.action === 'login_echec' ? 'crit' : ''}">${AC[x.action] || esc(x.action)}</td><td title="${esc(x.detail)}">${esc(x.detail)}</td><td class="mono">${esc(x.ip)}</td></tr>`).join('');
};

/* ---------- configurations : copier / telecharger ---------- */
const fileSafe = x => String(x).replace(/[^A-Za-z0-9_.-]+/g, '_');
function stamp(t) {
  const d = new Date(t * 1000), z = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`;
}
function syncCfgButtons() {
  const ok = !!(S.cfg && S.cfg.shown);
  $('cfgCopy').disabled = $('cfgDl').disabled = !ok;
  $('cfgCopy').hidden = $('cfgDl').hidden = !can('tech');
}
function downloadText(o) {
  if (!o) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([o.text], {type: 'text/plain;charset=utf-8'}));
  a.download = o.file; a.click(); URL.revokeObjectURL(a.href);
}
async function copyRaw(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  const old = btn.textContent; btn.textContent = 'Copié ✓';
  setTimeout(() => { btn.textContent = old; }, 1500);
}
async function dlConfig(id) {
  const r = await api('/api/config?id=' + id);
  if (r.error) { alert('Téléchargement impossible : ' + r.error); return; }
  downloadText({text: r.text, file: `${fileSafe(r.name)}-${stamp(r.t)}.txt`});
}

/* ---------- administration : creation de compte ---------- */
async function createUser() {
  const m = $('nuMsg'), btn = $('nuCreate');
  m.className = 'nu-msg'; m.textContent = '';
  btn.disabled = true;
  try {
    const r = await api('/api/users', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: $('nuUser').value.trim(), role: $('nuRole').value, password: $('nuPw').value})});
    if (r.ok) {
      m.className = 'nu-msg ok';
      m.innerHTML = `Compte <b>${esc(r.user)}</b> créé (${esc(ROLE_LABEL[r.role] || r.role)}).` +
        (r.password ? ` Mot de passe, <b>affiché une seule fois</b> : <code>${esc(r.password)}</code> <button class="chip" data-copy="${esc(r.password)}">Copier</button>` : '');
      $('nuUser').value = ''; $('nuPw').value = '';
      S.audit = null;
      RENDER.admin();
    } else {
      m.className = 'nu-msg err';
      m.textContent = (r.error || 'Échec') + '.';
    }
  } finally { btn.disabled = false; }
}

/* ---------- clics ---------- */
window.onExtraClick = e => {
  const t = e.target;
  if (t.closest('#invCsv')) { exportCsv(); return true; }
  if (t.closest('#cfgCopy')) { if (S.cfg.shown) copyRaw(S.cfg.shown.text, $('cfgCopy')); return true; }
  if (t.closest('#cfgDl')) { downloadText(S.cfg.shown); return true; }
  if (t.closest('#nuCreate')) { createUser(); return true; }
  if (t.closest('#repPrint')) { window.print(); return true; }
  if (t.closest('#mclose2')) { closeModal(); return true; }
  let el;
  if ((el = t.closest('[data-cfgdl]'))) { dlConfig(el.dataset.cfgdl); return true; }
  if ((el = t.closest('[data-notesave]'))) { saveNote(el.dataset.notesave); return true; }
  if ((el = t.closest('[data-note]'))) { openNote(el.dataset.note); return true; }
  if ((el = t.closest('[data-cfgview]'))) { showCfg(el.dataset.cfgview); return true; }
  if ((el = t.closest('[data-cfgdiff]'))) { showDiff(el.dataset.cfgdiff); return true; }
  if (t.closest('#cfgBackup')) {
    const sw = S.data.switches[S.sw], btn = $('cfgBackup');
    btn.disabled = true; btn.textContent = 'Sauvegarde en cours...';
    api('/api/backup', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ip: sw.ip})}).then(r => {
      btn.disabled = false; btn.textContent = 'Sauvegarder maintenant';
      $('cfgViewTitle').textContent = r.error ? 'Erreur : ' + r.error : r.changed ? 'Nouvelle sauvegarde enregistree' : 'Configuration inchangee depuis la derniere sauvegarde';
      loadCfgList(sw.ip);
    });
    return true;
  }
  if ((el = t.closest('[data-r]'))) { S.repDays = +el.dataset.r; RENDER.report(); return true; }
  if ((el = t.closest('[data-p]'))) { S.prange = el.dataset.p; render(); return true; }
  return false;
};

api('/api/me').then(me => {
  S.me = me;
  document.body.dataset.role = me.role;
  $('account').textContent = '👤 ' + me.user;
  $('nav').querySelector('[data-v="admin"]').hidden = me.role !== 'admin';
  if (S.data) render();
});

{ const v = location.hash.slice(1); if (VIEWS.includes(v) && v !== S.view) { S.view = v; if (S.data) render(); } }

$('theme').addEventListener('click', () => {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('vigilia-theme', t); } catch (e) { /* stockage indisponible */ }
  if (S.data) render();
});

/* ---------- mon compte : changement de mot de passe ---------- */
const ROLE_LABEL = {viewer: 'Lecture seule', tech: 'Technicien', admin: 'Administrateur'};
function openAccount() {
  if (!S.me) return;
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">Mon compte</h2><div class="muted">${esc(S.me.user)} - ${ROLE_LABEL[S.me.role] || esc(S.me.role)}</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    <div class="mh4">Changer mon mot de passe</div>
    <label class="fld">Mot de passe actuel<input id="pwOld" type="password" autocomplete="current-password"></label>
    <label class="fld">Nouveau mot de passe<input id="pwNew" type="password" autocomplete="new-password"></label>
    <label class="fld">Confirmer le nouveau mot de passe<input id="pwNew2" type="password" autocomplete="new-password"></label>
    <div class="muted" style="font-size:12px;margin-top:6px">12 caracteres minimum, avec au moins 3 types parmi : minuscules, majuscules, chiffres, symboles. Vos autres sessions seront deconnectees.</div>
    <div id="pwMsg" class="err" role="alert" style="text-align:left"></div>
    <button class="btn" data-pwsave="1">Changer le mot de passe</button>`;
  $('modal').hidden = false;
  $('pwOld').focus();
}
async function savePassword() {
  const o = $('pwOld').value, n = $('pwNew').value, m = $('pwMsg');
  m.style.color = '';
  if (n !== $('pwNew2').value) { m.textContent = 'Les deux nouveaux mots de passe sont differents.'; return; }
  const r = await api('/api/password', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({old: o, new: n})});
  if (r.ok) { m.style.color = 'var(--ok)'; m.textContent = 'Mot de passe change.'; setTimeout(closeModal, 1500); }
  else m.textContent = (r.error || 'Echec') + '.';
}
$('account').addEventListener('click', openAccount);
const _extra = window.onExtraClick;
window.onExtraClick = e => {
  if (e.target.closest('[data-pwsave]')) { savePassword(); return true; }
  return _extra(e);
};
