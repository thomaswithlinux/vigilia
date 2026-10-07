'use strict';
/* Topologie interactive : switches -> categories -> appareils. Zoom (molette), deplacement (glisser), recherche, filtres, panneau de details. */
const TCAT = {
  wifi: {l: 'Bornes Wi-Fi', c: '#5aa9ff'}, phone: {l: 'Téléphones', c: '#c792ea'}, srv: {l: 'Serveurs & stockage', c: '#f2b84b'},
  fw: {l: 'Pare-feu & routeurs', c: '#ff9f68'}, net: {l: 'Autres équipements réseau', c: '#6ee7d8'}, pc: {l: 'Postes & autres appareils', c: '#8ba2b8'},
  link: {l: 'Liens vers équipements intermédiaires', c: '#9b8cff'},
};
Object.assign(S, {topo: {x: 20, y: 20, k: 1, needFit: true, exp: new Set(), cat: new Set(), more: new Set(), hide: new Set(), prob: false, sel: null, q: '', suppress: false, bb: {w: 800, h: 400}}});

const cut = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

function tClass(p) {
  const nb = p.nb || {}, t = ((p.desc || '') + ' ' + (nb.name || '')).toLowerCase(), caps = (nb.caps || '').toLowerCase();
  if (p.mac_count > 8) return 'link';
  if (/wifi|wlan|\bap[-_ ]?\d|\bbw\d|access.?point|aruba|unifi/.test(t) || caps.includes('wlan')) return 'wifi';
  if (caps.includes('telephone') || /voip|phone|ipbx|\btel[-_ ]/.test(t)) return 'phone';
  if (caps.includes('router') || /fgt|forti|firewall|pare-?feu|routeur|\bwan\b|\bfw[-_ ]/.test(t)) return 'fw';
  if (/srv|server|serveur|\bnas|esxi|idrac|\bilo\b|veeam|hyper|vcenter|backup|sauvegarde|synology|qnap/.test(t) || ['VMware', 'QNAP', 'Microsoft Hyper-V', 'Dell'].includes(vendor(p.mac || ''))) return 'srv';
  if (caps.includes('bridge') || caps.includes('switch')) return 'net';
  return 'pc';
}

function tModel(d) {
  const idx = {};
  d.switches.forEach((s, i) => { idx[s.name] = i; });
  const E = {};
  d.switches.forEach((s, i) => s.ports.forEach(p => {
    const o = p.nb && p.nb.owner;
    if (!o || o === s.name || idx[o] === undefined) return;
    const j = idx[o], a = Math.min(i, j), b = Math.max(i, j), k = a + '-' + b, e = E[k] = E[k] || {key: k, a, b, side: {}};
    (e.side[i] = e.side[i] || []).push(p);
  }));
  const edges = Object.values(E).map(e => {
    const sd = Object.values(e.side);
    return Object.assign(e, {n: Math.max(...sd.map(x => x.length)), down: Math.max(...sd.map(x => x.filter(p => p.status !== 'up').length))});
  });
  const devs = d.switches.map((s, i) => s.ports
    .filter(p => p.status === 'up' && !(p.nb && p.nb.owner && p.nb.owner !== s.name && idx[p.nb.owner] !== undefined))
    .map(p => ({i, p, cat: tClass(p), name: p.desc || (p.nb && p.nb.name) || p.mac || 'Appareil non identifié', sev: portSev(s.name, p.n)})));
  return {idx, edges, devs};
}

function tVisible(dv, q) {
  const T = S.topo;
  if (T.hide.has(dv.cat) || (T.prob && !dv.sev)) return false;
  if (!q) return true;
  const hay = [dv.name, dv.p.name, dv.p.mac, ...(dv.p.macs || []).map(m => m.mac), String(dv.p.vlan || ''), vendor(dv.p.mac || ''), dv.p.note || ''].join(' ').toLowerCase();
  return hay.includes(q);
}

const sevColor = sev => sev === 'crit' ? css('--crit') : sev === 'warn' ? css('--warn') : css('--ok');

