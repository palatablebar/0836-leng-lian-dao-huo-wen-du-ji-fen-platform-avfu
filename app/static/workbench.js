(function () {
  var state = { payload: null, kind: 'bars', run: null, approved: false };
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function setNotice(text) { $('notice').textContent = text || ''; }
  function renderIssues(data) {
    $('issue-count').textContent = data.issues.length + ' 条';
    $('issue-list').innerHTML = data.issues.length ? data.issues.map(function (item) {
      return '<li><span>' + esc(item.line || '-') + '</span><span>' + esc(item.key || '无主键') + '</span><code>' + esc(item.code) + '</code></li>';
    }).join('') : '<li class="empty">暂无异常</li>';
  }
  function renderBreakdown(items) {
    if (!items || !items.length) return '';
    return '<details><summary>' + items.length + ' 项</summary><ul>' + items.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('') + '</ul></details>';
  }
  function renderRows(data) {
    var labels = Object.assign({label: '记录'}, state.resultColumns);
    var source = data.row_kind === 'source';
    var hasBreakdown = data.rows.some(function (row) { return row.breakdown && row.breakdown.length; });
    var keys = source ? state.inputColumns : Object.keys(labels).filter(function (key) {
      return data.rows.some(function (row) { return Object.hasOwn(row, key); });
    });
    $('row-count').textContent = source ? data.rows.length + ' 行预览' :
      data.summary.PASS + ' 通过 / ' + data.summary.REVIEW + ' 复核 / ' + data.summary.REJECT + ' 阻断';
    var tail = source ? '' : '<th>结论</th>' + (hasBreakdown ? '<th>计算分项</th>' : '');
    $('row-head').innerHTML = '<tr>' + keys.map(function (key) { return '<th>' + esc(labels[key] || key) + '</th>'; }).join('') + tail + '</tr>';
    $('row-body').innerHTML = data.rows.length ? data.rows.map(function (row) {
      var values = keys.map(function (key) { return '<td class="' + (typeof row[key] === 'number' ? 'num' : '') + '">' + esc(row[key]) + '</td>'; }).join('');
      var verdict = source ? '' : '<td><span class="verdict" data-v="' + esc(row.verdict) + '">' + esc(row.verdict || '') + '</span><br><small>' + esc(row.reason || '') + '</small></td>';
      var breakdown = hasBreakdown ? '<td>' + renderBreakdown(row.breakdown) + '</td>' : '';
      return '<tr>' + values + verdict + breakdown + '</tr>';
    }).join('') : '<tr><td class="empty" colspan="' + (keys.length + (source ? 0 : 1)) + '">没有可展示条目</td></tr>';
  }
  function renderLedger(data) {
    if (!data.ledger) { $('ledger-list').innerHTML = '<p class="empty">运行对账后显示</p>'; return; }
    var values = data.ledger;
    $('ledger-list').innerHTML = [
      ['来源行', values.counts.input], ['采信行', values.counts.accepted], ['隔离行', values.counts.isolated],
      ['精确重复', values.counts.duplicates], ['忽略行', values.counts.ignored], ['计算条目', values.counts.computed]
    ].map(function (row) { return '<div class="ledger-row"><span>' + row[0] + '</span><strong>' + row[1] + '</strong></div>'; }).join('') +
      '<div class="ledger-row"><span>' + esc(values.metric_field) + '</span><strong>' + esc(values.metric_total) + '</strong></div>' +
      values.checks.map(function (check) { return '<div class="ledger-row"><span>' + esc(check.label) + '</span><strong class="' + (check.ok ? 'check-ok' : 'check-bad') + '">' + (check.ok ? '通过' : '异常') + '</strong></div>'; }).join('');
  }
  function render(data) {
    state.payload = data;
    $('chart-label').textContent = Object.values(state.resultColumns)[0];
    $('m-input').textContent = data.counts.input;
    $('m-accepted').textContent = data.counts.accepted;
    $('m-isolated').textContent = data.counts.isolated + data.counts.duplicates;
    $('m-rejected').textContent = data.summary.REJECT;
    renderRows(data);
    renderIssues(data);
    renderLedger(data);
    window.renderChart($('chart'), data.chart && data.chart.length ? (state.kind || 'bars') : 'bars', data.chart || []);
  }
  function stageButtons(stages) {
    $('stage-nav').innerHTML = stages.map(function (stage, index) {
      return '<button type="button" data-stage="' + stage.id + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '">' + esc(stage.name) + '</button>';
    }).join('');
    Array.from(document.querySelectorAll('[data-stage]')).forEach(function (button) {
      button.addEventListener('click', function () {
        document.querySelectorAll('[data-stage]').forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
        loadStage(button.getAttribute('data-stage'));
      });
    });
  }
  async function loadStage(stage) {
    try {
      setNotice('');
      document.body.setAttribute('aria-busy', 'true');
      var payload = await request('/api/stages/' + stage, {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      render(payload);
    } catch (error) { setNotice(error.message); }
    finally { document.body.removeAttribute('aria-busy'); }
  }
  function syncReviewButtons() {
    var run = state.run;
    var terminal = run && (run.status === 'SUPERSEDED');
    var decided = run && (run.status === 'APPROVED' || run.status === 'HELD');
    $('sign').disabled = terminal || decided || (run && run.summary.REJECT > 0);
    $('hold').disabled = terminal || decided;
    var downloadable = run && (run.status === 'APPROVED' || run.status === 'SUPERSEDED');
    $('download').hidden = !downloadable;
    if (downloadable) $('download').href = '/api/runs/' + run.run_id + '/evidence';
  }
  function renderCalibration(run) {
    var cal = run && run.calibration;
    if (!run) {
      $('release-pill').textContent = '未执行批次';
      $('release-pill').removeAttribute('data-r');
      $('rep-sensor').innerHTML = '';
      $('rep-send').disabled = true;
      $('tol-list').innerHTML = '<li class="empty">尚未登记容差</li>';
      $('rep-list').innerHTML = '<li class="empty">尚未收到校准报告</li>';
      $('cal-note').textContent = '';
      return;
    }
    var sensors = run.sensors || [];
    $('rep-sensor').innerHTML = sensors.map(function (sid) {
      return '<option value="' + esc(sid) + '">' + esc(sid) + '</option>';
    }).join('');
    $('rep-send').disabled = sensors.length === 0 || run.status === 'SUPERSEDED';
    if (cal) {
      $('release-pill').textContent = cal.release_label + (cal.complete ? ' · 实测' : ' · 包络');
      $('release-pill').setAttribute('data-r', cal.release_result);
      var tol = cal.tolerances || {};
      var tolKeys = Object.keys(tol).sort();
      $('tol-list').innerHTML = tolKeys.length ? tolKeys.map(function (sid) {
        return '<li><span>' + esc(sid) + '</span><strong>±' + esc(tol[sid]) + '</strong></li>';
      }).join('') : '<li class="empty">尚未登记容差</li>';
      var off = cal.measured_offsets || {};
      var offKeys = Object.keys(off).sort();
      $('rep-list').innerHTML = offKeys.length ? offKeys.map(function (sid) {
        return '<li><span>' + esc(sid) + '</span><strong>' + esc(off[sid]) + '</strong></li>';
      }).join('') : '<li class="empty">尚未收到校准报告</li>';
      var note = [];
      if (cal.missing_tolerances.length) note.push('缺容差：' + cal.missing_tolerances.join('、'));
      if (cal.missing_reports.length) note.push('待报告：' + cal.missing_reports.join('、'));
      if (cal.over_limit) note.push('重算判定存在温区超限');
      $('cal-note').textContent = note.join('；');
    }
  }
  function applyRun(run) {
    state.run = run;
    state.approved = run.status === 'APPROVED' || run.status === 'SUPERSEDED';
    render(run);
    $('run-status').textContent = run.status + ' · rev ' + run.revision;
    $('revision').textContent = 'rev ' + run.revision;
    syncReviewButtons();
    renderCalibration(run);
  }
  async function runBatch() {
    try {
      setNotice('');
      $('run').disabled = true;
      var run = await request('/api/runs', {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      applyRun(run);
    } catch (error) { setNotice(error.message); }
    finally { $('run').disabled = false; }
  }
  async function review(decision) {
    if (!state.run) return;
    try {
      var run = await request('/api/runs/' + state.run.run_id + '/review', {
        method: 'POST',
        body: JSON.stringify({decision: decision, comment: $('comment').value, expected_revision: state.run.revision})
      });
      applyRun(run);
    } catch (error) { setNotice(error.message); }
  }
  async function saveTolerance() {
    var sensorId = $('tol-sensor').value.trim();
    var tolerance = $('tol-value').value.trim();
    if (!sensorId || !tolerance) { setNotice('请填写探针与允许误差'); return; }
    try {
      setNotice('');
      await request('/api/tolerances', {method: 'POST', body: JSON.stringify({sensor_id: sensorId, tolerance: tolerance})});
      $('tol-sensor').value = ''; $('tol-value').value = '';
      if (state.run) {
        var run = await request('/api/runs/' + state.run.run_id);
        applyRun(run);
      }
    } catch (error) { setNotice(error.message); }
  }
  async function submitReport() {
    if (!state.run) return;
    var sensorId = $('rep-sensor').value;
    var offset = $('rep-offset').value.trim();
    if (!sensorId || !offset) { setNotice('请选择探针并填写实测偏差'); return; }
    try {
      setNotice('');
      var run = await request('/api/runs/' + state.run.run_id + '/calibration', {
        method: 'POST',
        body: JSON.stringify({sensor_id: sensorId, measured_offset: offset})
      });
      $('rep-offset').value = '';
      if (run.report_unchanged) setNotice('同一份报告已登记，未新增版本');
      if (run.superseded) setNotice('实测超限，已停止凭旧结论放行；凭据仍可下载');
      applyRun(run);
    } catch (error) { setNotice(error.message); }
  }
  async function boot() {
    try {
      var catalog = await request('/api/catalog');
      state.kind = catalog.chart;
      state.resultColumns = catalog.result_columns;
      state.inputColumns = catalog.columns;
      stageButtons(catalog.stages.slice(0, 5));
      document.querySelector('.rail-note').textContent = catalog.code + ' · ' + catalog.stages[6].name;
      await loadStage('intake');
    } catch (error) { setNotice(error.message); }
    $('run').addEventListener('click', runBatch);
    $('sign').addEventListener('click', function () { review('APPROVED'); });
    $('hold').addEventListener('click', function () { review('HELD'); });
    $('tol-save').addEventListener('click', saveTolerance);
    $('rep-send').addEventListener('click', submitReport);
    $('profile').addEventListener('change', function () {
      state.run = null; state.approved = false;
      $('sign').disabled = true; $('hold').disabled = true; $('download').hidden = true;
      $('run-status').textContent = '未执行批次'; $('revision').textContent = 'rev 0';
      renderCalibration(null);
      loadStage('intake');
    });
  }
  document.addEventListener('DOMContentLoaded', boot);
})();
