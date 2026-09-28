/* ================================================================
   ACAI — сменный отчёт начальника производства: общий код страниц.

   Файл в Экселе один, а смотрят его с двух сторон:

     «Производство» (/production) — как идёт цех: выпуск за смену,
     неделю и месяц, свежесть файла, загрузка новой версии;

     «Аналитика» (/analytics) — разбор за длинные периоды: где
     теряются часы по месяцам, какие причины повторяются, какая
     бригада сколько сделала за полгода и год.

   Обе страницы читают одни и те же числа из одних и тех же ручек —
   иначе два места ответили бы на один вопрос по-разному.
   ================================================================ */

// Дата из отчёта «2026-09-17» → «17.09»
const xlsDate = v => String(v || '').slice(8,10) + '.' + String(v || '').slice(5,7);


const xlsEsc = v => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const xlsHours = m => { m = Math.round(m||0); const h = Math.floor(m/60); return h ? `${h} ч ${m%60} мин` : `${m} мин`; };

// «402 простоя», а не «402 простоев»: мелочь, но по ней видно,
// писал это человек или машина.
const xlsPlural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
};

// только от пересчёта кубометров, и запятая в них — признак, что
// пересчитали не тем коэффициентом, а не подробность.
const xlsInt = v => Math.round(Number(v || 0)).toLocaleString('ru-RU');
// Кубометры — с десятыми: здесь запятая на своём месте.
const xlsM3 = v => Number(v || 0).toLocaleString('ru-RU', {maximumFractionDigits: 1});

// Кнопки периода. Отсчёт идёт от последней смены в файле, а не от
// сегодня: отчёт заполняют с задержкой, и «сегодня» по календарю
// почти всегда было бы пустым.
const OUTPUT_PERIODS = [['Последняя смена','day'], ['7 дней','week'],
                        ['Месяц','month'], ['Всё время','all']];
let _outputPeriod = 'month';

function xlsTabs(id, items, current, handler){
  const box = document.getElementById(id);
  if (!box) return;
  box.innerHTML = items.map(([label, value]) =>
    `<button type="button" class="xls-tab${value === current ? ' on' : ''}"
             onclick="${handler}('${value}')">${label}</button>`).join('');
}

// Сколько сделали кирпичей, сколько брака и сколько годных.
// Виды сведены по формату: «1,4 НФ полнател», «1.4НФ» и «1,4 НФ
// пустотел» — это три колонки в файле, но не три завода. Блок
// пересчитан из кубометров по цифре владельца: 0,0208 м³ на штуку.
async function loadXlsOutput(period){
  const box = document.getElementById('xlsOutput');
  const card = document.getElementById('xlsOutputCard');
  if (!box || !card) return;

  if (period) _outputPeriod = period;
  xlsTabs('outputTabs', OUTPUT_PERIODS, _outputPeriod, 'loadXlsOutput');

  let d = {};
  try { d = await ACAI.get('/api/production/report-output?period=' + _outputPeriod); } catch { return; }
  if (!d.products || !d.products.length) {
    card.style.display = '';
    box.innerHTML = `<div class="empty-state">За этот период в отчёте выпуска нет. Последняя смена в файле — ${d.last_shift_date ? xlsDate(d.last_shift_date) : '—'}.</div>`;
    return;
  }

  card.style.display = '';

  const defectShare = d.pieces_total
    ? (d.defect_pieces / d.pieces_total * 100).toFixed(2).replace('.', ',') : null;

  box.innerHTML = `
    <div style="font-size:12px;color:var(--text-dim);margin-bottom:10px">${xlsEsc(d.period_title)}</div>

    <div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px;margin-bottom:12px">
      <div><b style="font-family:var(--mono);font-size:22px">${xlsInt(d.good_pieces)}</b> шт годных</div>
      <div><b style="font-family:var(--mono);font-size:20px">${xlsInt(d.pieces_total)}</b> шт сделано</div>
      <div><b style="font-family:var(--mono);font-size:20px;color:var(--warn)">${xlsInt(d.defect_pieces)}</b> шт брак и отстрел${
        defectShare ? ` · ${defectShare}%` : ''}</div>
    </div>

    <div class="xls-scroll" style="margin-bottom:12px"><table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="text-align:left;border-bottom:2px solid var(--border)">
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Вид</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Штук</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Поддонов</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Смен</th>
      </tr></thead>
      <tbody>
        ${d.products.map(p => `<tr style="border-bottom:1px solid var(--border)">
          <td style="padding:8px">${xlsEsc(p.title)}
            ${p.note ? `<div style="font-size:11px;color:var(--text-dim);margin-top:2px">${xlsEsc(p.note)}</div>` : ''}</td>
          <td style="padding:8px;font-family:var(--mono);white-space:nowrap">${xlsInt(p.pieces)}</td>
          <td style="padding:8px;font-family:var(--mono);white-space:nowrap">${
            p.pallets != null ? xlsInt(p.pallets) : '<span style="color:var(--text-dim)">—</span>'}</td>
          <td style="padding:8px;font-family:var(--mono)">${p.shifts}</td>
        </tr>`).join('')}
      </tbody>
    </table></div>

    ${d.defect_cubic ? `<div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">
      В браке ${xlsM3(d.defect_cubic)} м³ были записаны кубометрами — это блок, пересчитал по ${String(d.block_m3).replace('.', ',')} м³/шт.
    </div>` : ''}

    ${(d.other || []).length ? `
      <details style="font-size:12px;color:var(--text-dim)">
        <summary style="cursor:pointer;list-style:none">Ещё ${xlsM3(d.other_cubic)} м³ других форматов — в счёт штук не вошли <span style="color:var(--accent)">— показать</span></summary>
        <div style="margin-top:6px;line-height:1.6">
          ${d.other.map(p => `<div>• ${xlsEsc(p.title)} — ${xlsM3(p.cubic)} м³, ${p.shifts} ${xlsPlural(p.shifts,'смена','смены','смен')}</div>`).join('')}
          <div style="margin-top:4px">Сколько кубометров в штуке этих форматов, в отчёте не сказано. Скажете коэффициент — посчитаю и их.</div>
        </div>
      </details>` : ''}`;
}