RENDER.topology = function (d) {
  const svg = $('topo'), W = svg.clientWidth, H = svg.clientHeight;
  if (W < 100 || H < 100) return;
  const T = S.topo, q = T.q.trim().toLowerCase(), M = tModel(d), sw = d.switches;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  renderTopoToolbar(M);

  // ---- niveaux (parcours en largeur depuis le switch le plus connecte)
  const adj = sw.map(() => []);
  M.edges.forEach(e => { adj[e.a].push(e.b); adj[e.b].push(e.a); });
  const root = adj.map(a => a.length).indexOf(Math.max(...adj.map(a => a.length)));
  const level = sw.map(() => -1);
  level[root] = 0;
  const order = [root];
  for (let h = 0; h < order.length; h++) for (const n of adj[order[h]]) if (level[n] < 0) { level[n] = level[order[h]] + 1; order.push(n); }
  const loose = sw.map((_, i) => i).filter(i => level[i] < 0);

  // ---- contenu deplie de chaque switch
  const NW = 214, NH = 68, DW = 236, DH = 42, CH = 30, GX = 70, RG = 26, forced = !!q || T.prob;
  const blocks = sw.map((s, i) => {
    const vis = M.devs[i].filter(dv => tVisible(dv, q)), cats = {};
    vis.forEach(dv => (cats[dv.cat] = cats[dv.cat] || []).push(dv));
    const open = T.exp.has(i) || (forced && vis.length > 0), items = [];
    if (open) Object.keys(TCAT).filter(c => cats[c]).forEach(c => {
      items.push({t: 'cat', c, n: cats[c].length});
      const key = i + '|' + c;
      if (T.cat.has(key) || forced) {
        const lim = T.more.has(key) ? 9999 : 12;
        cats[c].slice(0, lim).forEach(dv => items.push({t: 'dev', dv}));
        if (cats[c].length > lim) items.push({t: 'more', key, n: cats[c].length - lim});
      }
    });
    const h = items.reduce((a, it) => a + (it.t === 'cat' ? CH : it.t === 'dev' ? DH : 24) + 6, 0);
    return {open, items, h: Math.max(NH, h)};
  });

  // ---- positions
  const pos = {}, levels = [], colX = [], hasItems = i => blocks[i].open && blocks[i].items.length > 0;
  order.forEach(i => (levels[level[i]] = levels[level[i]] || []).push(i));
  const LX = hasItems(root) ? DW + GX : 36;  // les appareils du switch racine s'affichent a sa gauche
  let maxY = 0, cx = LX, maxX = 0;
  levels.forEach((list, L) => {
    colX[L] = cx;
    const open = L > 0 && list.some(hasItems);  // les appareils des autres switches s'affichent a leur droite
    maxX = Math.max(maxX, cx + NW + (open ? DW + 70 : 40));
    cx += NW + (open ? DW + 50 : 0) + GX;
    let y = 24;
    list.sort((a, b) => a - b).forEach(i => { pos[i] = {x: colX[L], y}; y += blocks[i].h + RG; });
    maxY = Math.max(maxY, y);
  });
  if (levels.length > 1) {
    const k = levels[1], top = pos[k[0]].y, bot = pos[k[k.length - 1]].y + NH;
    pos[root].y = Math.max(24, (top + bot) / 2 - NH / 2);
  }
  if (loose.length) {
    let y = maxY + 18;
    loose.forEach(i => { pos[i] = {x: LX, y}; y += blocks[i].h + RG; });
    maxY = y;
  }
  if (loose.some(hasItems)) maxX = Math.max(maxX, LX + NW + DW + 70);

  // ---- dessin : liens entre switches
  let g = '';
  M.edges.forEach(e => {
    let a = e.a, b = e.b;
    if (level[a] > level[b]) [a, b] = [b, a];
    const A = pos[a], B = pos[b], col = e.down >= e.n ? css('--crit') : e.down ? css('--warn') : css('--ok');
    const x1 = A.x + NW, y1 = A.y + NH / 2, x2 = B.x, y2 = B.y + NH / 2, xm = (x1 + x2) / 2;
    const path = level[a] === level[b] ? `M${A.x + NW / 2},${A.y + NH} L${B.x + NW / 2},${B.y}` : `M${x1},${y1} H${xm} V${y2} H${x2}`;
    const sp = (Object.values(e.side)[0][0] || {}).speed || '';
    const lab = `${e.n}×${sp}${e.down ? ' ⚠' + e.down : ''}`, lw = 12 + lab.length * 6.4, my = level[a] === level[b] ? (A.y + NH + B.y) / 2 : y2, mx = level[a] === level[b] ? A.x + NW / 2 : xm;
    const sel = T.sel && T.sel.t === 'edge' && T.sel.key === e.key;
    g += `<g class="t-edge${sel ? ' sel' : ''}" data-te="${e.key}"><path d="${path}" fill="none" stroke="${col}" stroke-width="${Math.min(2.5 + e.n, 8)}" opacity="${sel ? 1 : .75}"/>
      <path d="${path}" fill="none" stroke="transparent" stroke-width="16"/>
      <rect x="${mx - lw / 2}" y="${my - 11}" width="${lw}" height="22" rx="11" class="t-pill" style="stroke:${col}"/><text x="${mx}" y="${my + 4}" text-anchor="middle" class="t-pilltxt">${esc(lab)}</text>
      <title>${esc(sw[e.a].name)} ⇄ ${esc(sw[e.b].name)} : ${e.n} lien(s), ${e.down} en panne. Cliquez pour le détail.</title></g>`;
  });

  // ---- dessin : switches, categories, appareils
  sw.forEach((s, i) => {
    const P = pos[i], B = blocks[i], left = i === root, nsel = T.sel && T.sel.t === 'sw' && T.sel.i === i;
    const sev = s.reach === false ? 'crit' : swSev(s), col = sevColor(sev), cx = left ? P.x : P.x + NW, dir = left ? -1 : 1;
    const tx = cx + dir * 24, up = s.ports.filter(p => p.status === 'up').length;
    if (B.open && B.items.length) {
      let y = P.y, lastMid = P.y + NH / 2;
      const rows = [];
      B.items.forEach(it => {
        const hh = it.t === 'cat' ? CH : it.t === 'dev' ? DH : 24;
        rows.push({it, y, hh});
        lastMid = y + hh / 2;
        y += hh + 6;
      });
      g += `<path d="M${cx},${P.y + NH / 2} H${tx} V${lastMid}" fill="none" class="t-trunk"/>`;
      const cardX = left ? tx - 22 - DW : tx + 22;
      rows.forEach(({it, y, hh}) => {
        const mid = y + hh / 2, ex = left ? cardX + DW : cardX;
        g += `<path d="M${tx},${mid} H${ex}" fill="none" class="t-trunk"/>`;
        if (it.t === 'cat') {
          const open = T.cat.has(i + '|' + it.c) || forced;
          g += `<g class="t-cat" data-tc="${i}|${it.c}"><rect x="${cardX}" y="${y}" width="${DW}" height="${hh}" rx="15" class="t-catbg" style="stroke:${TCAT[it.c].c}"/>
            <circle cx="${cardX + 15}" cy="${mid}" r="5" style="fill:${TCAT[it.c].c}"/><text x="${cardX + 28}" y="${mid + 4}" class="t-catx">${esc(cut(TCAT[it.c].l, 26))}</text>
            <text x="${cardX + DW - 14}" y="${mid + 4}" text-anchor="end" class="t-catn">${it.n} ${open ? '▾' : '▸'}</text></g>`;
        } else if (it.t === 'dev') {
          const dv = it.dv, p = dv.p, dsel = T.sel && T.sel.t === 'dev' && T.sel.i === i && T.sel.n === p.n, dc = sevColor(dv.sev);
          const sub = [p.name, p.vlan ? 'VLAN ' + p.vlan : '', p.speed, p.mac_count > 1 ? p.mac_count + ' MAC' : (p.mac || '')].filter(Boolean).join(' · ');
          g += `<g class="t-dev${dsel ? ' sel' : ''}" data-td="${i}|${p.n}"><rect x="${cardX}" y="${y}" width="${DW}" height="${hh}" rx="8" class="t-devbg"/>
            <rect x="${cardX}" y="${y}" width="5" height="${hh}" rx="2" style="fill:${dc}"/>
            <text x="${cardX + 14}" y="${y + 17}" class="t-name">${esc(cut(dv.name, 29))}</text><text x="${cardX + 14}" y="${y + 32}" class="t-sub">${esc(cut(sub, 38))}</text>
            <title>${esc(dv.name)} - port ${esc(p.name)}${p.mac ? ' - ' + esc(p.mac) : ''}</title></g>`;
        } else {
          g += `<g class="t-more" data-tm="${it.key}"><text x="${cardX + 14}" y="${y + 16}" class="t-link">+ ${it.n} autres (afficher tout)</text></g>`;
        }
      });
    }
    g += `<g class="t-node${nsel ? ' sel' : ''}" data-tn="${i}"><rect x="${P.x}" y="${P.y}" width="${NW}" height="${NH}" rx="12" class="t-nodebg" style="stroke:${col}"/>
      <text x="${P.x + 14}" y="${P.y + 23}" class="t-nname">${esc(cut(s.name, 20))}</text><text x="${P.x + NW - 14}" y="${P.y + 23}" text-anchor="end" class="t-chev">${B.open ? '▾' : '▸'}</text>
      <text x="${P.x + 14}" y="${P.y + 41}" class="t-sub">${esc(cut(s.model + ' · ' + s.ip, 32))}</text>
      <text x="${P.x + 14}" y="${P.y + 58}" class="t-sub">${s.reach === false ? 'INJOIGNABLE' : up + ' ports · ' + M.devs[i].length + ' appareils · CPU ' + s.cpu.toFixed(0) + '%'}</text></g>`;
  });
  if (loose.length) {
    const y = Math.min(...loose.map(i => pos[i].y)) - 22;
    g = `<text x="${LX}" y="${y}" class="t-hint">Switches sans lien LLDP connu avec les autres</text>` + g;
  }

  T.bb = {w: Math.max(maxX, 600), h: Math.max(maxY + 20, 300)};
  if (T.needFit) {
    T.k = Math.max(0.3, Math.min(1, (W - 30) / T.bb.w, (H - 30) / T.bb.h));
    T.x = Math.max(10, (W - T.bb.w * T.k) / 2); T.y = 14; T.needFit = false;
  }
  svg.innerHTML = `<g id="topoG" transform="translate(${T.x},${T.y}) scale(${T.k})">${g}</g>`;
  renderTopoSide(d, M);
};

