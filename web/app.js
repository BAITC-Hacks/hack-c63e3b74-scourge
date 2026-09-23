const form = document.querySelector('#search-form');
const statusNode = document.querySelector('#status');
const results = document.querySelector('#results');
const submit = document.querySelector('#submit');
const toggle = document.querySelector('#compare-toggle');
const secondDate = document.querySelector('#compare-date');
const aiForm = document.querySelector('#ai-form');
const aiBrief = document.querySelector('#ai-brief');
const aiParse = document.querySelector('#ai-parse');
const aiStatus = document.querySelector('#ai-status');
const aiFeedback = document.querySelector('#ai-feedback');
const preferencesInput = document.querySelector('#style-preferences');
const names = {dense:'Много вариантов', rare:'Редкая категория', no_matches:'Пустая выдача', category_absent:'Нет категории', venue:'Банкетный зал', december:'Декабрьский сезон'};
let busy = false;
let aiAvailable = false;
let disabledControls = [];

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function compareMode(value) {
  toggle.checked = value;
  document.querySelector('#compare-field').hidden = !value;
  document.querySelector('#compare-note').hidden = !value;
  secondDate.required = value;
}
toggle.addEventListener('change', () => compareMode(toggle.checked));

function setBusy(value) {
  busy = value;
  if (value) {
    disabledControls = Array.from(document.querySelectorAll('button, input, select, textarea'), control => [control, control.disabled]);
    disabledControls.forEach(([control]) => { control.disabled = true; });
  } else {
    disabledControls.forEach(([control, disabled]) => { control.disabled = disabled; });
    disabledControls = [];
  }
}

async function api(path, request) {
  const response = await fetch(path, request);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Ошибка сервиса');
  return data;
}

function post(request) {
  return {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request)};
}

function languageInputs() {
  return Array.from(document.querySelectorAll('input[name="languages"]'));
}

function fill(request) {
  for (const key of ['city', 'category', 'format', 'date', 'budget', 'duration_hours']) {
    const input = form.elements.namedItem(key);
    input.value = request[key] == null ? '' : String(request[key]);
    if (input.tagName === 'SELECT') input.value = String(request[key] || '').toLocaleLowerCase('ru');
  }
  const languages = Array.isArray(request.languages) ? request.languages : (request.language ? [request.language] : []);
  const selected = languages.map(value => String(value).toLocaleLowerCase('ru'));
  languageInputs().forEach(input => { input.checked = selected.includes(input.value); });
}

function requestPayload() {
  const request = {};
  for (const key of ['city', 'category', 'format', 'date', 'budget', 'duration_hours']) {
    request[key] = form.elements.namedItem(key).value;
  }
  request.budget = Number(request.budget);
  request.duration_hours = request.duration_hours === '' ? null : Number(request.duration_hours);
  request.languages = languageInputs().filter(input => input.checked).map(input => input.value);
  request.language = null;
  return request;
}

function readPreferences() {
  const preferences = preferencesInput.value.split('\n').map(line => line.trim()).filter(Boolean);
  if (preferences.length > 5 || preferences.some(value => value.length > 200)) {
    throw new Error('Укажите не больше 5 пожеланий, каждое до 200 символов и с новой строки.');
  }
  return preferences;
}

function resetBrief() {
  preferencesInput.value = '';
  aiBrief.value = '';
  aiFeedback.replaceChildren();
  aiFeedback.hidden = true;
  aiStatus.className = 'ai-status';
  aiStatus.textContent = aiAvailable ? 'Опишите событие — перенесём условия в форму для проверки.' : 'AI сейчас недоступен. Заполните форму ниже — обычный подбор работает.';
}

function renderStyleMatches(article, matches) {
  if (!Array.isArray(matches) || !matches.length) return;
  const section = el('div', undefined, 'style-matches');
  section.append(el('p', 'ВАШИ ПОЖЕЛАНИЯ', 'reason-heading'));
  matches.forEach(match => {
    const supported = match.status === 'supported' && typeof match.quote === 'string' && match.quote.trim();
    const item = el('div', undefined, supported ? 'style-match supported' : 'style-match unknown');
    item.append(el('p', `${match.preference} — ${supported ? 'есть подтверждение в описании' : 'нужно уточнить'}`));
    if (supported) item.append(el('blockquote', match.quote));
    section.append(item);
  });
  article.append(section);
}

