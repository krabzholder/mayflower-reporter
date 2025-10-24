---
layout: default
title: "Citator"
---

# Citator
This page lists cases by official reporter citation. It is regenerated automatically on each build.

<div id="citator-list">Loading…</div>

<script>
(async function(){
  try {
    const r = await fetch('/_data/search.json');
    const data = await r.json();
    const list = data.slice().sort((a,b) => {
      if(a.volume !== b.volume) return a.volume - b.volume;
      return a.page_start - b.page_start;
    });
    const html = list.map(i => `<div><a href="${i.path}">${i.reporter_cite}</a> — ${i.judge||''}</div>`).join('');
    document.getElementById('citator-list').innerHTML = html || 'No cases yet.';
  } catch(e){
    document.getElementById('citator-list').innerHTML = 'No cases yet.';
  }
})();
</script>