function renderTopoToolbar(M) {
  const T = S.topo, tot = {};
  M.devs.forEach(l => l.forEach(dv => { tot[dv.cat] = (tot[dv.cat] || 0) + 1; }));
  $('topoCats').innerHTML = Object.keys(TCAT).filter(c => tot[c]).map(c =>
    `<button class="chip ${T.hide.has(c) ? '' : 'on'}" data-thide="${c}" style="${T.hide.has(c) ? '' : 'background:' + TCAT[c].c + ';border-color:' + TCAT[c].c + ';color:#06121f'}">${esc(TCAT[c].l)} ${tot[c]}</button>`).join('');
  $('topoProb').classList.toggle('on', T.prob);
}

/* ---------- panneau de details ---------- */
function renderTopoSide(d, M) {
  const T = S.topo, box = $('topoSide'), title = $('topoSideT'), sel = T.sel;
  let h = '';
  if (sel && sel.t === 'sw' && d.switches[sel.i]) {
    const s = d.switches[sel.i], i = sel.i, al = alertsFor(s.name), cats = {};
    M.devs[i].forEach(dv => { cats[dv.cat] = (cats[dv.cat] || 0) + 1; });
    title.textContent = 'Switch';
    h = `<div class="dt" style="font-size:18px">${esc(s.name)}</div><div class="muted">${esc(s.model)} · ${esc(s.ip)}${s.loc ? ' · ' + esc(s.loc) : ''}</div>` +
      sec('État', kv('Ports actifs', s.ports.filter(p => p.status === 'up').length + ' / ' + s.ports.filter(p => p.status !== 'off').length) + kv('CPU', s.cpu.toFixed(0) + ' %', lvl(s.cpu, 75, 90)) +
        kv('Mémoire', s.mem.toFixed(0) + ' %') + kv('Température', s.temp.toFixed(0) + ' °C', lvl(s.temp, 62, 75)) + kv('Uptime', s.reach === false ? '-' : uptime(s.uptime)) + kv('Firmware', esc(s.firmware || '-')) +
        (s.poe > 0 ? kv('PoE consommé', s.poe.toFixed(0) + ' W') : '')) +
      sec(`Appareils connectés (${M.devs[i].length})`, Object.keys(TCAT).filter(c => cats[c]).map(c =>
        `<div class="dl tcat-row" data-tcx="${i}|${c}"><span><i class="tdot" style="background:${TCAT[c].c}"></i>${esc(TCAT[c].l)}</span><b>${cats[c]}</b></div>`).join('') || '<div class="muted">Aucun appareil actif.</div>') +
      (al.length ? sec(`Problèmes (${al.length})`, al.slice(0, 8).map(a => `<div class="trow" data-key="${esc(a.key)}"><span class="sevtag">${SEV[a.sev]}</span>${esc(a.title)}</div>`).join('')) : sec('Problèmes', '<div class="muted" style="color:var(--ok)">Aucun problème actif.</div>')) +
      `<div class="actions"><button class="btn" data-i="${i}">Ouvrir le switch</button><button class="btn alt" data-ssh="${i}||">&gt;_ SSH</button></div>`;
  } else if (sel && sel.t === 'edge') {
    const e = M.edges.find(x => x.key === sel.key);
    if (e) {
      title.textContent = 'Lien entre switches';
      const rows = [];
      Object.entries(e.side).forEach(([si, ps]) => ps.forEach(p => rows.push({si: +si, p})));
      h = `<div class="dt" style="font-size:17px">${esc(d.switches[e.a].name)} ⇄ ${esc(d.switches[e.b].name)}</div><div class="muted">${e.n} lien(s) · ${e.down} en panne</div>` +
        `<table class="tbl mini"><tr><th>Switch</th><th>Port</th><th>État</th><th>Débit</th></tr>` + rows.map(({si, p}) =>
          `<tr class="row" data-open="${si}|${p.n}"><td>${esc(cut(d.switches[si].name, 16))}</td><td class="mono">${esc(p.name)}</td><td class="${p.status === 'up' ? 'ok' : 'crit'}">${p.status === 'up' ? 'actif ' + esc(p.speed) : 'DOWN'}</td><td>${bps(p.in)} / ${bps(p.out)}</td></tr>`).join('') + '</table>' +
        `<div class="muted" style="margin-top:8px">Cliquez une ligne pour ouvrir le détail du port (erreurs, VLAN, compteurs).</div>`;
    }
  } else if (sel && sel.t === 'dev' && d.switches[sel.i]) {
    const s = d.switches[sel.i], p = s.ports.find(x => x.n === sel.n);
    if (p) {
      const cat = tClass(p), al = alertsFor(s.name).filter(a => a.port === p.n), nb = p.nb || {};
      title.textContent = 'Appareil connecté';
      h = `<div class="dt" style="font-size:17px">${esc(p.desc || nb.name || p.mac || 'Appareil non identifié')}</div>
        <div class="muted"><i class="tdot" style="background:${TCAT[cat].c}"></i>${esc(TCAT[cat].l)} · sur ${esc(s.name)} port ${esc(p.name)}</div>` +
        sec('Liaison', kv('Port', esc(p.name)) + kv('Vitesse', esc(p.speed) + ' ' + esc(p.duplex)) + kv('VLAN', p.vlan || (p.macs[0] ? p.macs[0].vlan : '-')) + kv('Entrant', bps(p.in)) + kv('Sortant', bps(p.out)) +
          kv('Charge', (p.util * 100).toFixed(1) + ' %', lvl(p.util * 100, 85, 95)) + kv('Erreurs / s', p.err.toFixed(1), lvl(p.err, 5, 40)) + (p.poe_status ? kv('PoE', p.poe.toFixed(1) + ' W (' + esc(p.poe_status) + ')') : '')) +
        sec(`Adresses MAC (${p.mac_count})`, (p.macs || []).slice(0, 10).map(m => `<div class="mac"><code>${esc(m.mac)}</code><span class="chip2">VLAN ${m.vlan}</span><span class="muted">${esc(vendor(m.mac))}</span><button class="chip" data-copy="${esc(m.mac)}">Copier</button></div>`).join('') +
          (p.mac_count > 10 ? `<div class="muted">+ ${p.mac_count - 10} autres</div>` : '') || '<div class="muted">Aucune adresse apprise.</div>') +
        (nb.name || nb.chassis ? sec('Voisin LLDP', kv('Nom', esc(nb.name || '-')) + kv('Port distant', esc(nb.rport || '-')) + kv('Châssis', `<code>${esc(nb.chassis || '-')}</code>`) + kv('Fonctions', esc(nb.caps || '-'))) : '') +
        (p.note ? sec('Note', `<div style="white-space:pre-wrap">${esc(p.note)}</div>`) : '') +
        (al.length ? sec('Problèmes', al.map(a => `<div class="cause ${a.sev}"><b>${esc(a.title)}</b><div class="muted">${esc(a.cause)}</div></div>`).join('')) : '') +
        `<div class="actions"><button class="btn" data-open="${sel.i}|${p.n}">Ouvrir le port</button><button class="btn alt" data-i="${sel.i}">Voir le switch</button></div>`;
    }
  }
  if (!h) {
    title.textContent = 'Vue d\'ensemble';
    const tot = {};
    M.devs.forEach(l => l.forEach(dv => { tot[dv.cat] = (tot[dv.cat] || 0) + 1; }));
    const n = Object.values(tot).reduce((a, b) => a + b, 0);
    h = `<div class="dt" style="font-size:17px">${d.switches.length} switches · ${n} appareils</div><div class="muted">Réseau supervisé</div>` +
      sec('Appareils par catégorie', Object.keys(TCAT).filter(c => tot[c]).map(c => `<div class="dl"><span><i class="tdot" style="background:${TCAT[c].c}"></i>${esc(TCAT[c].l)}</span><b>${tot[c]}</b></div>`).join('')) +
      sec('Comment l\'utiliser', '<ul class="steps"><li><b>Clic sur un switch</b> : déplie ses appareils par catégorie</li><li><b>Clic sur une catégorie</b> : liste les appareils</li><li><b>Clic sur un appareil</b> : détails, MAC, port, PoE</li><li><b>Clic sur un lien</b> : ports et débit de chaque liaison</li><li><b>Molette</b> : zoom · <b>glisser</b> : déplacer</li><li><b>Recherche</b> : ne garde que les appareils correspondants</li></ul>');
  }
  if (box._h !== h) { const top = box.scrollTop; box.innerHTML = h; box.scrollTop = top; box._h = h; }
}

