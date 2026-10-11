'use strict';
/* Mon compte : derniere connexion, mot de passe, double authentification (TOTP). Bouton "Changer de compte". */

async function openAccount2() {
  if (!S.me) return;
  try { Object.assign(S.me, await api('/api/me')); } catch (e) { /* on garde ce qu'on sait */ }
  const me = S.me, ll = me.last_login ? `${fsec(me.last_login.t)} depuis ${esc(me.last_login.ip)}` : 'première connexion';
  $('mbox').innerHTML = `<div class="mh"><div><h2 id="mtitle">Mon compte</h2><div class="muted">${esc(me.user)} - ${ROLE_LABEL[me.role] || esc(me.role)}</div></div><button class="ghost" id="mclose" aria-label="Fermer">✕</button></div>
    <div class="dl" style="margin-top:10px"><span>Connexion précédente</span><b>${ll}</b></div>
    <div class="muted" style="font-size:12px">Si cette connexion ne vous dit rien, changez votre mot de passe immédiatement.</div>
    <div class="mh4">Changer mon mot de passe</div>
    <label class="fld">Mot de passe actuel<input id="pwOld" type="password" autocomplete="current-password"></label>
    <label class="fld">Nouveau mot de passe<input id="pwNew" type="password" autocomplete="new-password"></label>
    <label class="fld">Confirmer le nouveau mot de passe<input id="pwNew2" type="password" autocomplete="new-password"></label>
    <div class="muted" style="font-size:12px;margin-top:6px">12 caractères minimum, au moins 3 types parmi : minuscules, majuscules, chiffres, symboles. Vos autres sessions seront déconnectées.</div>
    <div id="pwMsg" class="err" role="alert" style="text-align:left"></div>
    <button class="btn" data-pwsave="1">Changer le mot de passe</button>
    <div class="mh4" style="margin-top:22px">Double authentification ${me.totp ? '<span class="pill ok">activée</span>' : '<span class="pill">désactivée</span>'}</div>` +
    (me.totp
      ? `<div class="muted">Un code à 6 chiffres est demandé à chaque connexion, en plus du mot de passe.</div>
         <label class="fld">Mot de passe actuel<input id="mfaPw" type="password" autocomplete="current-password"></label>
         <label class="fld">Code actuel de l'application<input id="mfaCode" inputmode="numeric" maxlength="8" autocomplete="one-time-code"></label>
         <div id="mfaMsg" class="err" role="alert" style="text-align:left"></div>
         <button class="btn alt" style="margin-left:0" data-mfaoff="1">Désactiver la double authentification</button>`
      : `<div class="muted">Ajoute un code à 6 chiffres (Google Authenticator, Microsoft Authenticator, Aegis, FreeOTP…) à votre mot de passe : même volé, celui-ci ne suffit plus. Recommandé, surtout pour les administrateurs.</div>
         <div id="mfaBox"></div><div id="mfaMsg" class="err" role="alert" style="text-align:left"></div>
         <button class="btn alt" id="mfaStartBtn" style="margin-left:0" data-mfastart="1">Activer la double authentification</button>`);
  $('modal').hidden = false;
}

async function mfaStart() {
  const r = await api('/api/totp/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
  if (!r.secret) { $('mfaMsg').textContent = (r.error || 'Échec') + '.'; return; }
  const spaced = r.secret.match(/.{1,4}/g).join(' ');
  $('mfaStartBtn').hidden = true;
  $('mfaBox').innerHTML = `<ol class="steps" style="color:var(--text)"><li>Dans votre application : <b>Ajouter un compte → Saisir une clé de configuration</b> (type : basé sur l'heure).</li>
    <li>Nom : <code>Vigilia</code> · Clé : <code class="secret">${esc(spaced)}</code> <button class="chip" data-copy="${esc(r.secret)}">Copier la clé</button></li>
    <li>Saisissez ci-dessous le code à 6 chiffres affiché pour valider.</li></ol>
    <label class="fld">Code affiché dans l'application<input id="mfaCode" inputmode="numeric" maxlength="8" autocomplete="one-time-code"></label>
    <button class="btn" data-mfaon="1">Valider et activer</button>`;
  $('mfaCode').focus();
}

async function mfaEnable() {
  const r = await api('/api/totp/enable', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: $('mfaCode').value})});
  if (r.ok) { S.me.totp = true; openAccount2(); } else $('mfaMsg').textContent = (r.error || 'Échec') + '.';
}

async function mfaDisable() {
  const r = await api('/api/totp/disable', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: $('mfaPw').value, code: $('mfaCode').value})});
  if (r.ok) { S.me.totp = false; openAccount2(); } else $('mfaMsg').textContent = (r.error || 'Échec') + '.';
}

$('account').removeEventListener('click', window.openAccount);
$('account').addEventListener('click', openAccount2);
$('switchUser').addEventListener('click', async () => { await fetch('/logout', {method: 'POST'}); location.reload(); });

const _prevExtraA = window.onExtraClick;
window.onExtraClick = e => {
  const t = e.target;
  if (t.closest('[data-mfastart]')) { mfaStart(); return true; }
  if (t.closest('[data-mfaon]')) { mfaEnable(); return true; }
  if (t.closest('[data-mfaoff]')) { mfaDisable(); return true; }
  return _prevExtraA(e);
};
