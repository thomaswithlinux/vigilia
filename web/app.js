'use strict';
const $ = id => document.getElementById(id);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const SEV = {crit: 'CRITIQUE', warn: 'ALERTE'};
const VIEWS = ['overview', 'switches', 'problems', 'log', 'devices', 'poe', 'perf'];
const PALETTE = ['#2ec4b6', '#ff6b5b', '#f2b84b', '#9b8cff', '#5aa9ff', '#7bd88f', '#ff9f68', '#c792ea', '#6ee7d8'];

const S = {data: null, view: 'overview', sw: 0, port: null, sel: null, filter: 'all', lfilter: 'all', hist: {}};

/* ---------- formatage ---------- */
function bps(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + ' Gb/s';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + ' Mb/s';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + ' kb/s';
  return Math.round(v) + ' b/s';
}
function ago(t, now) {
  const s = Math.max(0, Math.round(now - t));
  if (s < 60) return s + ' s';
  if (s < 3600) return Math.floor(s / 60) + ' min';
  if (s < 86400) return Math.floor(s / 3600) + ' h ' + String(Math.floor(s % 3600 / 60)).padStart(2, '0');
  return Math.floor(s / 86400) + ' j';
}
const uptime = s => Math.floor(s / 86400) + ' j ' + Math.floor(s % 86400 / 3600) + ' h';
const hhmmss = t => new Date(t * 1000).toLocaleTimeString('fr-FR');
const lvl = (v, w, c) => v >= c ? 'crit' : v >= w ? 'warn' : 'ok';
const num = v => v == null ? '-' : Number(v).toLocaleString('fr-FR');
function bytes(v) {
  if (v == null) return '-';
  const u = ['o', 'Ko', 'Mo', 'Go', 'To']; let i = 0;
  while (v >= 1024 && i < 4) { v /= 1024; i++; }
  return v.toFixed(i ? 1 : 0) + ' ' + u[i];
}
const bar = (pct, cls) => `<span class="ubar"><i class="${cls === 'ok' ? '' : cls}" style="width:${Math.max(2, Math.min(100, pct))}%"></i></span>`;

/* ---------- donnees ---------- */
async function poll() {
  try {
    const r = await fetch('/api/state', {cache: 'no-store'});
    if (r.status === 401) { location.reload(); return; }
    S.data = await r.json();
    S.data.switches.forEach((sw, i) => sw.ports.forEach(p => {
      const k = i + ':' + p.n, h = S.hist[k] || (S.hist[k] = []);
      h.push(p.status === 'up' ? p.util : 0);
      if (h.length > 60) h.shift();
    }));
    if (S.sw >= S.data.switches.length) S.sw = 0;
    $('live').textContent = S.data.mode === 'live' ? 'donnees reelles' : 'mode demonstration';
    render();
  } catch (e) {
    $('live').textContent = 'hors ligne';
  }
}
const alertsFor = name => S.data.alerts.filter(a => a.switch === name);
function portSev(name, n) {
  let s = null;
  for (const a of S.data.alerts) if (a.switch === name && a.port === n) { if (a.sev === 'crit') return 'crit'; s = 'warn'; }
  return s;
}
function portClass(sw, p) {
  if (p.status === 'off') return 'off';
  if (p.status === 'down') return 'crit';
  return portSev(sw.name, p.n) || 'up';
}
const swSev = sw => { const al = alertsFor(sw.name); return al.some(a => a.sev === 'crit') ? 'crit' : al.length ? 'warn' : ''; };

/* ---------- navigation ---------- */
function go(v) {
  if (!VIEWS.includes(v)) v = 'overview';
  if (v !== S.view) S.port = null;
  S.view = v;
  if (location.hash !== '#' + v) history.replaceState(null, '', '#' + v);
  if (S.data) render();
}
function openPort(swIdx, n) {
  S.sw = swIdx; S.port = n;
  if (S.view !== 'switches') { S.view = 'switches'; history.replaceState(null, '', '#switches'); }
  render();
}

/* ---------- rendu global ---------- */
const RENDER = {overview: renderOverview, switches: renderSwitches, problems: renderProblems, log: renderLog, devices: renderDevices, poe: renderPoe, perf: renderPerf};
function render() {
  const d = S.data;
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + S.view));
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.v === S.view));
  renderHeader(d);
  RENDER[S.view](d);
  const sw = d.switches[S.sw];
  renderDrawer(sw, S.port && sw.ports.find(x => x.n === S.port));
}

function renderHeader(d) {
  const c = d.alerts.filter(a => a.sev === 'crit'), w = d.alerts.length - c.length, b = $('banner');
  if (c.length) { b.className = 'banner crit'; b.textContent = `${c.length} probleme${c.length > 1 ? 's' : ''} critique${c.length > 1 ? 's' : ''}` + (w ? ` - ${w} alerte${w > 1 ? 's' : ''}` : '') + ` - ${c[0].switch} : ${c[0].title}`; }
  else if (w) { b.className = 'banner warn'; b.textContent = `${w} alerte${w > 1 ? 's' : ''} a surveiller - aucun probleme critique`; }
  else { b.className = 'banner ok'; b.textContent = 'Tout fonctionne - aucun probleme detecte'; }
  $('clock').textContent = new Date(d.now * 1000).toLocaleString('fr-FR');
  const nb = $('navAlerts');
  nb.hidden = !d.alerts.length; nb.textContent = d.alerts.length; nb.className = 'nbadge' + (c.length ? ' crit' : '');
  $('sideFoot').innerHTML = `${d.switches.length} equipements<br>maj ${hhmmss(d.now)}`;
}