/* ---------- interactions ---------- */
(function () {
  const T = S.topo, svg = $('topo');
  let drag = null;
  const apply = () => { const g = svg.querySelector('#topoG'); if (g) g.setAttribute('transform', `translate(${T.x},${T.y}) scale(${T.k})`); };
  svg.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    drag = {sx: e.clientX, sy: e.clientY, x: T.x, y: T.y, moved: false};
    svg.classList.add('grabbing');
  });
  window.addEventListener('mousemove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (drag.moved) { T.x = drag.x + dx; T.y = drag.y + dy; apply(); }
  });
  window.addEventListener('mouseup', () => {
    if (!drag) return;
    if (drag.moved) { T.suppress = true; setTimeout(() => { T.suppress = false; }, 60); }
    drag = null; svg.classList.remove('grabbing');
  });
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, k0 = T.k;
    const k1 = Math.max(0.25, Math.min(2.5, k0 * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    T.x = mx - (mx - T.x) * k1 / k0; T.y = my - (my - T.y) * k1 / k0; T.k = k1;
    apply();
  }, {passive: false});
  $('topoSearch').addEventListener('input', e => { T.q = e.target.value; if (S.data) render(); });
})();

const _prevExtra = window.onExtraClick;
window.onExtraClick = e => {
  const T = S.topo, t = e.target;
  if (T.suppress && t.closest && t.closest('#topo')) return true;  // fin d'un glisser : pas un clic
  let el;
  const flip = (set, k) => { if (set.has(k)) set.delete(k); else set.add(k); };
  if ((el = t.closest('[data-tn]'))) { const i = +el.dataset.tn; flip(T.exp, i); T.sel = {t: 'sw', i}; render(); return true; }
  if ((el = t.closest('[data-tc]'))) { flip(T.cat, el.dataset.tc); render(); return true; }
  if ((el = t.closest('[data-td]'))) { const [i, n] = el.dataset.td.split('|'); T.sel = {t: 'dev', i: +i, n: +n}; render(); return true; }
  if ((el = t.closest('[data-tm]'))) { T.more.add(el.dataset.tm); render(); return true; }
  if ((el = t.closest('[data-te]'))) { T.sel = {t: 'edge', key: el.dataset.te}; render(); return true; }
  if ((el = t.closest('[data-tcx]'))) { const [i, c] = el.dataset.tcx.split('|'); T.exp.add(+i); T.cat.add(i + '|' + c); T.sel = {t: 'sw', i: +i}; render(); return true; }
  if ((el = t.closest('[data-thide]'))) { flip(T.hide, el.dataset.thide); render(); return true; }
  if (t.closest('#topoProb')) { T.prob = !T.prob; render(); return true; }
  if (t.closest('#topoExpand')) { S.data.switches.forEach((_, i) => { T.exp.add(i); Object.keys(TCAT).forEach(c => T.cat.add(i + '|' + c)); }); render(); return true; }
  if (t.closest('#topoCollapse')) { T.exp.clear(); T.cat.clear(); T.more.clear(); render(); return true; }
  if (t.closest('#topoFit')) { T.needFit = true; render(); return true; }
  return _prevExtra(e);
};
