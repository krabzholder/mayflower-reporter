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

{% if site.cases and site.cases.size > 0 %}
  <ul id="all-cases">
    {% for c in site.cases %}
      <li>
        <a href="{{ c.url | relative_url }}">{{ c.title }}</a>
        {% if c.reporter_cite %} — {{ c.reporter_cite }}{% endif %}
      </li>
    {% endfor %}
  </ul>
{% else %}
  <p class="muted">No cases have been published yet.<br>
  To add one, upload a PDF to <code>/rulings/</code> and push to the repository.</p>
{% endif %}