// Какая смена сколько сделала. Сравниваем по штукам за смену: у одной
// бригады смен больше, и сумма сама по себе ничего не говорит.
const BRIGADE_SPANS = [['Месяц','month'], ['Полгода','half'], ['Год','year']];
let _brigadeSpan = 'month';

async function loadXlsBrigades(span){
  const box = document.getElementById('xlsBrigades');
  const card = document.getElementById('xlsBrigadesCard');
  if (!box || !card) return;

  if (span) _brigadeSpan = span;
  xlsTabs('brigadeTabs', BRIGADE_SPANS, _brigadeSpan, 'loadXlsBrigades');

  let d = {};
  try { d = await ACAI.get('/api/production/report-brigades?span=' + _brigadeSpan); } catch { return; }
  const rows = d.brigades || [];
  if (!rows.length) return;

  card.style.display = '';

  const max = Math.max(1, ...rows.map(r => r.per_shift || 0));

  box.innerHTML = `
    <div style="font-size:12px;color:var(--text-dim);margin-bottom:10px">
      ${xlsEsc(d.span_title)} — по ${d.last_shift_date ? xlsDate(d.last_shift_date) : '—'}. Столбик — штук за смену.
    </div>

    ${rows.map(r => `
      <div style="margin-bottom:12px">
        <div style="display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:3px">
          <div style="width:150px;flex-shrink:0">${xlsEsc(r.master)}</div>
          <div style="flex:1;background:var(--surface-2);border-radius:4px;height:18px;overflow:hidden;min-width:60px">
            <div style="width:${Math.round((r.per_shift||0)/max*100)}%;height:100%;background:var(--accent);opacity:.75"></div>
          </div>
          <div style="width:118px;flex-shrink:0;text-align:right;font-family:var(--mono);white-space:nowrap">${xlsInt(r.per_shift)} шт/смену</div>
        </div>
        <div style="font-size:11px;color:var(--text-dim);margin-left:160px">
          ${r.shifts} ${xlsPlural(r.shifts,'смена','смены','смен')}
          (${r.day_shifts} ${xlsPlural(r.day_shifts,'дневная','дневных','дневных')} · ${r.night_shifts} ${xlsPlural(r.night_shifts,'ночная','ночных','ночных')}),
          всего ${xlsInt(r.pieces)} шт${r.defect_share != null ? `, брак ${String(r.defect_share).replace('.', ',')}%` : ''}${
            r.no_output ? `. В ${r.no_output} ${xlsPlural(r.no_output,'смене','сменах','сменах')} выпуск в отчёте не заполнен — в «штук за смену» они не считаются` : ''}
        </div>
      </div>`).join('')}`;
}