/* ---------- Vue d'ensemble ---------- */
function totals(d) {
  let up = 0, exp = 0, tin = 0, tout = 0, cpu = 0, temp = 0, cpuN = '', tempN = '', swOk = 0;
  d.switches.forEach(sw => {
    sw.ports.forEach(p => { if (p.status !== 'off') { exp++; if (p.status === 'up') { up++; tin += p.in; tout += p.out; } } });
    if (sw.cpu > cpu) { cpu = sw.cpu; cpuN = sw.name; }
    if (sw.temp > temp) { temp = sw.temp; tempN = sw.name; }
    if (swSev(sw) !== 'crit' && sw.reach !== false) swOk++;
  });
  return {up, exp, tin, tout, cpu, temp, cpuN, tempN, swOk};
}
function renderKpis(d) {
  const t = totals(d), c = d.alerts.filter(a => a.sev === 'crit').length, w = d.alerts.length - c, down = t.exp - t.up;
  const k = (cls, l, v, u, s) => `<div class="kpi ${cls}"><div class="l">${l}</div><div class="v">${v}<small>${u}</small></div><div class="s">${s}</div></div>`;
  const rate = bps(t.tin + t.tout).split(' ');
  $('kpis').innerHTML =
    k(t.swOk === d.switches.length ? 'ok' : 'warn', 'Switches OK', t.swOk, '/ ' + d.switches.length, 'joignables, sans critique') +
    k(down > 2 ? 'warn' : 'ok', 'Ports actifs', t.up, '/ ' + t.exp, down ? `${down} port${down > 1 ? 's' : ''} inactif${down > 1 ? 's' : ''}` : 'tous actifs') +
    k(c ? 'crit' : w ? 'warn' : 'ok', 'Problemes', c + w, '', `${c} critique${c > 1 ? 's' : ''} - ${w} alerte${w > 1 ? 's' : ''}`) +
    k('', 'Debit total', rate[0], rate[1], `entrant ${bps(t.tin)}`) +
    k(lvl(t.cpu, 75, 90), 'CPU maximum', t.cpu.toFixed(0), '%', esc(t.cpuN)) +
    k(lvl(t.temp, 62, 75), 'Temperature max', t.temp.toFixed(0), '°C', esc(t.tempN));
}
function alertRow(a, d) {
  return `<div class="alert ${a.sev}${S.sel === a.key ? ' sel' : ''}" data-key="${esc(a.key)}"><div class="bar"></div>
    <div style="min-width:0"><div class="t"><span class="sevtag">${SEV[a.sev]}</span>${esc(a.title)}</div><div class="d">${esc(a.switch)} - ${esc(a.detail)}</div></div>
    <div class="w">${ago(a.since, d.now)}</div></div>`;
}
const allOk = '<div class="allok"><b>OK</b>Aucun probleme</div>';
const evRow = e => `<div class="ev ${e.sev}"><time>${hhmmss(e.t)}</time><span>${esc(e.text)}</span></div>`;

function renderOverview(d) {
  renderKpis(d);
  $('swSummary').textContent = d.switches.length + ' equipements';
  $('swCards').innerHTML = d.switches.map((sw, i) => {
    const sev = sw.reach === false ? 'crit' : swSev(sw), al = alertsFor(sw.name), c = al.filter(a => a.sev === 'crit').length, w = al.length - c;
    const up = sw.ports.filter(p => p.status === 'up').length, tot = sw.ports.filter(p => p.status !== 'off').length;
    const rate = sw.ports.reduce((s, p) => s + (p.status === 'up' ? p.in + p.out : 0), 0);
    return `<button class="card ${sev}" data-i="${i}"><div class="n"><span>${esc(sw.name)}</span><span>${c ? `<span class="badge crit">${c}</span>` : ''}${w ? `<span class="badge">${w}</span>` : ''}${!al.length ? '<span class="badge ok">OK</span>' : ''}</span></div>
      <div class="m">${esc(sw.model)} - ${esc(sw.ip)}</div>
      <div class="strip">${sw.ports.map(p => `<i class="${portClass(sw, p) === 'off' ? '' : portClass(sw, p)}"></i>`).join('')}</div>
      <div class="st"><span><b>${up}</b>/${tot} ports</span><span>CPU <b>${sw.cpu.toFixed(0)}%</b></span><span><b>${sw.temp.toFixed(0)}</b>°C</span><span><b>${bps(rate).replace(' b/s', ' b')}</b></span></div></button>`;
  }).join('');
  $('ovCount').textContent = d.alerts.length;
  $('ovAlerts').innerHTML = d.alerts.length ? d.alerts.map(a => alertRow(a, d)).join('') : allOk;
  $('ovEvents').innerHTML = d.events.slice(0, 40).map(evRow).join('');
  const n = Math.min(...d.switches.map(s => s.hist.length));
  const sum = col => Array.from({length: n}, (_, k) => d.switches.reduce((a, s) => a + s.hist[s.hist.length - n + k][col], 0));
  const h0 = d.switches[0].hist;
  lineChart($('chOv'), [{v: sum(1), c: css('--s-in'), area: true}, {v: sum(2), c: css('--s-out'), area: true}], {fmt: v => bps(v).replace(' b/s', ' b'), t0: h0[h0.length - n][0], t1: h0[h0.length - 1][0]});
  const li = sum(1)[n - 1], lo = sum(2)[n - 1];
  $('ovTrafficNow').innerHTML = `<span style="color:var(--s-in)">entrant ${bps(li)}</span> - <span style="color:var(--s-out)">sortant ${bps(lo)}</span>`;
}

