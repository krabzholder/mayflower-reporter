---
layout: default
title: "Mayflower Reporter"
---
<h1>Mayflower Reporter (M.2d)</h1>
<p>Search published rulings by title, citation, judge, or docket. Type below to filter.</p>

<div class="searchbar">
  <input id="q" placeholder="Search cases…" autocomplete="off">
</div>
<div class="search-results" aria-live="polite"></div>

<h2>All Cases</h2>
<ul id="all-cases">
  {% for c in site.cases %}
    <li><a href="{{ c.url }}">{{ c.title }}</a> — {{ c.reporter_cite }}</li>
  {% endfor %}
</ul>
