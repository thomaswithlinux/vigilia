'use strict';
/* Journal detaille : filtres serveur, pagination, detail d'un evenement (contexte, cause, verifications, evenements lies), export .zip. */
const KIND_LABEL = {port_down: 'Port down', errors: 'Erreurs sur un port', util: 'Saturation de lien', flap: 'Port instable', duplex: 'Half-duplex', temp: 'Température', cpu: 'CPU',
  speed: 'Lien en 10 Mb/s', unreach: 'Switch injoignable', hostkey: 'Clé SSH modifiée', device_new: 'Nouvel appareil', device_move: 'Appareil déplacé', config: 'Configuration modifiée'};
const LV = {crit: ['CRITIQUE', 'crit'], warn: ['ALERTE', 'warn'], ok: ['RÉSOLU', 'ok'], info: ['INFO', 'info']};
Object.assign(S, {log: {rows: [], more: false, total: 0, kinds: [], switches: [], loading: false, at: 0, sig: '', sel: null, detail: null, pages: 1, key: '', demo: false}});
const fsec = t => new Date(t * 1000).toLocaleString('fr-FR');

const logParams = () => ({sev: S.lfilter === 'all' ? '' : S.lfilter, sw: $('logSw').value, kind: $('logKind').value, days: $('logDays').value, q: $('logSearch').value.trim()});
const logKey = () => JSON.stringify(logParams());

async function fetchLog(reset) {
  const L = S.log;
  if (L.loading) return;
  L.loading = true;
  const p = new URLSearchParams(Object.assign({limit: 200}, logParams()));
  if (!reset && L.rows.length) p.set('before', L.rows[L.rows.length - 1].id);
  try {
    const r = await api('/api/events?' + p);
    if (r.demo) { L.demo = true; return; }
    L.rows = reset ? r.events : L.rows.concat(r.events);
    L.more = r.more; L.total = r.total; L.kinds = r.kinds; L.switches = r.switches; L.at = Date.now();
    L.pages = reset ? 1 : L.pages + 1;
    fillLogSelects();
  } finally {
    L.loading = false;
    if (S.view === 'log' && S.data) RENDER.log(S.data);
  }
}

function fillLogSelects() {
  const L = S.log, sw = $('logSw'), kd = $('logKind');
  const cur = [sw.value, kd.value];
  sw.innerHTML = '<option value="">Tous les switches</option>' + L.switches.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
  kd.innerHTML = '<option value="">Tous les types</option>' + L.kinds.map(k => `<option value="${esc(k)}">${esc(KIND_LABEL[k] || k)}</option>`).join('');
  sw.value = cur[0]; kd.value = cur[1];
}

RENDER.log = function (d) {
  const L = S.log, key = logKey();
  document.querySelectorAll('#logFilter .chip').forEach(b => b.classList.toggle('on', b.dataset.l === S.lfilter));
  $('zipBox').hidden = !can('tech');
  if (key !== L.key) { L.key = key; L.sig = ''; fetchLog(true); }
  else if (Date.now() - L.at > 10000 && L.pages === 1 && !L.loading) fetchLog(true);  // rafraichissement automatique de la 1re page
  if (L.demo) { $('logTbl').innerHTML = '<tr><td class="muted">Le journal détaillé n\'est disponible qu\'en mode réel.</td></tr>'; return; }
  const sig = L.rows.length + '|' + (L.rows[0] ? L.rows[0].id : 0) + '|' + (L.rows.length ? L.rows[L.rows.length - 1].id : 0) + '|' + L.sel + '|' + L.more;
  $('logCount').textContent = `${L.rows.length} affiché(s) sur ${L.total} enregistrés`;
  if (sig !== L.sig) {
    L.sig = sig;
    $('logTbl').innerHTML = '<colgroup><col style="width:178px"><col style="width:86px"><col style="width:128px"><col style="width:84px"><col style="width:150px"><col></colgroup><tr><th>Date</th><th>Niveau</th><th>Switch</th><th>Port</th><th>Type</th><th>Message</th></tr>' +
      L.rows.map(e => `<tr class="row${L.sel === e.id ? ' sel' : ''}" data-ev="${e.id}"><td class="mono">${fsec(e.t)}</td><td class="${LV[e.sev] ? LV[e.sev][1] : ''}">${LV[e.sev] ? LV[e.sev][0] : esc(e.sev)}</td><td>${esc(e.sw)}</td><td class="mono">${esc(e.port)}</td>` +
        `<td>${esc(KIND_LABEL[e.kind] || '')}</td><td title="${esc(e.text)}">${esc(e.text)}</td></tr>`).join('');
    $('logMore').innerHTML = L.more ? `<div style="padding:10px 14px"><button class="chip" data-logmore="1">Charger les ${200} suivants</button></div>` : (L.rows.length ? '<div class="muted" style="padding:10px 14px">Fin du journal pour ces filtres.</div>' : '<div class="muted" style="padding:14px">Aucun événement pour ces filtres.</div>');
  }
  renderLogDetail();
};

