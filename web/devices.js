'use strict';
/* Appareils : recherche + filtres (switch, VLAN, constructeur, type, vitesse, PoE, deplaces, nouveaux, problemes), tri par colonne, export CSV. */
Object.assign(S, {dev: {sort: 'sw', dir: 1}});
const DEV_COLS = [['mac', 'Adresse MAC', 172], ['ven', 'Constructeur', 196], ['cat', 'Type', 190], ['vlan', 'VLAN', 62], ['sw', 'Switch', 140], ['port', 'Port', 74],
  ['name', 'Nom / voisin', 0], ['spd', 'Vitesse', 74], ['poe', 'PoE', 66], ['first', 'Vu depuis', 130], ['moves', 'Déplacé', 82]];
const DEV_SELECTS = {devSw: 'Tous les switches', devVlan: 'Tous les VLAN', devVen: 'Tous les constructeurs', devCat: 'Tous les types', devSpd: 'Toutes les vitesses'};

function devRows(d) {
  const rows = [];
  d.switches.forEach((sw, si) => sw.ports.forEach(p => {
    if (p.status !== 'up') return;
    (p.macs || []).forEach(m => rows.push({si, sw, p, mac: m.mac, vlan: m.vlan, first: m.first, moves: m.moves, ven: vendor(m.mac) || 'Inconnu', cat: tClass(p), prob: !!portSev(sw.name, p.n)}));
  }));
  return rows;
}

function fillDevSelect(id, pairs) {  // pairs : [valeur, libelle]
  const el = $(id), cur = el.value;
  const html = `<option value="">${DEV_SELECTS[id]}</option>` + pairs.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  if (el._h !== html) { el.innerHTML = html; el._h = html; el.value = pairs.some(([v]) => String(v) === cur) ? cur : ''; }
}

const devFilters = () => ({q: $('devSearch').value.trim().toLowerCase(), sw: $('devSw').value, vlan: $('devVlan').value, ven: $('devVen').value, cat: $('devCat').value, spd: $('devSpd').value,
  poe: $('devPoe').checked, moved: $('devMoved').checked, fresh: $('devNew').checked, prob: $('devProb').checked, hide: $('devHide').checked});

function devSortKey(r, k) {
  switch (k) {
    case 'mac': return r.mac;
    case 'ven': return r.ven.toLowerCase();
    case 'cat': return TCAT[r.cat].l;
    case 'vlan': return r.vlan;
    case 'sw': return r.sw.name + String(r.p.n).padStart(4, '0');
    case 'port': return r.p.n;
    case 'name': return (r.p.desc || '').toLowerCase();
    case 'spd': return r.p.cap;
    case 'poe': return r.p.poe || 0;
    case 'first': return r.first || 0;
    default: return r.moves || 0;
  }
}