function render(data, day) {
  const section = el('section', undefined, 'result-group');
  section.append(el('h3', new Date(day + 'T12:00:00').toLocaleDateString('ru-RU', {day:'numeric', month:'long', year:'numeric'})), el('p', data.message, 'summary'));
  const cards = el('div', undefined, 'cards');
  data.cards.forEach(card => {
    const article = el('article', undefined, 'card');
    const top = el('div', undefined, 'card-top');
    const identity = el('div');
    identity.append(el('h4', card.name), el('div', `${card.category} · ${card.city} · ${card.id}`, 'meta'));
    top.append(identity, el('div', `${card.price_kind === 'starting' ? 'от ' : ''}${new Intl.NumberFormat('ru-RU').format(card.price)} ₸`, 'price'));
    article.append(top);
    const badges = el('div', undefined, 'badges');
    card.notices.forEach(notice => badges.append(el('span', notice, notice === 'Добавлен командой' ? 'badge team' : 'badge')));
    article.append(badges, el('p', 'ПОЧЕМУ ПОДХОДИТ', 'reason-heading'), el('p', card.explanation, 'explanation'));
    renderStyleMatches(article, card.style_matches);
    cards.append(article);
  });
  section.append(cards);
  if (!data.cards.length) {
    const recovery = el('div', undefined, 'empty');
    recovery.append(el('p', data.recovery_message || 'Попробуйте другую дату, бюджет или условия подбора.'));
    for (const suggestion of (Array.isArray(data.suggestions) ? data.suggestions : [])) {
      const item = el('div', undefined, 'suggestion');
      const button = el('button', suggestion.label);
      button.type = 'button';
      button.disabled = busy;
      button.addEventListener('click', () => { if (busy) return; fill(suggestion.request); compareMode(false); search(); });
      item.append(button, el('p', suggestion.message, 'hint'));
      recovery.append(item);
    }
    section.append(recovery);
  }
  if (data.quality.message) section.append(el('p', data.quality.message));
  const detail = el('details');
  detail.append(el('summary', 'Почему другие профили не вошли'), el('p', data.exclusion_counting));
  const labels = {date_outside_calendar:'Нет календаря на эту дату', date_busy:'Заняты', date_unavailable:'Нет свободной даты', over_budget:'Выше бюджета', format_mismatch:'Другой формат', language_mismatch:'Другой язык', duration_exceeded:'Недостаточно часов'};
  const list = el('ul');
  Object.entries(data.exclusion_counts).forEach(([key, count]) => list.append(el('li', `${labels[key] || key}: ${count}`)));
  detail.append(list, el('p', `Всего в каталоге: ${data.total}. В выбранных городе и категории: ${data.city_category_count}. Подходят: ${data.eligible_count}.`));
  section.append(detail);
  return section;
}

function renderComparison(data) {
  const section = el('section', undefined, 'comparison-summary');
  section.append(el('h3', 'Что изменилось между датами'), el('p', data.message));
  if (data.changes.length) {
    const list = el('ul');
    data.changes.forEach(change => list.append(el('li', change.message)));
    section.append(list);
  }
  return section;
}

async function parseBrief() {
  if (busy || !aiAvailable || !aiForm.reportValidity()) return;
  if (!aiBrief.value.trim()) {
    aiStatus.textContent = 'Сначала опишите ваше событие.';
    return;
  }
  const text = aiBrief.value.trim();
  setBusy(true);
  aiStatus.className = 'ai-status';
  aiStatus.textContent = 'Разбираем описание и пожелания…';
  aiFeedback.replaceChildren();
  aiFeedback.hidden = true;
  try {
    const data = await api('/api/ai/parse', post({text}));
    fill(data.request);
    compareMode(false);
    preferencesInput.value = (data.preferences || []).join('\n');
    results.replaceChildren();
    statusNode.className = '';
    statusNode.textContent = 'Условия обновлены из описания. Проверьте форму и нажмите «Подобрать команду».';
    aiStatus.textContent = data.ready ? 'Описание разобрано. Проверьте заполненные условия и пожелания перед подбором.' : 'Нужно уточнить условия. Заполните недостающие поля в форме ниже.';
    const feedback = [...(data.questions || []), ...(data.warnings || [])];
    feedback.forEach(message => aiFeedback.append(el('li', message)));
    aiFeedback.hidden = feedback.length === 0;
  } catch (error) {
    aiStatus.textContent = `Не удалось разобрать описание: ${error.message}. Условия можно заполнить вручную.`;
    aiStatus.className = 'ai-status error';
  } finally {
    setBusy(false);
  }
}
aiForm.addEventListener('submit', event => { event.preventDefault(); parseBrief(); });

