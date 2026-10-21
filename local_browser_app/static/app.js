const TOKEN = document.querySelector('meta[name="app-token"]').content;
const $ = (id) => document.getElementById(id);
const value = (id) => $(id).value.trim();
const checked = (id) => $(id).checked;
const escapeHtml = (text) => String(text ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

async function api(path, payload = null, method = 'POST') {
  const options = {method, headers: {'X-Survey-App-Token': TOKEN}};
  if (payload !== null) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch (_) { body = {error: `HTTP ${response.status}`}; }
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body.result ?? body;
}

function setStatus(id, text, error = false) {
  const node = $(id); node.textContent = text || ''; node.classList.toggle('error', error);
}

let toastTimer;
function toast(message, error = false) {
  const node = $('toast');
  node.textContent = message; node.classList.toggle('error', error); node.classList.remove('hidden');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => node.classList.add('hidden'), 4200);
}

async function startJob(path, payload, onComplete) {
  const response = await api(path, payload);
  const job = response.job;
  const consoleNode = $('job-console');
  consoleNode.classList.remove('hidden');
  $('job-name').textContent = job.name;
  $('job-state').textContent = job.status;
  $('job-log').textContent = '';
  $('job-result').textContent = '';
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const current = await api(`/api/jobs/${job.id}`, null, 'GET');
        $('job-state').textContent = current.status;
        const log = current.logs.join('\n');
        const logNode = $('job-log');
        if (logNode.textContent !== log) { logNode.textContent = log; logNode.scrollTop = logNode.scrollHeight; }
        if (current.status === 'failed') {
          $('job-result').textContent = current.error;
          toast(current.error || `${current.name} failed`, true);
          reject(new Error(current.error));
          return;
        }
        if (current.status === 'complete') {
          $('job-result').textContent = summarizeResult(current.result);
          toast(`${current.name} complete`);
          if (onComplete) onComplete(current.result);
          resolve(current.result);
          return;
        }
        setTimeout(poll, 650);
      } catch (error) {
        reject(error);
      }
    };
    poll();
  });
}

function summarizeResult(result) {
  if (!result) return 'Complete.';
  if (result.output_path) return `Output: ${result.output_path}`;
  if (result.outputs) return result.outputs.map(row => row.tables || row.output_path || '').filter(Boolean).join('\n');
  return JSON.stringify(result, null, 2);
}

$('job-close').addEventListener('click', () => $('job-console').classList.add('hidden'));

// Tabs
document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(node => node.classList.toggle('active', node === button));
  document.querySelectorAll('.tool').forEach(node => node.classList.toggle('active', node.id === button.dataset.tab));
  if (button.dataset.tab === 'questions') loadQuestionFilters();
}));