RENDER.devices = function (d) {
  const all = devRows(d), F = devFilters();
  // listes deroulantes alimentees par les donnees reelles
  fillDevSelect('devSw', d.switches.map(s => [s.name, s.name]));
  fillDevSelect('devVlan', [...new Set(all.map(r => r.vlan))].sort((a, b) => a - b).map(v => [v, 'VLAN ' + v]));
  fillDevSelect('devVen', [...new Set(all.map(r => r.ven))].sort().map(v => [v, v]));
  fillDevSelect('devCat', Object.keys(TCAT).filter(c => all.some(r => r.cat === c)).map(c => [c, TCAT[c].l]));
  fillDevSelect('devSpd', [...new Set(all.map(r => r.p.speed))].sort((a, b) => parseFloat(a) * (/G/.test(a) ? 1000 : 1) - parseFloat(b) * (/G/.test(b) ? 1000 : 1)).map(v => [v, v]));
  const f2 = devFilters();
  const rows = all.filter(r => {
    if (f2.hide && r.p.mac_count > 8) return false;
    if (f2.sw && r.sw.name !== f2.sw) return false;
    if (f2.vlan && String(r.vlan) !== f2.vlan) return false;
    if (f2.ven && r.ven !== f2.ven) return false;
    if (f2.cat && r.cat !== f2.cat) return false;
    if (f2.spd && r.p.speed !== f2.spd) return false;
    if (f2.poe && !(r.p.poe > 0)) return false;
    if (f2.moved && !r.moves) return false;
    if (f2.fresh && !(r.first && d.now - r.first < 86400)) return false;
    if (f2.prob && !r.prob) return false;
    return !f2.q || (r.mac + ' ' + r.vlan + ' ' + r.sw.name + ' ' + r.p.name + ' ' + r.p.desc + ' ' + r.ven + ' ' + TCAT[r.cat].l + ' ' + (r.p.note || '')).toLowerCase().includes(f2.q);
  });
  const k = S.dev.sort, dir = S.dev.dir;
  rows.sort((a, b) => { const x = devSortKey(a, k), y = devSortKey(b, k); return (x < y ? -1 : x > y ? 1 : 0) * dir; });
  S.dev.rows = rows;
  const active = [f2.sw, f2.vlan, f2.ven, f2.cat, f2.spd].filter(Boolean).length + [f2.poe, f2.moved, f2.fresh, f2.prob].filter(Boolean).length + (f2.q ? 1 : 0);
  $('devCount').textContent = `${rows.length} appareil${rows.length > 1 ? 's' : ''} sur ${all.length}` + (active ? ` · ${active} filtre${active > 1 ? 's' : ''} actif${active > 1 ? 's' : ''}` : '') + (rows.length > 500 ? ' (500 affichés)' : '');
  $('devReset').disabled = !active && f2.hide;
  $('devTbl').innerHTML = '<colgroup>' + DEV_COLS.map(c => `<col${c[2] ? ` style="width:${c[2]}px"` : ''}>`).join('') + '</colgroup><tr>' +
    DEV_COLS.map(c => `<th class="sortable${k === c[0] ? ' on' : ''}" data-dsort="${c[0]}">${c[1]}${k === c[0] ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr>' +
    rows.slice(0, 500).map(r => `<tr class="row" data-open="${r.si}|${r.p.n}"><td><code>${esc(r.mac)}</code></td><td>${esc(r.ven)}</td><td><i class="tdot" style="background:${TCAT[r.cat].c}"></i>${esc(TCAT[r.cat].l)}</td>` +
      `<td>${r.vlan}</td><td>${esc(r.sw.name)}</td><td class="mono">${esc(r.p.name)}</td><td>${esc(r.p.desc)}${r.p.note ? ' <span class="chip2" title="' + esc(r.p.note) + '">note</span>' : ''}</td>` +
      `<td>${esc(r.p.speed)}</td><td>${r.p.poe > 0 ? r.p.poe.toFixed(1) + ' W' : '-'}</td><td>${r.first ? fdate(r.first) : '-'}</td><td class="${r.moves ? 'warn' : ''}">${r.moves ? r.moves + ' fois' : '-'}</td></tr>`).join('');
};

function resetDevFilters() {
  ['devSw', 'devVlan', 'devVen', 'devCat', 'devSpd'].forEach(id => { $(id).value = ''; });
  ['devPoe', 'devMoved', 'devNew', 'devProb'].forEach(id => { $(id).checked = false; });
  $('devHide').checked = true; $('devSearch').value = '';
  S.dev.sort = 'sw'; S.dev.dir = 1;
  render();
}

function exportDevCsv() {
  const rows = [['Adresse MAC', 'Constructeur', 'Type', 'VLAN', 'Switch', 'Port', 'Nom / voisin', 'Vitesse', 'PoE (W)', 'Premiere vue', 'Deplacements']];
  (S.dev.rows || []).forEach(r => rows.push([r.mac, r.ven, TCAT[r.cat].l, r.vlan, r.sw.name, r.p.name, r.p.desc, r.p.speed, r.p.poe || 0, r.first ? fdate(r.first) : '', r.moves || 0]));
  const q = x => { let t = String(x ?? ''); if (/^[=+\-@\t\r]/.test(t)) t = "'" + t; return '"' + t.replace(/"/g, '""') + '"'; };  // neutralise l'injection de formules Excel
  const csv = '﻿' + rows.map(r => r.map(q).join(';')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
  a.download = 'appareils.csv'; a.click(); URL.revokeObjectURL(a.href);
}

['devSw', 'devVlan', 'devVen', 'devCat', 'devSpd', 'devPoe', 'devMoved', 'devNew', 'devProb'].forEach(id => $(id).addEventListener('change', () => S.data && render()));

const _prevExtraD = window.onExtraClick;
window.onExtraClick = e => {
  const t = e.target;
  let el;
  if ((el = t.closest('[data-dsort]'))) {
    const k = el.dataset.dsort;
    if (S.dev.sort === k) S.dev.dir = -S.dev.dir; else { S.dev.sort = k; S.dev.dir = 1; }
    render();
    return true;
  }
  if (t.closest('#devReset')) { resetDevFilters(); return true; }
  if (t.closest('#devCsv')) { exportDevCsv(); return true; }
  return _prevExtraD(e);
};