/* ---------- Switches ---------- */
function renderSwitches(d) {
  const sw = d.switches[S.sw];
  $('swList').innerHTML = d.switches.map((s, i) => {
    const sev = s.reach === false ? 'crit' : swSev(s), al = alertsFor(s.name);
    const up = s.ports.filter(p => p.status === 'up').length;
    return `<button class="sitem ${sev}${i === S.sw ? ' on' : ''}" data-i="${i}"><div class="n"><span>${esc(s.name)}</span>${al.length ? `<span class="badge ${sev}">${al.length}</span>` : ''}</div><div class="m">${esc(s.ip)} - ${up} ports actifs</div></button>`;
  }).join('');
  $('swTitle').textContent = `${sw.name} - ${sw.model}`;
  const sb = $('sshBtn'), sal = alertsFor(sw.name);
  sb.dataset.ssh = S.sw + '||';
  sb.className = 'btn-ssh' + (sal.some(a => a.sev === 'crit') ? ' crit' : sal.length ? ' alert' : '');
  $('swMeta').innerHTML = `<span>IP <b class="mono">${esc(sw.ip)}</b></span><span>Lieu <b>${esc(sw.loc || '-')}</b></span><span>Uptime <b>${uptime(sw.uptime)}</b></span><span>CPU <b>${sw.cpu.toFixed(0)} %</b></span><span>Memoire <b>${sw.mem.toFixed(0)} %</b></span><span>Temp. <b>${sw.temp.toFixed(0)} °C</b></span>` +
    (sw.poe_max ? `<span>PoE <b>${sw.poe.toFixed(0)} / ${sw.poe_max} W</b></span>` : sw.poe > 0 ? `<span>PoE <b>${sw.poe.toFixed(0)} W</b></span>` : '') +
    (sw.fans.length ? `<span>Ventilateurs <b>${sw.fans.join(' / ')} tr/min</b></span>` : '') +
    (sw.reach === false ? '<span style="color:var(--crit)"><b>INJOIGNABLE - donnees figees</b></span>' : '') + (window.metaExtra ? window.metaExtra(sw) : '');
  renderFront(sw);
  const h = sw.hist, last = h[h.length - 1], t0 = h[0][0], t1 = last[0];
  lineChart($('chTraffic'), [{v: h.map(r => r[1]), c: css('--s-in'), area: true}, {v: h.map(r => r[2]), c: css('--s-out'), area: true}], {fmt: v => bps(v).replace(' b/s', ' b'), t0, t1});
  $('trafficNow').innerHTML = `<span style="color:var(--s-in)">in ${bps(last[1])}</span> <span style="color:var(--s-out)">out ${bps(last[2])}</span>`;
  lineChart($('chCpu'), [{v: h.map(r => r[3]), c: css('--s-in'), area: true}, {v: h.map(r => r[4]), c: css('--warn')}], {max: 100, fmt: v => Math.round(v), t0, t1, marks: [{v: 90, c: css('--crit')}]});
  $('cpuNow').innerHTML = `<span style="color:var(--s-in)">CPU ${last[3].toFixed(0)} %</span> <span style="color:var(--warn)">${last[4].toFixed(0)} °C</span>`;
  const rows = sw.ports.filter(p => p.status === 'up').sort((a, b) => b.util - a.util).slice(0, 12);
  $('top').innerHTML = '<colgroup><col style="width:74px"><col><col style="width:118px"></colgroup><tr><th>Port</th><th>Equipement</th><th>Charge</th></tr>' + rows.map(p => {
    const c = lvl(p.util * 100, 85, 95);
    return `<tr class="row" data-n="${p.n}"><td class="mono">${esc(p.name)}</td><td>${esc(p.desc || p.mac)}</td><td>${bar(p.util * 100, c)}${(p.util * 100).toFixed(0)}%</td></tr>`;
  }).join('');
}

