'use strict';
/* Serveurs : hotes VMware ESXi, machines virtuelles et datastores (supervision en lecture seule). */
VIEWS.push('servers');
Object.assign(S, {srv: null, srvHost: '', srvFilter: 'all', srvAt: 0});

const GB = 1024 ** 3;
const gb = v => v >= 1024 * GB ? (v / 1024 / GB).toFixed(1) + ' To' : (v / GB).toFixed(v >= 100 * GB ? 0 : 1) + ' Go';
const mb = v => v >= 1024 ? (v / 1024).toFixed(v >= 10240 ? 0 : 1) + ' Go' : Math.round(v) + ' Mo';
const POWER = {poweredOn: ['Allumee', 'ok'], poweredOff: ['Eteinte', ''], suspended: ['Suspendue', 'warn']};
const TOOLS = {guestToolsRunning: 'OK', guestToolsNotRunning: 'arretes', toolsOk: 'OK', toolsOld: 'anciens', toolsNotRunning: 'arretes', toolsNotInstalled: 'absents'};
const hostSev = h => {
  if (h.reach === false) return 'crit';
  const al = S.data ? S.data.alerts.filter(a => a.switch === h.name) : [];
  return al.some(a => a.sev === 'crit') ? 'crit' : al.length ? 'warn' : '';
};

async function pollServers() {
  try {
    S.srv = await api('/api/servers');
    S.srvAt = Date.now();
    if (S.data && (S.view === 'servers' || S.view === 'overview')) render();
  } catch (e) { /* le prochain tour reessaie */ }
}

/* ---------- vue d'ensemble : cartes des hotes ---------- */
const _ovBase = RENDER.overview;
RENDER.overview = function (d) {
  _ovBase(d);
  const hosts = (S.srv && S.srv.hosts) || [], pan = $('srvPanel');
  if (pan) pan.hidden = !hosts.length;
  if (!hosts.length) return;
  $('srvSummary').textContent = `${hosts.length} hote${hosts.length > 1 ? 's' : ''} - ${hosts.reduce((n, h) => n + (h.info ? h.info.vm_on : 0), 0)} VM allumees`;
  $('srvCards').innerHTML = hosts.map((h, i) => {
    const sev = hostSev(h), al = d.alerts.filter(a => a.switch === h.name), c = al.filter(a => a.sev === 'crit').length, w = al.length - c, x = h.info;
    return `<button class="card ${sev}" data-srv="${i}"><div class="n"><span>${esc(h.name)}</span><span>${c ? `<span class="badge crit">${c}</span>` : ''}${w ? `<span class="badge">${w}</span>` : ''}${!al.length ? '<span class="badge ok">OK</span>' : ''}</span></div>
      <div class="m">${x ? esc(x.version) : esc(h.err || 'connexion...')} - ${esc(h.ip)}</div>
      ${x ? `<div class="st"><span><b>${x.vm_on}</b>/${x.vm_total} VM</span><span>CPU <b>${x.cpu_pct.toFixed(0)}%</b></span><span>RAM <b>${x.mem_pct.toFixed(0)}%</b></span>${x.temp != null ? `<span><b>${x.temp.toFixed(0)}</b>°C</span>` : ''}</div>` : ''}</button>`;
  }).join('');
};

/* ---------- page Serveurs ---------- */
const kpiS = (cls, l, v, u, s) => `<div class="kpi ${cls}"><div class="l">${l}</div><div class="v">${v}<small>${u}</small></div><div class="s">${s}</div></div>`;