async function search() {
  if (busy || !form.reportValidity()) return;
  const request = requestPayload();
  const comparing = toggle.checked;
  let preferences;
  try {
    preferences = comparing ? [] : readPreferences();
  } catch (error) {
    statusNode.textContent = error.message;
    statusNode.className = 'error';
    return;
  }
  const useAI = !comparing && aiAvailable && preferences.length > 0;
  const dates = comparing ? [request.date, secondDate.value] : [request.date];
  setBusy(true);
  statusNode.className = '';
  statusNode.textContent = useAI ? 'Проверяем условия и ищем подтверждения вашим пожеланиям…' : 'Проверяем условия и календарь…';
  results.replaceChildren();
  results.className = comparing ? 'compare-grid' : '';
  try {
    const path = comparing ? '/api/compare' : (useAI ? '/api/ai/recommend' : '/api/recommend');
    const payload = comparing ? {...request, compare_date:dates[1]} : (useAI ? {...request, preferences} : request);
    const data = await api(path, post(payload));
    if (comparing) results.append(renderComparison(data));
    (comparing ? data.results : [data]).forEach((response, index) => results.append(render(response, response.request_date || dates[index])));
    if (comparing) {
      statusNode.textContent = 'Одинаковые условия, две даты. Пожелания к атмосфере не учитывались. Порядок: меньшая цена, затем id.';
    } else if (data.ai) {
      statusNode.textContent = [data.ai.message, data.ranking_rule].filter(Boolean).join(' ');
    } else {
      statusNode.textContent = 'Подбор готов. Порядок: меньшая цена, затем id.';
      if (preferences.length && !aiAvailable) statusNode.textContent += ' AI сейчас недоступен: пожелания к атмосфере не учитывались.';
    }
  } catch (error) {
    statusNode.textContent = error.message;
    statusNode.className = 'error';
  } finally {
    setBusy(false);
    results.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}
form.addEventListener('submit', event => { event.preventDefault(); search(); });

async function init() {
  try {
    const meta = await api('/api/meta');
    for (const [field, key] of Object.entries({city:'cities', category:'categories', format:'formats'})) {
      const select = form.elements.namedItem(field);
      select.append(new Option('Выберите…', ''));
      meta[key].forEach(value => select.append(new Option(value.charAt(0).toUpperCase() + value.slice(1), value)));
    }
    const languages = document.querySelector('#language-options');
    meta.languages.forEach(value => {
      const label = el('label', undefined, 'language-option');
      const input = el('input');
      input.type = 'checkbox';
      input.name = 'languages';
      input.value = value;
      label.append(input, el('span', value.charAt(0).toUpperCase() + value.slice(1)));
      languages.append(label);
    });
    document.querySelector('#catalog').textContent = `${meta.total} профилей · добавлено командой: ${meta.team_count} · календарь осень–зима 2026`;
    aiAvailable = Boolean(meta.ai && meta.ai.configured);
    aiParse.disabled = !aiAvailable;
    resetBrief();
    const demos = document.querySelector('#demo-buttons');
    for (const demo of meta.demos) {
      if (!names[demo.id]) continue;
      const button = el('button', names[demo.id]);
      button.type = 'button';
      button.addEventListener('click', () => { if (busy) return; resetBrief(); fill(demo.request); compareMode(false); search(); });
      demos.append(button);
    }
    const compare = el('button', 'Сравнить две даты');
    compare.type = 'button';
    compare.addEventListener('click', () => {
      if (busy) return;
      resetBrief();
      fill(meta.demos.find(demo => demo.id === 'dense').request);
      compareMode(true);
      secondDate.value = meta.demos.find(demo => demo.id === 'other_date').request.date;
      search();
    });
    demos.append(compare);
    fill(meta.demos.find(demo => demo.id === 'dense').request);
    submit.disabled = false;
  } catch (error) {
    statusNode.textContent = `Не удалось загрузить каталог: ${error.message}. Обновите страницу.`;
    statusNode.className = 'error';
    aiStatus.textContent = 'AI недоступен, пока не загружен каталог. Обновите страницу.';
  }
}
init();