function renderFront(sw) {
  const groups = {};
  sw.ports.forEach(p => (groups[p.name.split('/')[0]] = groups[p.name.split('/')[0]] || []).push(p));
  const keys = Object.keys(groups), th = keys.length > 1 ? 30 : 42;
  $('ports').innerHTML = keys.map(k => {
    const ps = groups[k];
    return `<div class="pgroup">${keys.length > 1 ? `<div class="gl">Chassis ${k}</div>` : ''}<div class="pgrid" style="--cols:${Math.ceil(ps.length / 2)};--th:${th}px">${ps.map(p => {
      const cls = portClass(sw, p);
      return `<div class="port ${cls}${p.role === 'uplink' ? ' sfp' : ''}${S.port === p.n ? ' sel' : ''}${p.note ? ' hasnote' : ''}" data-n="${p.n}">${p.name.split('/').pop()}${th > 30 ? `<span class="r">${p.role === 'uplink' ? p.speed : p.status === 'up' ? Math.round(p.util * 100) + '%' : ''}</span>` : ''}${p.status === 'up' ? `<i class="u" style="width:${Math.max(3, p.util * 100)}%"></i>` : ''}</div>`;
    }).join('')}</div></div>`;
  }).join('');
}

/* ---------- Problemes ---------- */
function renderProblems(d) {
  const list = d.alerts.filter(a => S.filter === 'all' || a.sev === S.filter);
  const c = d.alerts.filter(a => a.sev === 'crit').length;
  $('probSummary').textContent = `${c} critique${c > 1 ? 's' : ''} - ${d.alerts.length - c} alerte${d.alerts.length - c > 1 ? 's' : ''}`;
  document.querySelectorAll('#sevFilter .chip').forEach(b => b.classList.toggle('on', b.dataset.f === S.filter));
  $('alerts').innerHTML = list.length ? list.map(a => alertRow(a, d)).join('') : allOk;
  const a = list.find(x => x.key === S.sel) || list[0];
  if (!a) { $('alertDetail').innerHTML = '<div class="muted">Aucun probleme a afficher.</div>'; return; }
  const si = d.switches.findIndex(s => s.name === a.switch), sw = d.switches[si], p = a.port && sw ? sw.ports.find(x => x.n === a.port) : null;
  $('alertDetail').innerHTML = `<p class="diag-title"><span class="sevtag" style="font-size:11px">${SEV[a.sev]}</span> ${esc(a.title)}</p>
    <div class="muted">${esc(a.switch)}${p ? ' - port ' + esc(p.name) : ''} - depuis ${ago(a.since, d.now)} - ${esc(a.detail)}</div>
    <div class="cause ${a.sev}"><b>Cause probable</b><div>${esc(a.cause)}</div></div>
    <b>Verifications</b><ul class="steps">${a.steps.map(s => `<li><code>${esc(s)}</code></li>`).join('')}</ul>
    ${p ? `<div class="dl" style="margin-top:12px"><span>Equipement</span><b>${esc(p.desc || '-')}</b></div><div class="dl"><span>MAC</span><b class="mono">${esc(p.mac || '-')}</b></div><div class="dl"><span>Charge</span><b>${(p.util * 100).toFixed(0)} %</b></div><div class="dl"><span>Erreurs/s</span><b>${p.err.toFixed(0)}</b></div>
    <button class="btn" data-open="${si}|${p.n}">Ouvrir le detail du port</button>` : sw ? `<button class="btn" data-i="${si}">Voir le switch</button>` : ''}
    ${sw ? `<button class="btn alt" data-ssh="${si}|${esc(a.key)}|${p ? esc(p.name) : ''}">&gt;_ Se connecter en SSH</button>` : ''}`;
}

/* ---------- Journal ---------- */
function renderLog(d) {
  const q = $('logSearch').value.trim().toLowerCase();
  document.querySelectorAll('#logFilter .chip').forEach(b => b.classList.toggle('on', b.dataset.l === S.lfilter));
  const rows = d.events.filter(e => (S.lfilter === 'all' || e.sev === S.lfilter) && (!q || e.text.toLowerCase().includes(q)));
  $('logCount').textContent = `${rows.length} evenement${rows.length > 1 ? 's' : ''} depuis le demarrage du serveur`;
  const tag = {crit: ['CRITIQUE', 'crit'], warn: ['ALERTE', 'warn'], ok: ['RESOLU', 'ok']};
  $('logTbl').innerHTML = '<colgroup><col style="width:110px"><col style="width:110px"><col></colgroup><tr><th>Heure</th><th>Niveau</th><th>Message</th></tr>' +
    rows.map(e => `<tr><td class="mono">${hhmmss(e.t)}</td><td class="${tag[e.sev][1]}">${tag[e.sev][0]}</td><td title="${esc(e.text)}">${esc(e.text)}</td></tr>`).join('');
}

/* ---------- Appareils ---------- */
function renderDevices(d) {
  const q = $('devSearch').value.trim().toLowerCase(), hide = $('devHide').checked;
  const rows = [];
  d.switches.forEach((sw, si) => sw.ports.forEach(p => {
    if (p.status !== 'up' || (hide && p.mac_count > 8)) return;
    (p.macs || []).forEach(m => rows.push({si, sw, p, mac: m.mac, vlan: m.vlan}));
  }));
  const f = rows.filter(r => !q || (r.mac + ' ' + r.vlan + ' ' + r.sw.name + ' ' + r.p.name + ' ' + r.p.desc).toLowerCase().includes(q));
  $('devCount').textContent = `${f.length} appareil${f.length > 1 ? 's' : ''}` + (f.length > 500 ? ' (500 affiches, affinez la recherche)' : '');
  $('devTbl').innerHTML = '<colgroup><col style="width:170px"><col style="width:70px"><col style="width:170px"><col style="width:90px"><col><col style="width:90px"></colgroup><tr><th>Adresse MAC</th><th>VLAN</th><th>Switch</th><th>Port</th><th>Nom / voisin</th><th>Vitesse</th></tr>' +
    f.slice(0, 500).map(r => `<tr class="row" data-open="${r.si}|${r.p.n}"><td><code>${esc(r.mac)}</code></td><td>${r.vlan}</td><td>${esc(r.sw.name)}</td><td class="mono">${esc(r.p.name)}</td><td>${esc(r.p.desc)}</td><td>${esc(r.p.speed)}</td></tr>`).join('');
}

