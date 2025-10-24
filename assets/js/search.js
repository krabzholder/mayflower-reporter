async function loadIndex(){
  try{
    const base = (typeof window !== 'undefined' && window.__base) ? window.__base : '/';
    const r = await fetch(base + '_data/search.json');
    return await r.json();
  }catch(e){ return []; }
}

function renderResults(items){
  const box = document.querySelector('.search-results');
  if(!box) return;
  if(!items.length){ box.innerHTML = '<div>No matches.</div>'; return; }
  box.innerHTML = items.slice(0,100).map(i =>
    `<div><a href="${(window.__base||'/').replace(/\/$/,'') + i.path}">${i.reporter_cite}</a> — ${i.judge||''} <span style="color:#888">${i.docket?('· '+i.docket):''}</span></div>`
  ).join('');
}

window.addEventListener('DOMContentLoaded', async () => {
  const q = document.getElementById('q');
  const idx = await loadIndex();
  if(!q) return;
  q.addEventListener('input', () => {
    const term = q.value.trim().toLowerCase();
    if(!term){ document.querySelector('.search-results').innerHTML=''; return; }
    const hits = idx.filter(d =>
      (d.title||'').toLowerCase().includes(term) ||
      (d.reporter_cite||'').toLowerCase().includes(term) ||
      (d.judge||'').toLowerCase().includes(term) ||
      (d.docket||'').toLowerCase().includes(term)
    );
    renderResults(hits);
  });
});