async function loadXlsAnalytics(){
  const card = document.getElementById('xlsAnalyticsCard');
  const box = document.getElementById('xlsAnalytics');
  if (!card || !box) return;

  let d = {};
  try { d = await ACAI.get('/api/production/report-analytics'); } catch { return; }
  if (!d.loaded || !(d.months||[]).length) return;

  card.style.display = '';

  const totals = d.totals || {};
  const months = d.months || [];
  const sections = d.by_section || [];
  const reasons = d.top_reasons || [];
  const shifts = d.by_shift || [];

  const day = shifts.find(x => x.shift === 'day') || {minutes:0, cases:0};
  const night = shifts.find(x => x.shift === 'night') || {minutes:0, cases:0};
  const worstMonth = [...months].sort((a,b) => (b.downtime_minutes||0) - (a.downtime_minutes||0))[0];
  const worstSection = sections[0];
  const maxMonth = Math.max(1, ...months.map(m => m.downtime_minutes||0));
  const longest = d.longest || [];
  const worstIncident = d.worst_incident;

  // Выводы словами — как на остальных вкладках: сначала что это значит,
  // потом уже таблицы. Плановые остановки в выводы не идут: проточка
  // вальцов и переход на другой формат — это работа, а не поломка.
  const lines = [];
  if (totals.incident_minutes != null) {
    const parts = [`<b>${xlsHours(totals.incident_minutes)}</b> — поломки`];
    if (totals.organizational_minutes) parts.push(`${xlsHours(totals.organizational_minutes)} — нет сырья или связи`);
    parts.push(`${xlsHours(totals.planned_minutes)} — плановые (проточка, переходы)`);
    lines.push(`Из ${xlsHours(totals.minutes)} простоя: ` + parts.join(', ') + '.');
  }
  if (worstSection) lines.push(`Больше всего часов теряет <b>${xlsEsc(worstSection.section_title)}</b> — ${xlsHours(worstSection.minutes)} за год.`);
  if (worstMonth) lines.push(`Тяжелее всего дался <b>${xlsEsc(worstMonth.sheet)}</b>: ${xlsHours(worstMonth.downtime_minutes)} простоя.`);
  if (day.minutes && night.minutes) {
    const times = (day.minutes / Math.max(1, night.minutes)).toFixed(1);
    lines.push(`В дневную смену простоев в ${times} раза больше, чем в ночную (${xlsHours(day.minutes)} против ${xlsHours(night.minutes)}).`);
  }
  if (worstIncident) lines.push(`Самая дорогая повторяющаяся <b>поломка</b> — «${xlsEsc(worstIncident.reason)}»: ${xlsHours(worstIncident.minutes)} за ${worstIncident.cases} ${xlsPlural(worstIncident.cases,'раз','раза','раз')}.`);

  box.innerHTML = `
    <div style="display:flex;gap:18px;flex-wrap:wrap;font-size:13px;margin-bottom:14px">
      <div><b style="font-family:var(--mono);font-size:22px">${xlsHours(totals.minutes)}</b> простоя за год</div>
      <div><b style="font-family:var(--mono);font-size:22px">${totals.cases||0}</b> ${xlsPlural(totals.cases||0,'случай','случая','случаев')}</div>
      <div><b style="font-family:var(--mono);font-size:22px">${months.length}</b> ${xlsPlural(months.length,'месяц','месяца','месяцев')} в файле</div>
    </div>

    ${lines.length ? `<div style="border-left:3px solid var(--accent);padding:2px 0 2px 12px;margin-bottom:16px;font-size:14px;line-height:1.7">
      ${lines.map(l => `<div>${l}</div>`).join('')}
    </div>` : ''}

    <div style="font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em;margin:4px 0 8px">По месяцам</div>
    <div style="margin-bottom:18px">
      ${months.map(m => {
        const width = Math.round((m.downtime_minutes||0) / maxMonth * 100);
        return `<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:13px">
          <div style="width:92px;flex-shrink:0">${xlsEsc(m.sheet)}</div>
          <div style="flex:1;background:var(--surface-2);border-radius:4px;height:16px;overflow:hidden">
            <div style="width:${width}%;height:100%;background:var(--accent);opacity:.75"></div>
          </div>
          <div style="width:110px;flex-shrink:0;text-align:right;font-family:var(--mono)">${xlsHours(m.downtime_minutes)}</div>
          <div style="width:92px;flex-shrink:0;text-align:right;color:var(--text-dim);font-size:12px">${m.shifts} ${xlsPlural(m.shifts,'смена','смены','смен')}</div>
        </div>`;
      }).join('')}
    </div>

    ${reasons.length ? `
    <div style="font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em;margin:4px 0 8px">Повторяющиеся причины (2 раза и чаще)</div>
    <div class="xls-scroll" style="margin-bottom:16px"><table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="text-align:left;border-bottom:2px solid var(--border)">
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Причина (как записана в отчёте)</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Участок</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Раз</th>
        <th style="padding:8px;color:var(--text-dim);font-size:12px">Потеряно</th>
      </tr></thead>
      <tbody>
        ${reasons.map(r => `<tr style="border-bottom:1px solid var(--border)">
          <td style="padding:8px">${xlsEsc(r.reason)}
            ${r.kind === 'planned' ? '<span style="font-size:11px;color:var(--text-dim);border:1px solid var(--border);border-radius:999px;padding:1px 7px;margin-left:6px">плановая</span>' : ''}
            ${r.kind === 'organizational' ? '<span style="font-size:11px;color:var(--warn);border:1px solid var(--warn);border-radius:999px;padding:1px 7px;margin-left:6px">не ремонт</span>' : ''}
            ${(r.variants||[]).length ? `<div style="font-size:11px;color:var(--text-dim);margin-top:2px">в отчёте писали: ${(r.variants||[]).map(v=>`«${xlsEsc(v.slice(0,40))}»`).join(', ')}</div>` : ''}</td>
          <td style="padding:8px;color:var(--text-dim)">${xlsEsc(r.sections)}</td>
          <td style="padding:8px;font-family:var(--mono)">${r.cases}</td>
          <td style="padding:8px;font-family:var(--mono)">${xlsHours(r.minutes)}</td>
        </tr>`).join('')}
      </tbody>
    </table></div>` : ''}

    ${longest.length ? `
    <details>
      <summary style="cursor:pointer;font-size:12px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:.06em;list-style:none">
        Самые долгие разовые остановки <span style="font-weight:400;text-transform:none">— показать</span>
      </summary>
      <div class="xls-scroll"><table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px">
        <thead><tr style="text-align:left;border-bottom:2px solid var(--border)">
          <th style="padding:8px;color:var(--text-dim);font-size:12px">Дата</th>
          <th style="padding:8px;color:var(--text-dim);font-size:12px">Причина</th>
          <th style="padding:8px;color:var(--text-dim);font-size:12px">Участок</th>
          <th style="padding:8px;color:var(--text-dim);font-size:12px">Потеряно</th>
        </tr></thead>
        <tbody>
          ${longest.map(r => `<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:8px;color:var(--text-dim);white-space:nowrap">${xlsDate(r.date)}</td>
            <td style="padding:8px">${xlsEsc(r.reason)}
              ${r.kind === 'planned' ? '<span style="font-size:11px;color:var(--text-dim)"> · плановая</span>' : ''}
              ${r.kind === 'organizational' ? '<span style="font-size:11px;color:var(--warn)"> · не ремонт</span>' : ''}</td>
            <td style="padding:8px;color:var(--text-dim)">${xlsEsc(r.section_title)}</td>
            <td style="padding:8px;font-family:var(--mono);white-space:nowrap">${xlsHours(r.minutes)}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>
    </details>` : ''}

    ${totals.unparsed ? `<div style="font-size:12px;color:var(--warn);margin-top:10px">
      В эти числа не вошли ${totals.unparsed} ${xlsPlural(totals.unparsed,'запись','записи','записей')}, которые не удалось разобрать — они перечислены выше.
    </div>` : ''}`;
}