/* ---------- PoE ---------- */
function renderPoe(d) {
  let total = 0;
  const rows = [];
  d.switches.forEach((sw, si) => sw.ports.forEach(p => { if (p.status === 'up' && p.poe > 0) { total += p.poe; rows.push({si, sw, p}); } }));
  rows.sort((a, b) => b.p.poe - a.p.poe);
  const k = (cls, l, v, s) => `<div class="kpi ${cls}"><div class="l">${l}</div><div class="v">${v}<small>W</small></div><div class="s">${s}</div></div>`;
  $('poeKpis').innerHTML = k('', 'Total PoE', total.toFixed(0), `${rows.length} ports alimentes`) + d.switches.filter(s => s.poe > 0).map(s => k('', esc(s.name), s.poe.toFixed(0), esc(s.ip))).join('');
  $('poeCount').textContent = rows.length + ' ports';
  const mx = rows.length ? rows[0].p.poe : 1;
  $('poeTbl').innerHTML = '<colgroup><col style="width:170px"><col style="width:80px"><col><col style="width:120px"><col style="width:180px"><col style="width:90px"></colgroup><tr><th>Switch</th><th>Port</th><th>Equipement</th><th>Etat</th><th>Consommation</th><th>Maximum</th></tr>' +
    rows.map(({si, sw, p}) => `<tr class="row" data-open="${si}|${p.n}"><td>${esc(sw.name)}</td><td class="mono">${esc(p.name)}</td><td>${esc(p.desc || p.mac)}</td><td class="ok">${esc(p.poe_status)}</td><td>${bar(p.poe / mx * 100, 'ok')}${p.poe.toFixed(1)} W</td><td>${p.poe_max} W</td></tr>`).join('');
}

/* ---------- Performance ---------- */
function renderPerf(d) {
  $('perfTbl').innerHTML = '<colgroup><col style="width:170px"><col style="width:135px"><col style="width:100px"><col><col><col><col style="width:210px"><col style="width:115px"></colgroup><tr><th>Switch</th><th>IP</th><th>Uptime</th><th>CPU</th><th>Memoire</th><th>Temperature</th><th>Debit (in / out)</th><th>Ports actifs</th></tr>' +
    d.switches.map((sw, i) => {
      const tin = sw.ports.reduce((s, p) => s + (p.status === 'up' ? p.in : 0), 0), tout = sw.ports.reduce((s, p) => s + (p.status === 'up' ? p.out : 0), 0);
      const up = sw.ports.filter(p => p.status === 'up').length;
      return `<tr class="row" data-i="${i}"><td><i class="dot ${sw.reach === false ? 'crit' : swSev(sw) || 'ok'}"></i>${esc(sw.name)}</td><td class="mono">${esc(sw.ip)}</td><td>${sw.reach === false ? '-' : uptime(sw.uptime)}</td>
        <td>${bar(sw.cpu, lvl(sw.cpu, 75, 90))}${sw.cpu.toFixed(0)} %</td><td>${bar(sw.mem, lvl(sw.mem, 80, 92))}${sw.mem.toFixed(0)} %</td><td>${bar(sw.temp, lvl(sw.temp, 62, 75))}${sw.temp.toFixed(0)} °C</td>
        <td>${bps(tin)} / ${bps(tout)}</td><td>${up} / ${sw.ports.length}</td></tr>`;
    }).join('');
  const live = d.switches.map((s, i) => ({s, c: PALETTE[i % PALETTE.length]})).filter(x => x.s.reach !== false && x.s.hist.length > 2);
  if (!live.length) return;
  const n = Math.min(...live.map(x => x.s.hist.length)), h0 = live[0].s.hist;
  const t0 = h0[h0.length - n][0], t1 = h0[h0.length - 1][0];
  const ser = col => live.map(x => ({v: x.s.hist.slice(-n).map(r => r[col]), c: x.c}));
  $('perfLegend').innerHTML = live.map(x => `<span><i style="background:${x.c}"></i>${esc(x.s.name)}</span>`).join('');
  lineChart($('chPerfCpu'), ser(3), {max: 100, fmt: v => Math.round(v) + '%', t0, t1, marks: [{v: 90, c: css('--crit')}]});
  lineChart($('chPerfTemp'), ser(4), {max: 100, fmt: v => Math.round(v) + '°', t0, t1, marks: [{v: 75, c: css('--crit')}, {v: 62, c: css('--warn')}]});
}

