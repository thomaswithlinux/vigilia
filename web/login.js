const f = document.getElementById('f'), u = document.getElementById('u'), p = document.getElementById('p'),
  b = document.getElementById('b'), e = document.getElementById('e'), cr = document.getElementById('codeRow'), c = document.getElementById('c');
let needCode = false;
f.addEventListener('submit', async ev => {
  ev.preventDefault();
  b.disabled = true; e.textContent = '';
  try {
    const body = {user: u.value, password: p.value};
    if (needCode) body.code = c.value;
    const r = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (r.ok) {
      const j = await r.json().catch(() => ({}));
      if (j.need_totp) {  // mot de passe correct, le compte exige la double authentification
        needCode = true; cr.hidden = false; c.required = true; c.focus();
        e.textContent = 'Saisissez le code de votre application d\'authentification.';
        b.disabled = false;
        return;
      }
      location.reload();
      return;
    }
    e.textContent = r.status === 429 ? 'Trop de tentatives, reessayez dans une minute' : (needCode ? 'Code ou identifiants invalides' : 'Identifiants invalides');
  } catch (x) { e.textContent = 'Serveur injoignable'; }
  b.disabled = false; p.value = ''; c.value = '';
  if (needCode) { needCode = false; cr.hidden = true; c.required = false; }
  p.focus();
});

document.getElementById('theme').addEventListener('click', () => {
  const t = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('vigilia-theme', t); } catch (e) { /* stockage indisponible */ }
});