async function selectEvent(id) {
  const L = S.log;
  L.sel = id; L.sig = ''; L.detail = null;
  RENDER.log(S.data);
  try { L.detail = await api('/api/event?id=' + id); } catch (e) { return; }
  renderLogDetail(true);
}

function renderLogDetail(force) {
  const L = S.log, el = $('logDetail');
  if (!L.sel) return;
  if (!L.detail || !L.detail.event || L.detail.event.id !== L.sel) { el.innerHTML = '<div class="muted">Chargement…</div>'; el._h = ''; return; }
  const r = L.detail, ev = r.event, dt = ev.detail || {}, lv = LV[ev.sev] || ['?', ''];
  const swI = S.data.switches.findIndex(s => s.name === ev.sw), sw = swI >= 0 ? S.data.switches[swI] : null, pObj = sw && ev.port ? sw.ports.find(p => p.name === ev.port) : null;
  const LBL = {alerte_id: 'Alerte n°', titre: 'Titre', detail: 'Détail', gravite: 'Gravité', avant: 'Avant', apres: 'Après', ouverte: 'Ouverte le', duree_s: 'Durée de l\'incident', mac: 'Adresse MAC', vlan: 'VLAN',
    port: 'Port', premiere_vue: 'Première vue', de: 'Depuis', vers: 'Vers', deplacements: 'Déplacements', sauvegarde: 'Sauvegarde', config_id: 'Configuration n°', precedente_id: 'Version précédente', taille_octets: 'Taille'};
  const sevTxt = v => ({crit: 'Critique', warn: 'Alerte', ok: 'Résolu', info: 'Info'}[v] || v);
  const fmtv = (k, v) => k === 'ouverte' || k === 'premiere_vue' ? fsec(v) : k === 'duree_s' ? dur(v) : k === 'taille_octets' ? bytes(v) : ['gravite', 'avant', 'apres'].includes(k) ? sevTxt(v) :
    k === 'mac' ? `<code>${esc(v)}</code> <span class="muted">${esc(vendor(v))}</span> <button class="chip" data-copy="${esc(v)}">Copier</button>` : esc(v);
  let h = `<div class="dt" style="font-size:16px"><span class="pill ${lv[1] === 'ok' ? 'ok' : lv[1] === 'crit' ? 'crit' : ''}">${lv[0]}</span> ${esc(KIND_LABEL[ev.kind] || 'Événement')}</div>
    <div class="logmsg">${esc(ev.text)}</div>` +
    sec('Quand', kv('Date exacte', fsec(ev.t)) + kv('Il y a', ago(ev.t, S.data.now)) + kv('Événement n°', ev.id)) +
    sec('Où', kv('Switch', sw ? `<a data-i="${swI}">${esc(sw.name)}</a>` : esc(ev.sw || '-')) + kv('Adresse IP', `<code>${esc(ev.ip || '-')}</code>`) +
      kv('Port', pObj ? `<a data-open="${swI}|${pObj.n}">${esc(ev.port)}</a>` : esc(ev.port || '-')));
  const keys = Object.keys(dt).filter(k => !['cause', 'verifications', 'titre'].includes(k) && dt[k] !== '' && dt[k] != null);
  if (keys.length || dt.titre) h += sec('Détail', (dt.titre ? kv('Titre', esc(dt.titre)) : '') + keys.map(k => kv(esc(LBL[k] || k), fmtv(k, dt[k]))).join(''));
  if (dt.cause) h += `<div class="cause ${ev.sev === 'crit' ? 'crit' : ''}"><b>Cause probable</b><div>${esc(dt.cause)}</div></div>`;
  if (dt.verifications && dt.verifications.length) h += sec('Vérifications proposées', dt.verifications.map(c => c.startsWith('show ') ? cmdRow(c, true) : `<div class="muted" style="margin:4px 0">${esc(c)}</div>`).join(''));
  if (r.alert) {
    const a = r.alert;
    h += sec('Alerte liée', kv('Ouverte le', fsec(a.opened)) + kv('Fermée le', a.closed ? fsec(a.closed) : '<span class="x warn">toujours active</span>') + kv('Durée', dur((a.closed || Date.now() / 1000) - a.opened)) + kv('Gravité', sevTxt(a.sev)));
  }
  if (dt.config_id && swI >= 0) h += `<div class="actions"><button class="btn alt" data-cfgopen="${swI}|${dt.config_id}">Voir la configuration</button>` + (dt.precedente_id ? `<button class="btn alt" data-cfgdiffopen="${swI}|${dt.precedente_id}|${dt.config_id}">Voir les changements</button>` : '') + '</div>';
  const evRow2 = x => `<div class="trow" data-ev="${x.id}"><span class="dot ${x.sev === 'crit' ? 'crit' : x.sev === 'warn' ? 'warn' : 'ok'}"></span><span class="mono muted">${fsec(x.t)}</span> ${esc(cut(x.text, 70))}</div>`;
  if (r.related.length) h += sec(`Événements liés (${r.related.length})`, r.related.map(evRow2).join(''));
  if (r.around.length) h += sec('Autour de cet événement (± 5 min)', r.around.map(evRow2).join(''));
  h += `<div class="actions">` +
    `<button class="btn alt" data-copy="${esc(ev.text)}">Copier le message</button><button class="btn alt" data-copy="${esc(JSON.stringify(ev, null, 1))}">Copier en JSON</button>` +
    (sw ? `<button class="btn alt" data-ssh="${swI}||${esc(ev.port || '')}">&gt;_ SSH</button>` : '') + '</div>';
  if (el._h !== h) { const top = el.scrollTop; el.innerHTML = h; el.scrollTop = top; el._h = h; }
}

