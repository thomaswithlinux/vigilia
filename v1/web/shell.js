'use strict';
/* Terminal SSH integre : s'ouvre depuis la fenetre « Se connecter en SSH ». L'utilisateur saisit son compte et son mot de passe
   (jamais ceux du service, jamais memorises) ; la sortie arrive par attente longue sur /api/shell/read. Role technicien minimum. */
Object.assign(S, {sh: {id: null, pos: 0, hist: [], hi: 0, sw: null}});
const SHELL_JSON = {'Content-Type': 'application/json'};

const _openSshBase = openSsh;
openSsh = function (spec) {
  _openSshBase(spec);
  const i = +spec.split('|')[0], sw = S.data.switches[i];
  if (!sw || !can('tech') || S.data.mode !== 'live') return;
  $('mbox').insertAdjacentHTML('beforeend', `<div class="mh4">3. Ou ouvrir un terminal ici</div>
    <div class="muted" style="font-size:12.5px">Tapez la commande ci-dessus dans votre propre terminal, ou ouvrez un shell directement dans Vigilia : vous saisissez votre compte et votre mot de passe, rien n'est enregistré.</div>
    <button class="btn" type="button" data-shellopen="${i}">&gt;_ Ouvrir un shell maintenant</button>`);
};

function shellLogin(i) {
  const sw = S.data.switches[i];
  shellStop();
  S.sh.sw = i;
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">Terminal - ${esc(sw.name)}</h2><div class="muted">${esc(sw.model)} - ${esc(sw.ip)}</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    <div id="shLogin">
      <div class="muted" style="font-size:12.5px">Connexion SSH depuis le serveur Vigilia vers ce switch. Vos commandes s'exécutent avec les droits du compte saisi.</div>
      <label class="fld">Utilisateur<input id="shUser" autocomplete="username" spellcheck="false" value="${esc(S.data.ssh_user || '')}"></label>
      <label class="fld">Mot de passe<input id="shPw" type="password" autocomplete="current-password"></label>
      <div id="shMsg" class="err" role="alert" style="text-align:left"></div>
      <button class="btn" type="button" data-shellgo="${i}">Se connecter</button>
      <button class="btn alt" type="button" data-shellback="${i}">Retour</button>
    </div>
    <div id="shTerm" hidden>
      <pre id="shOut" class="pre term" tabindex="0"></pre>
      <div class="termin"><span class="mono">›</span><input id="shIn" class="mono" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Commande"></div>
      <div class="termkeys"><button class="chip" type="button" data-shellkey="c">Ctrl+C</button><button class="chip" type="button" data-shellkey="d">Ctrl+D (quitter)</button>
        <button class="chip" type="button" data-shellend="1">Fermer le terminal</button></div>
    </div>`;
  $('modal').hidden = false;
  ($('shUser').value ? $('shPw') : $('shUser')).focus();
}

async function shellGo(i) {
  const sw = S.data.switches[i], pw = $('shPw'), msg = $('shMsg'), btn = document.querySelector('[data-shellgo]');
  if (!$('shUser').value.trim() || !pw.value) { msg.textContent = 'Saisissez le compte et le mot de passe.'; return; }
  btn.disabled = true; msg.textContent = 'Connexion en cours...';
  let r;
  try { r = await api('/api/shell/open', {method: 'POST', headers: SHELL_JSON, body: JSON.stringify({ip: sw.ip, user: $('shUser').value.trim(), password: pw.value})}); }
  finally { pw.value = ''; btn.disabled = false; }
  if (!r.id) { msg.textContent = (r.error || 'Echec') + '.'; pw.focus(); return; }
  S.sh.id = r.id; S.sh.pos = 0;
  $('shLogin').hidden = true; $('shTerm').hidden = false;
  $('shIn').focus();
  shellPump(r.id);
}

async function shellPump(id) {
  while (S.sh.id === id) {
    let r;
    try { r = await api(`/api/shell/read?id=${encodeURIComponent(id)}&since=${S.sh.pos}`); }
    catch (e) { await new Promise(res => setTimeout(res, 1500)); continue; }
    const out = $('shOut');
    if (S.sh.id !== id || !out) return;
    if (r.out) {
      const stick = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
      out.textContent = (out.textContent + r.out).slice(-100000);
      if (stick) out.scrollTop = out.scrollHeight;
    }
    if (r.pos != null) S.sh.pos = r.pos;
    if (r.closed) {
      out.textContent += '\n[session terminée]\n'; out.scrollTop = out.scrollHeight;
      S.sh.id = null; $('shIn').disabled = true;
      return;
    }
  }
}

function shellSend(data) {
  if (!S.sh.id) return;
  api('/api/shell/send', {method: 'POST', headers: SHELL_JSON, body: JSON.stringify({id: S.sh.id, data})}).catch(() => {});
}

function shellStop() {
  const id = S.sh.id;
  S.sh.id = null;
  if (id) fetch('/api/shell/close', {method: 'POST', headers: SHELL_JSON, body: JSON.stringify({id}), keepalive: true}).catch(() => {});
}

const _closeModalBase = closeModal;
closeModal = function () { shellStop(); _closeModalBase(); };
window.addEventListener('pagehide', shellStop);

document.addEventListener('keydown', e => {
  const t = e.target;
  if (t.id === 'shPw' && e.key === 'Enter') { e.preventDefault(); shellGo(S.sh.sw); return; }
  if (t.id !== 'shIn') return;
  const H = S.sh.hist;
  if (e.key === 'Enter') {
    e.preventDefault();
    const v = t.value;
    if (v.trim() && H[H.length - 1] !== v) H.push(v);
    S.sh.hi = H.length; t.value = '';
    shellSend(v + '\n');
  } else if (e.key === 'ArrowUp' && H.length) {
    e.preventDefault(); S.sh.hi = Math.max(0, S.sh.hi - 1); t.value = H[S.sh.hi];
  } else if (e.key === 'ArrowDown') {
    e.preventDefault(); S.sh.hi = Math.min(H.length, S.sh.hi + 1); t.value = H[S.sh.hi] || '';
  } else if (e.ctrlKey && e.key.toLowerCase() === 'c' && t.selectionStart === t.selectionEnd) {
    e.preventDefault(); shellSend('\x03');
  } else if (e.ctrlKey && e.key.toLowerCase() === 'd' && !t.value) {
    e.preventDefault(); shellSend('\x04');
  }
});

const _prevExtraS = window.onExtraClick;
window.onExtraClick = e => {
  const t = e.target;
  let el;
  if ((el = t.closest('[data-shellopen]'))) { shellLogin(+el.dataset.shellopen); return true; }
  if ((el = t.closest('[data-shellgo]'))) { shellGo(+el.dataset.shellgo); return true; }
  if ((el = t.closest('[data-shellback]'))) { openSsh(el.dataset.shellback + '||'); return true; }
  if ((el = t.closest('[data-shellkey]'))) { shellSend(el.dataset.shellkey === 'c' ? '\x03' : '\x04'); $('shIn').focus(); return true; }
  if (t.closest('[data-shellend]')) { closeModal(); return true; }
  return _prevExtraS(e);
};