RENDER.servers = function (d) {
  const sv = S.srv, hosts = (sv && sv.hosts) || [];
  if (!sv) { $('srvKpis').innerHTML = ''; $('srvHosts').innerHTML = '<div class="pad muted" style="padding:14px 16px">Chargement...</div>'; return; }
  if (!hosts.length) {
    $('srvKpis').innerHTML = '';
    $('srvHosts').innerHTML = '<div class="pad muted" style="padding:14px 16px">Aucun serveur ESXi configure. Ajoutez-les dans <code>/etc/vigilia/esxi.json</code> (voir la documentation), puis redemarrez Vigilia.</div>';
    ['srvVm', 'srvDs'].forEach(id => $(id).innerHTML = '');
    return;
  }
  if (S.srvHost && !hosts.some(h => h.ip === S.srvHost)) S.srvHost = '';
  const sel = hosts.filter(h => !S.srvHost || h.ip === S.srvHost), ok = hosts.filter(h => h.reach !== false && hostSev(h) !== 'crit').length;
  const infos = sel.map(h => h.info).filter(Boolean);
  const vms = sel.flatMap(h => (h.vms || []).map(v => ({h, v})));
  const on = vms.filter(x => x.v.power === 'poweredOn').length;
  const cpuMax = Math.max(0, ...infos.map(i => i.cpu_pct)), memMax = Math.max(0, ...infos.map(i => i.mem_pct));
  const dsCap = sel.reduce((n, h) => n + h.datastores.filter(x => x.type !== 'NFS').reduce((a, x) => a + x.cap, 0), 0);
  const dsFree = sel.reduce((n, h) => n + h.datastores.filter(x => x.type !== 'NFS').reduce((a, x) => a + x.free, 0), 0);
  const dsPct = dsCap ? (1 - dsFree / dsCap) * 100 : 0;
  const temps = infos.map(i => i.temp).filter(t => t != null), tmax = temps.length ? Math.max(...temps) : null;
  const alerts = d.alerts.filter(a => sel.some(h => h.name === a.switch)), c = alerts.filter(a => a.sev === 'crit').length;
  $('srvKpis').innerHTML =
    kpiS(ok === hosts.length ? 'ok' : 'crit', 'Hotes OK', ok, '/ ' + hosts.length, 'joignables, sans critique') +
    kpiS('', 'VM allumees', on, '/ ' + vms.length, `${vms.length - on} eteinte${vms.length - on > 1 ? 's' : ''}`) +
    kpiS(lvl(cpuMax, 75, 90), 'CPU hote max', cpuMax.toFixed(0), '%', esc(infos.length ? 'charge de l\'hote le plus charge' : '-')) +
    kpiS(lvl(memMax, 85, 95), 'Memoire hote max', memMax.toFixed(0), '%', 'hote le plus charge') +
    kpiS(lvl(dsPct, 85, 95), 'Stockage local', dsPct.toFixed(0), '%', `${gb(dsCap - dsFree)} / ${gb(dsCap)} (hors NFS)`) +
    kpiS(c ? 'crit' : alerts.length ? 'warn' : 'ok', 'Problemes', alerts.length, '', `${c} critique${c > 1 ? 's' : ''}` + (tmax != null ? ` - CPU ${tmax.toFixed(0)} °C` : ''));

  $('srvHostChips').innerHTML = `<button class="chip${!S.srvHost ? ' on' : ''}" data-srvsel="">Tous</button>` + hosts.map(h => `<button class="chip${S.srvHost === h.ip ? ' on' : ''}" data-srvsel="${esc(h.ip)}"><i class="dot ${hostSev(h) || 'ok'}"></i>${esc(h.name)}</button>`).join('');

  $('srvHosts').innerHTML = sel.map(h => {
    const x = h.info, sev = hostSev(h), al = d.alerts.filter(a => a.switch === h.name);
    if (!x) return `<div class="srvhost"><div class="srvh"><b><i class="dot ${sev || 'crit'}"></i>${esc(h.name)}</b> <span class="muted mono">${esc(h.ip)}</span></div><div class="x ${h.reach === false ? 'crit' : ''}">${esc(h.err || 'connexion en cours...')}</div></div>`;
    const bad = x.bad_sensors.map(b => `<span class="chip2 ${b.state === 'red' ? 'crit' : 'warn'}">${esc(b.name.split(' ').slice(2).join(' ') || b.name)}</span>`).join(' ');
    return `<div class="srvhost">
      <div class="srvh"><b><i class="dot ${sev || 'ok'}"></i>${esc(h.name)}</b> <span class="muted mono">${esc(h.ip)}</span>
        ${h.reach === false ? '<span class="pill crit">INJOIGNABLE - donnees figees</span>' : x.maint ? '<span class="pill">Maintenance</span>' : '<span class="pill ok">Connecte</span>'}
        <span class="muted">${esc(x.version)} (build ${esc(x.build)})</span></div>
      <div class="srvbody"><div class="srvgrid">
        <div class="srvcol"><div class="srvt">Serveur</div>${kv('Serveur', esc(x.vendor + ' ' + x.model))}${kv('Processeur', esc(`${x.sockets} x ${x.cpu_model}`))}${kv('Coeurs / threads', `${x.cores} / ${x.threads}`)}${kv('Disponibilite', x.uptime ? uptime(x.uptime) : '-')}</div>
        <div class="srvcol"><div class="srvt">Charge</div><div class="dl"><span>CPU</span><b>${bar(x.cpu_pct, lvl(x.cpu_pct, 75, 90))}${x.cpu_pct.toFixed(0)} % <span class="muted">(${(x.cpu_mhz / 1000).toFixed(1)} / ${(x.cpu_cap / 1000).toFixed(1)} GHz)</span></b></div>
          <div class="dl"><span>Memoire</span><b>${bar(x.mem_pct, lvl(x.mem_pct, 85, 95))}${x.mem_pct.toFixed(0)} % <span class="muted">(${mb(x.mem_use_mb)} / ${mb(x.mem_mb)})</span></b></div>
          ${kv('Temp. processeur', x.temp != null ? x.temp.toFixed(0) + ' °C' : '-', x.temp >= 80 ? 'warn' : '')}${kv('Entree d\'air', x.inlet != null ? x.inlet.toFixed(0) + ' °C' : '-', x.inlet >= 32 ? 'warn' : '')}</div>
        <div class="srvcol"><div class="srvt">Sante</div>${kv('Etat VMware', x.status === 'green' ? 'vert' : x.status === 'yellow' ? 'jaune' : x.status === 'red' ? 'rouge' : esc(x.status), x.status === 'green' ? 'ok' : x.status === 'red' ? 'crit' : 'warn')}${kv('Capteurs en defaut', bad || 'aucun', bad ? 'warn' : 'ok')}
          ${kv('Cartes reseau', x.nics.map(n => `${esc(n.dev)} ${n.mbps ? n.mbps + ' Mb/s' : '<span class="x crit">sans lien</span>'}`).join(' &middot; ') || '-')}${kv('Alertes', al.length ? `<a data-key="${esc(al[0].key)}">${al.length} - voir</a>` : 'aucune', al.length ? 'warn' : 'ok')}</div>
      </div>
      <div class="srvch"><div class="srvt"><i class="lg" style="background:var(--s-in)"></i>CPU <i class="lg warn"></i>Memoire (live)</div><div class="chartbox srvbox"><svg class="chart" id="chSrv${esc(h.ip.replace(/\./g, '_'))}"></svg></div></div></div></div>`;
  }).join('');
  sel.forEach(h => {
    const el = $('chSrv' + h.ip.replace(/\./g, '_')), hist = h.hist || [];
    if (!el || hist.length < 2) return;
    lineChart(el, [{v: hist.map(r => r[1]), c: css('--s-in'), area: true}, {v: hist.map(r => r[2]), c: css('--warn')}], {max: 100, fmt: v => Math.round(v) + '%', t0: hist[0][0], t1: hist[hist.length - 1][0], marks: [{v: 90, c: css('--crit')}]});
  });

  /* VM */
  const q = $('srvSearch').value.trim().toLowerCase();
  document.querySelectorAll('#srvFilter .chip').forEach(b => b.classList.toggle('on', b.dataset.sf === S.srvFilter));
  const rows = vms.filter(({v}) => (S.srvFilter === 'all' || (S.srvFilter === 'on' ? v.power === 'poweredOn' : v.power !== 'poweredOn')) &&
    (!q || (v.name + ' ' + v.ip + ' ' + v.os + ' ' + v.dns).toLowerCase().includes(q)));
  $('srvVmCount').textContent = `${rows.length} VM`;
  $('srvVm').innerHTML = '<colgroup><col><col style="width:90px"><col style="width:120px"><col style="width:60px"><col style="width:140px"><col style="width:160px"><col style="width:130px"><col style="width:90px"><col style="width:80px"></colgroup><tr><th>Machine virtuelle</th><th>Etat</th><th>Hote</th><th>vCPU</th><th>CPU</th><th>Memoire</th><th>Adresse IP</th><th>Disponibilite</th><th>Snapshots</th></tr>' +
    rows.map(({h, v}) => {
      const p = POWER[v.power] || [v.power, ''], on = v.power === 'poweredOn', stat = v.status === 'red' ? 'crit' : v.status === 'yellow' ? 'warn' : '';
      return `<tr class="row" data-vm="${esc(h.ip + '|' + v.id)}"><td title="${esc(v.os)}"><i class="dot ${on ? (stat || 'ok') : ''}"></i>${esc(v.name)}${v.template ? ' <span class="chip2">modele</span>' : ''}</td><td class="${p[1]}">${p[0]}</td><td>${esc(h.name)}</td><td>${v.ncpu}</td>
        <td>${on ? bar(v.cpu_pct, lvl(v.cpu_pct, 80, 95)) + v.cpu_pct.toFixed(0) + ' %' : '-'}</td><td>${on ? bar(v.mem_pct, lvl(v.mem_pct, 85, 95)) + mb(v.mem_use_mb) : mb(v.mem_mb)}</td>
        <td class="mono">${esc(v.ip || '-')}</td><td>${on && v.uptime ? uptime(v.uptime) : '-'}</td><td class="${v.snap_oldest && S.data.now - v.snap_oldest > 3 * 86400 ? 'warn' : ''}">${v.snaps || '-'}</td></tr>`;
    }).join('');

  /* datastores */
  $('srvDs').innerHTML = '<colgroup><col style="width:140px"><col><col style="width:70px"><col style="width:90px"><col style="width:90px"><col style="width:200px"></colgroup><tr><th>Hote</th><th>Datastore</th><th>Type</th><th>Capacite</th><th>Libre</th><th>Utilisation</th></tr>' +
    sel.flatMap(h => h.datastores.map(x => `<tr><td>${esc(h.name)}</td><td><i class="dot ${x.ok ? 'ok' : 'crit'}"></i>${esc(x.name)}${x.ok ? '' : ' <span class="x crit">inaccessible</span>'}</td><td>${esc(x.type)}</td><td>${gb(x.cap)}</td><td>${gb(x.free)}</td><td>${bar(x.pct, lvl(x.pct, 85, 95))}${x.pct.toFixed(0)} %</td></tr>`)).join('');
};