// Table generator
let tableJobs = [];
$('tg-discover').addEventListener('click', async () => {
  setStatus('tg-status', 'Scanning…');
  try {
    const result = await api('/api/table-gen/discover', {root: value('tg-root'), output_root: value('tg-output-root')});
    tableJobs = result.jobs;
    const body = $('tg-jobs'); body.innerHTML = '';
    result.jobs.forEach((job, index) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input type="checkbox" class="tg-choice" data-index="${index}" checked></td>
        <td><strong>${escapeHtml(job.stem)}</strong><small>${escapeHtml(job.docx)}</small></td>
        <td>${escapeHtml(job.folder)}</td>
        <td><span class="pill">${escapeHtml(job.validation.status)}</span><small>${escapeHtml(job.validation.detail)}</small></td>
        <td><small>TABLES: ${escapeHtml(job.tables_out)}<br>BANNERS: ${escapeHtml(job.banners_out)}</small></td>`;
      body.appendChild(tr);
    });
    $('tg-jobs-card').classList.toggle('hidden', !result.jobs.length);
    setStatus('tg-status', result.jobs.length ? `${result.jobs.length} job(s) found` : 'No matching DOCX/PDF pairs found', !result.jobs.length);
  } catch (error) { setStatus('tg-status', error.message, true); }
});

$('tg-run').addEventListener('click', async () => {
  const selected = [...document.querySelectorAll('.tg-choice:checked')].map(node => tableJobs[Number(node.dataset.index)]);
  if (!selected.length) return toast('Select at least one questionnaire.', true);
  setStatus('tg-status', 'Running…');
  try {
    await startJob('/api/table-gen/run', {jobs: selected, include_banners: checked('tg-banners'), include_cover: checked('tg-cover')}, result => {
      setStatus('tg-status', `${result.completed} job(s) complete`);
    });
  } catch (error) { setStatus('tg-status', error.message, true); }
});

// Sheet merge
function mergePayload() {
  return {
    primary_path: value('sm-primary'), secondary_path: value('sm-secondary'),
    primary_sheet: value('sm-primary-sheet'), secondary_sheet: value('sm-secondary-sheet'),
    primary_join: value('sm-primary-join'), secondary_join: value('sm-secondary-join'),
    output_path: value('sm-output'), mapping_text: value('sm-mapping'),
    mapping_mode: checked('sm-manual-only') ? 'manual_only' : 'auto',
    row_order: value('sm-row-order'), report_enabled: checked('sm-report'), archive_secondary: checked('sm-archive')
  };
}

$('sm-preview').addEventListener('click', async () => {
  setStatus('sm-status', 'Reading files…');
  try {
    const result = await api('/api/sheet-merge/preview', mergePayload());
    $('sm-mapping').value = result.reviewed_mapping_text;
    $('sm-map-count').textContent = `${result.analysis.mapped_columns} mapped`;
    const a = result.analysis;
    const metricRows = [
      [a.primary_rows, 'Primary rows'], [a.secondary_rows, 'Secondary rows'],
      [a.conflict_rows, 'Matching keys'], [a.mapped_columns, 'Output mappings'],
      [a.primary_duplicate_rows, 'Primary duplicate rows'], [a.secondary_duplicate_rows, 'Secondary duplicate rows']
    ];
    $('sm-metrics').innerHTML = metricRows.map(([n,label]) => `<div class="metric"><strong>${n}</strong><span>${label}</span></div>`).join('');
    const extra = result.mapping.filter(row => ['secondary_extra','timeseries_extra'].includes(row.method));
    $('sm-notes').textContent = `${a.primary_join} → ${a.secondary_join}\n${extra.length} unmapped secondary field(s) will be preserved under survey-scoped names.`;
    $('sm-review').classList.remove('hidden');
    setStatus('sm-status', 'Preflight complete');
  } catch (error) { setStatus('sm-status', error.message, true); }
});

$('sm-run').addEventListener('click', async () => {
  setStatus('sm-status', 'Merging…');
  try {
    await startJob('/api/sheet-merge/run', mergePayload(), result => setStatus('sm-status', `Complete: ${result.output_path}`));
  } catch (error) { setStatus('sm-status', error.message, true); }
});

// OE coder
let oeResponses = [];
let oeSelected = null;
function oeBase() { return {session_path: value('oe-session')}; }

function defaultOeExportPath() {
  const source = value('oe-data');
  if (!source) return;
  const kind = value('oe-export-kind');
  const suffix = {coded_csv: '.OE-coded.csv', wincross: '.OE-tables.txt', codebook: '.OE-codebook.xlsx', audit: '.OE-audit.csv'}[kind];
  $('oe-export-path').value = source.replace(/\.(csv|xlsx)$/i, '') + suffix;
}

function loadOeDashboard(dashboard) {
  $('oe-session').value = dashboard.session_path;
  const select = $('oe-question');
  const prior = select.value;
  select.innerHTML = dashboard.questions.map(q => `<option value="${q.id}">${escapeHtml(q.name)} · ${q.text_column}</option>`).join('');
  if ([...select.options].some(option => option.value === prior)) select.value = prior;
  $('oe-workspace').classList.toggle('hidden', !dashboard.questions.length);
  if (dashboard.questions.length) refreshOeResponses();
}

$('oe-import').addEventListener('click', async () => {
  setStatus('oe-status', 'Importing…');
  try {
    const result = await api('/api/oe/import', {
      data_path: value('oe-data'), session_path: value('oe-session'), key_column: value('oe-key'),
      codelist_path: value('oe-codelist'), survey_id: value('oe-survey')
    });
    loadOeDashboard(result.dashboard); defaultOeExportPath();
    const s = result.import;
    setStatus('oe-status', `${s.response_count} response(s), ${s.question_count} question(s); ${s.new_response_count} new`);
  } catch (error) { setStatus('oe-status', error.message, true); }
});

$('oe-open').addEventListener('click', async () => {
  setStatus('oe-status', 'Opening…');
  try { const result = await api('/api/oe/dashboard', oeBase()); loadOeDashboard(result); setStatus('oe-status', 'Session open'); }
  catch (error) { setStatus('oe-status', error.message, true); }
});

async function refreshOeResponses(preserveId = null) {
  const questionId = Number(value('oe-question'));
  if (!questionId) return;
  setStatus('oe-progress', 'Loading…');
  try {
    const result = await api('/api/oe/responses', {...oeBase(), question_id: questionId, status: value('oe-filter'), search: value('oe-search')});
    oeResponses = result.responses;
    const list = $('oe-responses');
    list.innerHTML = result.responses.map(row => `<div class="response-row" data-id="${row.id}"><div class="row-top"><span>${escapeHtml(row.record_key)} · row ${row.row_number}</span><span class="codes">${escapeHtml(row.final_codes.join(', ') || 'blank')}</span></div><p>${escapeHtml(row.verbatim || '(blank verbatim)')}</p></div>`).join('');
    list.querySelectorAll('.response-row').forEach(node => node.addEventListener('click', () => selectOeResponse(Number(node.dataset.id))));
    const datalist = $('oe-code-list');
    datalist.innerHTML = result.codes.map(code => `<option value="${escapeHtml(code.code)}">${escapeHtml(code.label || '(label not set)')}</option>`).join('');
    setStatus('oe-progress', `${result.total} response(s)${result.limited ? ' · showing first 250' : ''}`);
    const target = preserveId && oeResponses.some(row => row.id === preserveId) ? preserveId : (oeResponses[0]?.id || null);
    if (target) selectOeResponse(target); else clearOeEditor();
  } catch (error) { setStatus('oe-progress', error.message, true); }
}

function selectOeResponse(id) {
  oeSelected = oeResponses.find(row => row.id === id) || null;
  document.querySelectorAll('.response-row').forEach(node => node.classList.toggle('active', Number(node.dataset.id) === id));
  if (!oeSelected) return clearOeEditor();
  $('oe-record').textContent = oeSelected.record_key;
  $('oe-import-state').textContent = oeSelected.import_status;
  $('oe-verbatim').textContent = oeSelected.verbatim || '(blank verbatim)';
  $('oe-original').textContent = `Original codes: ${oeSelected.original_codes.join(', ') || '(none)'}`;
  $('oe-codes').value = oeSelected.final_codes.join(', ');
  $('oe-note').value = oeSelected.note;
  $('oe-flagged').checked = oeSelected.flagged;
}
function clearOeEditor() { oeSelected = null; $('oe-record').textContent = 'No response selected'; $('oe-verbatim').textContent = 'No responses match this filter.'; $('oe-codes').value = ''; $('oe-note').value = ''; }

$('oe-refresh').addEventListener('click', () => refreshOeResponses(oeSelected?.id));
$('oe-question').addEventListener('change', () => refreshOeResponses());
$('oe-filter').addEventListener('change', () => refreshOeResponses());
$('oe-search').addEventListener('keydown', event => { if (event.key === 'Enter') refreshOeResponses(); });
$('oe-save').addEventListener('click', async () => {
  if (!oeSelected) return toast('Select a response.', true);
  try {
    const result = await api('/api/oe/assign', {...oeBase(), response_id: oeSelected.id, codes: value('oe-codes'), note: value('oe-note'), flagged: checked('oe-flagged'), apply_matching: checked('oe-matching'), matching_timeseries_only: true});
    toast(`Saved ${result.applied} response(s)`); await refreshOeResponses(oeSelected.id);
  } catch (error) { toast(error.message, true); }
});
$('oe-reset').addEventListener('click', async () => {
  if (!oeSelected) return toast('Select a response.', true);
  try { await api('/api/oe/reset', {...oeBase(), response_id: oeSelected.id}); toast('Original codes restored'); await refreshOeResponses(oeSelected.id); }
  catch (error) { toast(error.message, true); }
});
$('oe-save-code').addEventListener('click', async () => {
  try {
    await api('/api/oe/code', {...oeBase(), question_id: Number(value('oe-question')), code: value('oe-new-code'), label: value('oe-new-label'), supercategory: value('oe-new-super'), direction: value('oe-new-direction'), active: true});
    toast('Code label saved'); await refreshOeResponses(oeSelected?.id);
  } catch (error) { toast(error.message, true); }
});
$('oe-export-kind').addEventListener('change', defaultOeExportPath);
$('oe-export').addEventListener('click', async () => {
  try { await startJob('/api/oe/export', {...oeBase(), kind: value('oe-export-kind'), output_path: value('oe-export-path')}); }
  catch (_) { /* surfaced by job console */ }
});

// Question browser
let questionFiltersLoaded = false;
let questionPage = 1;
let questionPages = 0;
async function loadQuestionFilters() {
  if (questionFiltersLoaded) return;
  try {
    const data = await api('/api/questions/filters', {});
    const populate = (id, rows) => rows.forEach(item => $(id).insertAdjacentHTML('beforeend', `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`));
    populate('qb-state', data.states); populate('qb-client', data.clients); populate('qb-type', data.types); populate('qb-family', data.families);
    $('qb-count').textContent = `${data.count.toLocaleString()} indexed questions`;
    questionFiltersLoaded = true;
  } catch (error) { toast(error.message, true); }
}

async function runQuestionSearch(page = 1) {
  questionPage = page;
  $('qb-results').innerHTML = '<div class="empty">Searching…</div>';
  try {
    const result = await api('/api/questions/search', {query: value('qb-query'), mode: value('qb-mode'), state: value('qb-state'), client: value('qb-client'), question_type: value('qb-type'), question_family: value('qb-family'), page});
    questionPage = result.page; questionPages = result.pages;
    $('qb-count').textContent = `${result.total.toLocaleString()} result(s)`;
    $('qb-page').textContent = result.pages ? `Page ${result.page} of ${result.pages}` : 'No pages';
    $('qb-prev').disabled = result.page <= 1; $('qb-next').disabled = !result.pages || result.page >= result.pages;
    if (!result.results.length) { $('qb-results').innerHTML = '<div class="empty">No questions matched those filters.</div>'; return; }
    $('qb-results').innerHTML = result.results.map(row => `<article class="question-card">
      <div class="question-meta"><span class="pill">${escapeHtml(row.survey_id)}</span><span>Q${escapeHtml(row.qid)}</span><span>${escapeHtml(row.client)}</span><span>${escapeHtml(row.state_code || row.region)}</span><span>${escapeHtml(row.question_type)}</span><span>${escapeHtml(row.question_family)}</span></div>
      <h4>${escapeHtml(row.question_text)}</h4>${row.item_text ? `<p class="item">${escapeHtml(row.item_text)}</p>` : ''}
      <div class="options">${row.options.map(option => `<span class="option">${escapeHtml(option)}</span>`).join('')}</div>
    </article>`).join('');
  } catch (error) { $('qb-results').innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
}
$('qb-search').addEventListener('click', () => runQuestionSearch(1));
$('qb-query').addEventListener('keydown', event => { if (event.key === 'Enter') runQuestionSearch(1); });
$('qb-prev').addEventListener('click', () => runQuestionSearch(Math.max(1, questionPage - 1)));
$('qb-next').addEventListener('click', () => runQuestionSearch(Math.min(questionPages, questionPage + 1)));

// Auto Results
function toggleAutoSource() {
  const xlsx = value('ar-source') === 'xlsx';
  $('ar-marginals-label').classList.toggle('hidden', xlsx);
  $('ar-xlsx-label').classList.toggle('hidden', !xlsx);
}
$('ar-source').addEventListener('change', toggleAutoSource);
$('ar-run').addEventListener('click', async () => {
  setStatus('ar-status', 'Generating…');
  try {
    await startJob('/api/auto-results/run', {source_mode: value('ar-source'), marginals_path: value('ar-marginals'), xlsx_path: value('ar-xlsx'), template_path: value('ar-template'), output_path: value('ar-output'), placeholder: $('ar-placeholder').value, mode: 'fix', write_report: checked('ar-report')}, result => {
      setStatus('ar-status', `Complete: ${result.output_path}`);
    });
  } catch (error) { setStatus('ar-status', error.message, true); }
});

// Quota checker
let quotaReview = null;

function quotaOptions(columns, selected) {
  return [''].concat(columns).map(column => `<option value="${escapeHtml(column)}"${column === selected ? ' selected' : ''}>${escapeHtml(column || 'Not mapped')}</option>`).join('');
}

function quotaStatusClass(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'full' || key === 'ok') return 'full';
  if (key === 'open') return 'open';
  if (key === 'needs mapping') return 'unmapped';
  return 'issue';
}

function quotaNumber(value) {
  return value === null || value === undefined ? '—' : Number(value).toLocaleString();
}

function quotaLimit(value, share) {
  if (value === null || value === undefined) return '—';
  const percent = share === null || share === undefined ? '' : ` · ${Math.round(Number(share) * 100)}%`;
  return `${Number(value).toLocaleString()}${percent}`;
}

function showQuotaColumnProfile(column) {
  const profile = quotaReview?.sample?.profiles?.[column];
  const node = $('qc-column-profile');
  if (!profile || !column) { node.innerHTML = ''; return; }
  const values = profile.values.map(item => `<span><strong>${escapeHtml(item.value)}</strong> ${item.count.toLocaleString()}</span>`).join('');
  node.innerHTML = `<strong>${escapeHtml(column)}</strong><small>${profile.nonblank.toLocaleString()} nonblank · ${profile.distinct.toLocaleString()} distinct</small><div>${values || '<em>No nonblank values</em>'}</div>`;
}

function bindQuotaProfileEvents() {
  document.querySelectorAll('.qc-column-select').forEach(select => {
    select.addEventListener('focus', () => showQuotaColumnProfile(select.value));
    select.addEventListener('change', () => showQuotaColumnProfile(select.value));
  });
}

function renderQuotaMappings(result) {
  const columns = result.sample.columns;
  $('qc-fixed-mappings').innerHTML = result.mapping.fixed.map(item => `<label>${escapeHtml(item.label)}${item.required ? ' <small>required</small>' : ''}<select class="qc-column-select qc-fixed-map" data-key="${escapeHtml(item.key)}">${quotaOptions(columns, item.column)}</select></label>`).join('');

  const categorySection = $('qc-category-section');
  categorySection.classList.toggle('hidden', !result.mapping.categories.length);
  $('qc-category-mappings').innerHTML = result.mapping.categories.map(item => `<label>${escapeHtml(item.category)} <small>${item.quota_count} quota${item.quota_count === 1 ? '' : 's'}</small><select class="qc-column-select qc-category-map" data-category="${escapeHtml(item.category)}">${quotaOptions(columns, item.column)}</select></label>`).join('');

  const oversampleSection = $('qc-oversample-section');
  oversampleSection.classList.toggle('hidden', !result.mapping.sections.length);
  $('qc-section-mappings').innerHTML = result.mapping.sections.map(item => `<div class="quota-section-map">
    <div><strong>${escapeHtml(item.section)}</strong><small>${item.required ? 'Extra filter required because this workbook has multiple oversamples.' : 'Extra filter optional.'}</small></div>
    <label>Filter column<select class="qc-column-select qc-section-column" data-section="${escapeHtml(item.section)}">${quotaOptions(columns, item.column)}</select></label>
    <label>Matching values<input class="qc-section-values" data-section="${escapeHtml(item.section)}" value="${escapeHtml(item.values)}" placeholder="Example: 2 or Republican"></label>
  </div>`).join('');
  bindQuotaProfileEvents();
}

function renderExactQuotaBlock(block) {
  const hasCode = block.rows.some(row => row.code);
  const headers = block.columns.map(column => `<th>${escapeHtml(column.label)}</th>`).join('');
  const rows = block.rows.map(row => {
    const cells = block.columns.map(column => {
      const cell = row.cells[column.id];
      if (!cell) return '<td class="quota-cell empty-cell">—</td>';
      const statusClass = quotaStatusClass(cell.status);
      return `<td class="quota-cell ${statusClass}" title="${escapeHtml(cell.source)}">
        <div class="quota-cell-values"><span><small>Quota</small><strong>${quotaNumber(cell.target)}</strong></span><span><small>Current</small><strong>${quotaNumber(cell.current)}</strong></span></div>
        <div class="quota-delta">${escapeHtml(cell.delta)} · ${escapeHtml(cell.status)}</div>
      </td>`;
    }).join('');
    return `<tr><th class="quota-row-label">${escapeHtml(row.label)}</th>${hasCode ? `<td class="quota-code">${escapeHtml(row.code)}</td>` : ''}${cells}<td class="quota-total"><span>${quotaNumber(row.target)}</span><strong>${quotaNumber(row.current)}</strong></td></tr>`;
  }).join('');
  return `<div class="quota-block"><h4>${escapeHtml(block.title)}</h4><div class="quota-table-wrap"><table class="quota-table exact"><thead><tr><th>${block.section === 'Base Sample' ? 'Region / group' : 'Quota group'}</th>${hasCode ? '<th>Code</th>' : ''}${headers}<th>Total<br><small>Quota / current</small></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

function renderLimitQuotaBlock(block) {
  const rows = block.rows.map(row => `<tr class="${quotaStatusClass(row.status)}">
    <th class="quota-row-label">${escapeHtml(row.label)}</th>
    <td>${quotaLimit(row.minimum, row.minimum_share)}</td>
    <td class="quota-current">${quotaNumber(row.current)}</td>
    <td>${quotaLimit(row.maximum, row.maximum_share)}</td>
    <td>${escapeHtml(row.delta)}</td>
    <td><span class="quota-status ${quotaStatusClass(row.status)}">${escapeHtml(row.status)}</span></td>
    <td><input class="qc-match" data-quota-id="${escapeHtml(row.id)}" value="${escapeHtml(row.match_values)}" title="${escapeHtml(row.source)}"></td>
  </tr>`).join('');
  return `<div class="quota-block"><h4>${escapeHtml(block.title)}</h4><div class="quota-table-wrap"><table class="quota-table limits"><thead><tr><th>${escapeHtml(block.category)}</th><th>Minimum</th><th>Current</th><th>Maximum</th><th>Difference</th><th>Status</th><th>Sample value(s)</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

function renderQuotaSheet(result) {
  $('qc-sheet-name').textContent = `${result.workbook.sheet} · ${result.workbook.path}`;
  $('qc-title').textContent = result.workbook.title;
  let priorSection = null;
  const html = [];
  result.blocks.forEach(block => {
    if (block.section !== priorSection) {
      const target = result.summary.section_targets[block.section];
      const current = result.summary.section_counts[block.section];
      html.push(`<div class="quota-section-heading"><div><span>Section</span><h4>${escapeHtml(block.section)}</h4></div><div><small>Target</small><strong>${quotaNumber(target)}</strong></div><div><small>Sample</small><strong>${quotaNumber(current)}</strong></div></div>`);
      priorSection = block.section;
    }
    html.push(block.type === 'exact' ? renderExactQuotaBlock(block) : renderLimitQuotaBlock(block));
  });
  $('qc-sheet').innerHTML = html.join('') || '<div class="empty">No quota blocks were detected.</div>';
}

function renderQuotaReview(result) {
  quotaReview = result;
  const summary = result.summary;
  const baseCurrent = summary.section_counts['Base Sample'];
  $('qc-summary').innerHTML = [
    [summary.base_target, 'Base target'], [baseCurrent, 'Base sample'], [summary.sample_count, 'All sample rows'],
    [summary.open_cells, 'Open exact cells'], [summary.issues, 'Issues'], [summary.needs_mapping, 'Needs mapping']
  ].map(([number, label]) => `<div class="quota-summary-item"><strong>${quotaNumber(number)}</strong><span>${label}</span></div>`).join('');
  renderQuotaMappings(result);
  renderQuotaSheet(result);

  const notes = [...result.notes, ...result.messages];
  $('qc-notes-card').classList.toggle('hidden', !notes.length);
  $('qc-notes').innerHTML = notes.map(note => `<li>${escapeHtml(note)}</li>`).join('');
  $('qc-workspace').classList.remove('hidden');
  setStatus('qc-status', `${result.workbook.title} · sample n=${summary.sample_count.toLocaleString()}`);
}

function collectQuotaReviewPayload() {
  const mappings = {categories: {}};
  document.querySelectorAll('.qc-fixed-map').forEach(node => { mappings[node.dataset.key] = node.value; });
  document.querySelectorAll('.qc-category-map').forEach(node => { mappings.categories[node.dataset.category] = node.value; });
  const matches = {};
  document.querySelectorAll('.qc-match').forEach(node => { matches[node.dataset.quotaId] = node.value.trim(); });
  const sectionFilters = {};
  document.querySelectorAll('.qc-section-column').forEach(node => {
    const section = node.dataset.section;
    const values = [...document.querySelectorAll('.qc-section-values')].find(item => item.dataset.section === section)?.value.trim() || '';
    sectionFilters[section] = {column: node.value, values};
  });
  return {quota_path: value('qc-quota'), sample_path: value('qc-sample'), mappings, matches, section_filters: sectionFilters};
}

async function loadQuotaReview(payload = null) {
  setStatus('qc-status', 'Reading workbook and sample…');
  try {
    const result = await api('/api/quota/review', payload || {quota_path: value('qc-quota'), sample_path: value('qc-sample')});
    localStorage.setItem('survey-workbench-quota-path', value('qc-quota'));
    localStorage.setItem('survey-workbench-quota-sample', value('qc-sample'));
    renderQuotaReview(result);
  } catch (error) { setStatus('qc-status', error.message, true); }
}

$('qc-load').addEventListener('click', () => loadQuotaReview());
$('qc-apply').addEventListener('click', () => loadQuotaReview(collectQuotaReviewPayload()));
$('qc-quota').value = localStorage.getItem('survey-workbench-quota-path') || '';
$('qc-sample').value = localStorage.getItem('survey-workbench-quota-sample') || '';

// Startup health check
(async () => {
  try {
    const health = await api('/api/health', null, 'GET');
    $('health').classList.add('ok'); $('health').lastChild.textContent = ' Local · ready';
    $('tg-root').placeholder = 'C:\\…\\Job\\Table Gen';
  } catch (error) { $('health').lastChild.textContent = ' Offline'; toast(error.message, true); }
})();