async function downloadZip() {
  const btn = $('logZip'), days = $('zipDays').value, old = btn.textContent;
  btn.disabled = true; btn.textContent = 'Préparation…';
  try {
    const r = await fetch('/api/logs.zip?days=' + encodeURIComponent(days), {cache: 'no-store'});
    if (r.status === 401) { location.reload(); return; }
    if (!r.ok) { const j = await r.json().catch(() => ({})); alert('Export impossible : ' + (j.error || r.status)); return; }
    const blob = await r.blob(), name = (/filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '') || [])[1] || 'vigilia-logs.zip';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name; a.click(); URL.revokeObjectURL(a.href);
  } finally { btn.disabled = false; btn.textContent = old; }
}

['logSw', 'logKind', 'logDays'].forEach(id => $(id).addEventListener('change', () => S.data && render()));
let logTimer;
$('logSearch').addEventListener('input', () => { clearTimeout(logTimer); logTimer = setTimeout(() => S.data && render(), 350); });

const _prevExtraJ = window.onExtraClick;
window.onExtraClick = e => {
  const t = e.target;
  let el;
  if ((el = t.closest('[data-ev]'))) { selectEvent(+el.dataset.ev); return true; }
  if (t.closest('[data-logmore]')) { fetchLog(false); return true; }
  if (t.closest('#logZip')) { downloadZip(); return true; }
  if ((el = t.closest('[data-cfgopen]'))) { const [i, id] = el.dataset.cfgopen.split('|'); S.sw = +i; go('configs'); setTimeout(() => showCfg(+id), 700); return true; }
  if ((el = t.closest('[data-cfgdiffopen]'))) { const [i, a, b] = el.dataset.cfgdiffopen.split('|'); S.sw = +i; go('configs'); setTimeout(() => showDiff(a + '|' + b), 700); return true; }
  return _prevExtraJ(e);
};