/* ---------- detail d'une VM (fenetre) ---------- */
function openVm(key) {
  const [ip, id] = key.split('|'), h = S.srv && S.srv.hosts.find(x => x.ip === ip), v = h && h.vms.find(x => x.id === id);
  if (!v) return;
  const p = POWER[v.power] || [v.power, ''], on = v.power === 'poweredOn', al = S.data.alerts.filter(a => a.switch === h.name && a.title.includes(v.name));
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">${esc(v.name)} <span class="pill ${p[1]}">${p[0]}</span></h2><div class="muted">VM sur ${esc(h.name)} (${esc(h.ip)}) - supervision en lecture seule</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    ${al.map(a => `<div class="malert"><span class="sevtag">${SEV[a.sev]}</span>${esc(a.title)} <span class="muted">- ${esc(a.detail)}</span></div>`).join('')}
    <div class="mh4">General</div>${kv('Systeme', esc(v.os || '-'))}${kv('vCPU / memoire', `${v.ncpu} vCPU / ${mb(v.mem_mb)}`)}${kv('Adresse IP', `<code>${esc(v.ip || '-')}</code>`)}${kv('Nom DNS (VMware Tools)', esc(v.dns || '-'))}
    ${kv('VMware Tools', esc(TOOLS[v.tools] || v.tools || '-'), v.tools === 'guestToolsRunning' || v.tools === 'toolsOk' ? 'ok' : '')}${kv('Statut VMware', esc(v.status), v.status === 'green' ? 'ok' : v.status === 'red' ? 'crit' : v.status === 'yellow' ? 'warn' : '')}${on ? kv('Disponibilite', uptime(v.uptime)) : ''}
    <div class="mh4">Ressources</div>${on ? kv('CPU', bar(v.cpu_pct, lvl(v.cpu_pct, 80, 95)) + v.cpu_pct.toFixed(0) + ' % (' + v.cpu_mhz + ' MHz)') + kv('Memoire utilisee', bar(v.mem_pct, lvl(v.mem_pct, 85, 95)) + mb(v.mem_use_mb) + ' / ' + mb(v.mem_mb)) : '<div class="muted">VM eteinte : pas de mesure.</div>'}
    ${kv('Espace datastore utilise', gb(v.used))}${kv('Espace provisionne', gb(v.prov))}
    <div class="mh4">Disques (VMware Tools)</div>${v.disks.length ? v.disks.map(d => kv(`<code>${esc(d.path)}</code>`, d.cap ? bar((1 - d.free / d.cap) * 100, lvl((1 - d.free / d.cap) * 100, 85, 95)) + gb(d.cap - d.free) + ' / ' + gb(d.cap) : '-')).join('') : '<div class="muted">Non disponible (VM eteinte ou VMware Tools absents).</div>'}
    <div class="mh4">Snapshots</div>${v.snaps ? kv('Nombre', v.snaps, v.snaps > 2 ? 'warn' : '') + kv('Le plus ancien', fdate(v.snap_oldest), S.data.now - v.snap_oldest > 3 * 86400 ? 'warn' : '') : '<div class="muted">Aucun snapshot.</div>'}
    <div class="muted" style="margin-top:12px">Vigilia ne fait que lire ces informations : aucune action (demarrage, arret, snapshot...) n'est possible depuis cette page.</div>`;
  $('modal').hidden = false;
}

const _prevExtraSrv = window.onExtraClick;
window.onExtraClick = e => {
  let el;
  if ((el = e.target.closest('[data-srv]'))) { S.srvHost = S.srv.hosts[+el.dataset.srv].ip; go('servers'); return true; }
  if ((el = e.target.closest('[data-srvsel]'))) { S.srvHost = el.dataset.srvsel; render(); return true; }
  if ((el = e.target.closest('[data-sf]'))) { S.srvFilter = el.dataset.sf; render(); return true; }
  if ((el = e.target.closest('[data-vm]'))) { openVm(el.dataset.vm); return true; }
  return _prevExtraSrv ? _prevExtraSrv(e) : false;
};
$('srvSearch').addEventListener('input', () => S.data && S.view === 'servers' && render());

{ const v = location.hash.slice(1); if (v === 'servers' && S.view !== 'servers') { S.view = 'servers'; if (S.data) render(); } }
pollServers();
setInterval(pollServers, 5000);