/* ---------- graphiques (SVG a la taille reelle de la zone) ---------- */
function lineChart(svg, series, o) {
  const W = svg.clientWidth, H = svg.clientHeight, n = series[0].v.length;
  if (W < 80 || H < 60 || n < 2) return;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const R = 8, T = 10, B = 18;
  const max = o.max || Math.max(1, ...series.flatMap(s => s.v)) * 1.15;
  const L = Math.max(...[0, 1, 2, 3, 4].map(i => String(o.fmt(max * i / 4)).length)) * 6.2 + 14;
  const X = i => L + i / (n - 1) * (W - L - R), Y = v => T + (1 - v / max) * (H - T - B);
  let g = '';
  const rows = H > 140 ? 4 : 2;
  for (let i = 0; i <= rows; i++) {
    const v = max * i / rows, y = Y(v);
    g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" style="stroke:var(--border)"/><text x="${L - 6}" y="${y + 3}" text-anchor="end">${o.fmt(v)}</text>`;
  }
  (o.marks || []).forEach(m => { const y = Y(m.v); g += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${m.c}" stroke-dasharray="4 4" opacity=".6"/>`; });
  const mins = Math.max(1, Math.round((o.t1 - o.t0) / 60)), span = mins < 120 ? mins + ' min' : mins < 2880 ? Math.round(mins / 60) + ' h' : Math.round(mins / 1440) + ' j';
  g += `<text x="${L}" y="${H - 4}">-${span}</text><text x="${W - R}" y="${H - 4}" text-anchor="end">maintenant</text>`;
  for (const s of series) {
    const pts = s.v.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
    if (s.area) g += `<polygon points="${L},${Y(0)} ${pts} ${X(n - 1)},${Y(0)}" fill="${s.c}" opacity=".16"/>`;
    g += `<polyline points="${pts}" fill="none" stroke="${s.c}" stroke-width="1.8" stroke-linejoin="round"/>`;
  }
  svg.innerHTML = g;
}

/* ---------- panneau lateral : detail d'un port ---------- */
const dcache = {};
function fetchDetail(sw, p) {
  const key = sw.ip + '|' + p.name, c = dcache[key];
  if (c && (c.loading || Date.now() - c.t < 10000)) return c;
  const e = dcache[key] = {t: Date.now(), loading: true, data: c ? c.data : null};
  fetch('/api/port?ip=' + encodeURIComponent(sw.ip) + '&port=' + encodeURIComponent(p.name), {cache: 'no-store'})
    .then(r => r.json()).then(d => { e.data = d; })
    .catch(() => { e.data = {error: 'requete echouee'}; })
    .finally(() => { e.loading = false; e.t = Date.now(); if (S.data && S.port) { const s = S.data.switches[S.sw]; renderDrawer(s, s.ports.find(x => x.n === S.port)); } });
  return e;
}
const kv = (k, v, cls) => `<div class="dl"><span>${k}</span><b class="${cls || ''}">${v == null || v === '' ? '-' : v}</b></div>`;
const sec = (t, body) => `<section class="dsec"><h4>${t}</h4>${body}</section>`;
function spark(vals, color) {
  const w = 300, h = 42, n = vals.length;
  if (n < 2) return '';
  const pts = vals.map((v, i) => `${(i / (n - 1) * w).toFixed(1)},${(h - 3 - Math.min(1, v) * (h - 6)).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6"/></svg>`;
}

function renderDrawer(sw, p) {
  const el = $('drawer');
  if (!p) { el.classList.remove('open'); el._h = null; return; }
  const ent = fetchDetail(sw, p), d = ent.data;
  const al = alertsFor(sw.name).filter(a => a.port === p.n);
  const st = {up: ['Actif', 'ok'], down: ['DOWN', 'crit'], off: ['Libre', '']}[p.status];
  let h = `<div class="dh"><div><div class="dt">Port ${esc(p.name)} <span class="pill ${st[1]}">${st[0]}</span></div>
      <div class="muted">${esc(sw.name)} - ${esc(sw.model)} - ${esc(sw.ip)}</div></div><button class="ghost" id="dclose" aria-label="Fermer">✕</button></div>
    <div class="dname">${esc(p.desc || 'Aucun nom / port libre')}</div>
    <button class="btn alt" style="margin:0 0 4px" data-ssh="${S.sw}||${esc(p.name)}">&gt;_ Se connecter en SSH</button>`;
  h += al.map(a => `<div class="cause ${a.sev}"><b>${esc(a.title)}</b> <span class="muted">${esc(a.detail)}</span><div style="margin-top:4px">${esc(a.cause)}</div><ul class="steps">${a.steps.map(s => `<li><code>${esc(s)}</code></li>`).join('')}</ul></div>`).join('');

  const macs = (p.macs || []).map(m => `<div class="mac"><code>${esc(m.mac)}</code><span class="chip2">VLAN ${m.vlan}</span></div>`).join('');
  h += sec('Appareils connectes' + (p.mac_count ? ` <span class="count">${p.mac_count}</span>` : ''),
    p.status !== 'up' ? '<div class="muted">Aucun appareil : le lien est inactif.</div>'
      : macs ? macs + (p.mac_count > (p.macs || []).length ? `<div class="muted">+ ${p.mac_count - p.macs.length} autres adresses</div>` : '')
        + (p.mac_count > 3 ? '<div class="muted" style="margin-top:6px">Plusieurs adresses : le port mene a un autre switch, une borne Wi-Fi ou un telephone avec PC.</div>' : '')
        : '<div class="muted">Aucune adresse MAC apprise (equipement silencieux ou apprentissage en cours).</div>');
  h += sec('Trafic', kv('Entrant', bps(p.in)) + kv('Sortant', bps(p.out)) + kv('Charge', (p.util * 100).toFixed(1) + ' %', lvl(p.util * 100, 85, 95)) + (S.hist[S.sw + ':' + p.n] ? spark(S.hist[S.sw + ':' + p.n], css('--s-in')) : ''));

  const poe = p.poe_status ? sec('Alimentation PoE', kv('Etat', esc(p.poe_status), p.poe_status === 'Powered On' ? 'ok' : '') + kv('Consommation', p.poe.toFixed(1) + ' W') + kv('Maximum', p.poe_max + ' W')) : '';
  const detailBody = !d ? '<div class="muted">Chargement depuis le switch...</div>' : d.demo ? '<div class="muted">Mode simulation : pas de detail.</div>' : d.error ? `<div class="x crit">${esc(d.error)}</div>` : null;
  if (detailBody) {
    h += sec('Liaison', kv('Etat', st[0], st[1]) + kv('Vitesse', p.speed) + kv('Duplex', p.duplex, p.duplex === 'half' && p.status === 'up' ? 'warn' : '') + kv('Coupures depuis le demarrage', p.flaps)) + poe + sec('Details', detailBody);
  } else {
    h += sec('Liaison', kv('Etat', esc(d.oper), d.oper === 'up' ? 'ok' : 'crit') + (d.reason && d.reason !== 'None' ? kv('Raison', esc(d.reason), 'warn') : '') +
      kv('Vitesse', d.oper === 'up' ? esc(p.speed) : '-') + kv('Duplex', esc(d.duplex)) + kv('Auto-negociation', esc(d.autoneg)) + kv('Type', esc(d.type)) + (d.sfp && d.sfp !== 'N/A' ? kv('SFP / XFP', esc(d.sfp)) : '') +
      kv('Trame maximale', d.frame ? d.frame + ' o' : '-') + kv('Dernier changement', esc(d.last_change)) + kv('Changements d\'etat', num(d.changes), d.changes > 20 ? 'warn' : '') + kv('MAC du port (switch)', `<code>${esc(d.port_mac)}</code>`));
    h += poe;
    h += sec('VLAN', d.vlans.length ? d.vlans.map(v => `<div class="mac"><code>VLAN ${v.vlan}</code><span class="chip2">${esc(v.type)}</span><span class="muted">${esc(v.state)}</span></div>`).join('') : '<div class="muted">Aucun VLAN.</div>');
    if (d.lldp) h += sec('Voisin LLDP', kv('Nom', esc(d.lldp.name)) + kv('Port distant', esc(d.lldp.port)) + kv('IP de gestion', esc(d.lldp.ip)) + kv('Chassis', `<code>${esc(d.lldp.chassis)}</code>`) + kv('Fonctions', esc(d.lldp.caps)) + (d.lldp.descr ? `<div class="muted" style="margin-top:4px">${esc(d.lldp.descr)}</div>` : ''));
    const r = d.rx, t = d.tx, bad = (v, c) => v > 0 ? c : '';
    h += sec('Erreurs', kv('Erreurs / seconde', p.err.toFixed(1), lvl(p.err, 5, 40)) + kv('CRC recus', num(r.crc), bad(r.crc, 'warn')) + kv('Trames en erreur (Rx)', num(r.errors), bad(r.errors, 'warn')) +
      kv('Trames perdues (Rx)', num(r.lost), bad(r.lost, 'warn')) + kv('Trop courtes / trop longues', num(r.undersize) + ' / ' + num(r.oversize)) + kv('Alignement', num(r.align), bad(r.align, 'warn')) +
      kv('Erreurs envoi (Tx)', num(t.errors), bad(t.errors, 'warn')) + kv('Collisions', num(t.collisions) + ' (tardives ' + num(t.late) + ')', bad(t.collisions, 'warn')));
    h += sec('Compteurs cumules', kv('Octets recus', bytes(r.bytes)) + kv('Octets envoyes', bytes(t.bytes)) + kv('Unicast Rx / Tx', num(r.unicast) + ' / ' + num(t.unicast)) + kv('Broadcast Rx / Tx', num(r.broadcast) + ' / ' + num(t.broadcast)) + kv('Multicast Rx / Tx', num(r.multicast) + ' / ' + num(t.multicast)));
  }
  h += window.drawerExtra ? window.drawerExtra(sw, p) : '';
  el.classList.add('open');
  if (el._h !== h) { const top = el.scrollTop; el.innerHTML = h; el.scrollTop = top; el._h = h; }
}

/* ---------- fenetre SSH ---------- */
function closeModal() { $('modal').hidden = true; }
function cmdRow(text, small) {
  return `<div class="cmd${small ? ' small' : ''}"><code>${esc(text)}</code><button type="button" data-copy="${esc(text)}">Copier</button></div>`;
}
function openSsh(spec) {
  const [i, key, port] = spec.split('|'), sw = S.data.switches[+i];
  if (!sw) return;
  const user = S.data.ssh_user || 'admin', al = alertsFor(sw.name), a = key && al.find(x => x.key === key);
  const cmds = [];
  if (a) a.steps.filter(s => s.startsWith('show ')).forEach(s => cmds.push(s));
  if (port && !cmds.some(c => c.includes(port))) cmds.push(`show interfaces ${port}`);
  ['show health', 'show interfaces status'].forEach(c => { if (!cmds.includes(c)) cmds.push(c); });
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">Connexion SSH - ${esc(sw.name)}</h2><div class="muted">${esc(sw.model)} - ${esc(sw.ip)}${sw.loc ? ' - ' + esc(sw.loc) : ''}</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    <div class="keepass"><span class="ic">🔑</span><div><b>Le mot de passe se trouve dans KeePass.</b><br>Il n'est jamais affiche ni enregistre ici : copie la commande, colle-la dans un terminal, puis saisis le mot de passe depuis KeePass.</div></div>
    <div class="mh4">1. Commande de connexion</div>${cmdRow(`ssh ${user}@${sw.ip}`)}
    ${al.length ? `<div class="mh4">Problemes sur ce switch (${al.length})</div>${al.slice(0, 6).map(x => `<div class="malert"><span class="sevtag">${SEV[x.sev]}</span>${esc(x.title)} <span class="muted">- ${esc(x.detail)}</span></div>`).join('')}${al.length > 6 ? `<div class="muted">+ ${al.length - 6} autres</div>` : ''}` : ''}
    <div class="mh4">2. Commandes utiles une fois connecte (lecture seule)</div>${cmds.map(c => cmdRow(c, true)).join('')}`;
  $('modal').hidden = false;
  const first = $('mbox').querySelector('[data-copy]'); if (first) first.focus();
}
async function copyText(btn) {
  const text = btn.dataset.copy;
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { ta.remove(); }
  }
  const old = btn.textContent; btn.textContent = 'Copie ✓'; btn.classList.add('done');
  setTimeout(() => { btn.textContent = old; btn.classList.remove('done'); }, 1500);
}
$('modal').addEventListener('click', e => { if (e.target.id === 'modal' || e.target.closest('#mclose')) closeModal(); });

/* ---------- interactions ---------- */
document.addEventListener('click', e => {
  if (window.onExtraClick && S.data && window.onExtraClick(e)) return;
  const cp = e.target.closest('[data-copy]');
  if (cp) { copyText(cp); return; }
  const ssh = e.target.closest('[data-ssh]');
  if (ssh && S.data) { openSsh(ssh.dataset.ssh); return; }
  if (e.target.closest('#dclose')) { S.port = null; render(); return; }
  const t = e.target.closest('[data-v],[data-open],[data-key],[data-i],[data-n],[data-f],[data-l]');
  if (!t || !S.data) return;
  const d = t.dataset;
  if (d.v) return go(d.v);
  if (d.open) { const [i, n] = d.open.split('|'); return openPort(+i, +n); }
  if (d.f) { S.filter = d.f; return render(); }
  if (d.l) { S.lfilter = d.l; return render(); }
  if (d.key) {
    S.sel = d.key;
    if (S.view !== 'problems') return go('problems');
    return render();
  }
  if (d.i !== undefined) {
    S.sw = +d.i; S.port = null;
    if (S.view !== 'switches' && S.view !== 'configs') return go('switches');
    return render();
  }
  if (d.n) { S.port = S.port === +d.n ? null : +d.n; return render(); }
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (!$('modal').hidden) { closeModal(); return; }
  if (S.port && S.data) { S.port = null; render(); }
});
['logSearch', 'devSearch', 'devHide'].forEach(id => $(id).addEventListener('input', () => S.data && render()));
window.addEventListener('resize', () => S.data && render());
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v !== S.view) go(v); });

const tip = $('tip');
$('ports').addEventListener('mousemove', e => {
  const el = e.target.closest('.port');
  if (!el) { tip.hidden = true; return; }
  const p = S.data.switches[S.sw].ports.find(x => x.n === +el.dataset.n);
  tip.innerHTML = `<b>${esc(p.name)}</b> ${esc(p.desc || 'libre')}${p.note ? '<br><i>' + esc(p.note) + '</i>' : ''}<br>${p.status === 'up' ? `${p.mac ? '<code>' + esc(p.mac) + (p.mac_count > 1 ? ' +' + (p.mac_count - 1) : '') + '</code><br>' : ''}${p.speed} ${p.duplex}${p.vlan ? ' - VLAN ' + p.vlan : ''}<br>in ${bps(p.in)} / out ${bps(p.out)}` : p.status === 'down' ? '<span style="color:var(--crit)">LIEN DOWN</span>' : 'non utilise'}`;
  tip.hidden = false;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 300) + 'px';
  tip.style.top = Math.min(e.clientY + 16, innerHeight - 110) + 'px';
});
$('ports').addEventListener('mouseleave', () => { tip.hidden = true; });
$('logout').addEventListener('click', async () => { await fetch('/logout', {method: 'POST'}); location.reload(); });

S.view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
poll();
setInterval(poll, 2000);
