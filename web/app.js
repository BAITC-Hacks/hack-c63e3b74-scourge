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
const aiSummary = document.querySelector('#ai-summary');
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
toggle.addEventListener('change', () => {
  if (busy) return;
  compareMode(toggle.checked);
  clearBriefFeedback();
  results.replaceChildren();
  statusNode.className = '';
  statusNode.textContent = 'Запустите подбор с выбранными условиями формы.';
});

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

function clearBriefFeedback() {
  aiFeedback.replaceChildren();
  aiFeedback.hidden = true;
  aiSummary.replaceChildren();
  aiSummary.hidden = true;
  aiStatus.className = 'ai-status';
  aiStatus.textContent = aiAvailable ? 'Найдём по описанию. Поля ручного подбора не влияют на этот поиск.' : 'AI сейчас недоступен. Заполните форму ниже — обычный подбор работает.';
}

function resetBrief() {
  preferencesInput.value = '';
  aiBrief.value = '';
  clearBriefFeedback();
  results.replaceChildren();
  results.className = '';
}

function formatDate(day) {
  return day ? new Date(day + 'T12:00:00').toLocaleDateString('ru-RU', {day:'numeric', month:'long', year:'numeric'}) : 'Без ограничения даты';
}

function renderBriefSummary(parsed) {
  const request = parsed.request || {};
  const languages = Array.isArray(request.languages) ? request.languages : (request.language ? [request.language] : []);
  aiSummary.replaceChildren(el('h3', 'Учтено из описания'));
  const fields = [
    ['Город', request.city || 'не ограничен'],
    ['Категория', request.category || 'не ограничена'],
    ['Мероприятие', request.format || 'не ограничено'],
    ['Дата', request.date ? formatDate(request.date) : 'не указана — без ограничения даты'],
    ['Бюджет', request.budget == null ? 'не ограничен' : `до ${new Intl.NumberFormat('ru-RU').format(request.budget)} ₸`],
    ['Часы', request.duration_hours == null ? 'не ограничены' : String(request.duration_hours)],
    ['Языки', languages.length ? languages.join(', ') : 'не ограничены'],
  ];
  const list = el('dl', undefined, 'brief-conditions');
  fields.forEach(([label, value]) => {
    const item = el('div');
    item.append(el('dt', label), el('dd', value));
    list.append(item);
  });
  aiSummary.append(list);
  if (Array.isArray(parsed.preferences) && parsed.preferences.length) {
    aiSummary.append(el('p', `Пожелания: ${parsed.preferences.join('; ')}.`));
  }
  aiSummary.hidden = false;
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

function renderCard(card, alternative = false) {
  const article = el('article', undefined, alternative ? 'card alternative-card' : 'card');
  const top = el('div', undefined, 'card-top');
  const identity = el('div');
  identity.append(el('h4', card.name), el('div', `${card.category} · ${card.city} · ${card.id}`, 'meta'));
  top.append(identity, el('div', `${card.price_kind === 'starting' ? 'от ' : ''}${new Intl.NumberFormat('ru-RU').format(card.price)} ₸`, 'price'));
  article.append(top);
  const badges = el('div', undefined, 'badges');
  (Array.isArray(card.notices) ? card.notices : []).forEach(notice => badges.append(el('span', notice, notice === 'Добавлен командой' ? 'badge team' : 'badge')));
  article.append(badges);
  if (alternative) {
    const differences = el('div', undefined, 'differences');
    differences.append(el('p', 'ОТЛИЧИЯ ОТ ЗАПРОСА', 'reason-heading'));
    if (card.proposed_date) differences.append(el('p', `Предлагаемая дата: ${formatDate(card.proposed_date)}`, 'proposed-date'));
    const list = el('ul');
    (Array.isArray(card.differences) ? card.differences : []).forEach(difference => list.append(el('li', difference.message)));
    differences.append(list);
    article.append(differences);
  }
  article.append(el('p', alternative ? 'ЧТО СОВПАДАЕТ' : 'ПОЧЕМУ ПОДХОДИТ', 'reason-heading'), el('p', card.explanation, 'explanation'));
  renderStyleMatches(article, card.style_matches);
  return article;
}

function render(data, day, fromBrief = false) {
  const section = el('section', undefined, 'result-group');
  section.append(el('h3', formatDate(day)), el('p', data.message, 'summary'));
  const exactCards = Array.isArray(data.cards) ? data.cards : [];
  const alternatives = !exactCards.length && Array.isArray(data.alternatives) ? data.alternatives : [];
  if (fromBrief && exactCards.length) section.append(el('h3', 'Подходящие профили'));
  const cards = el('div', undefined, 'cards');
  exactCards.forEach(card => cards.append(renderCard(card)));
  section.append(cards);
  if (alternatives.length) {
    const nearby = el('section', undefined, 'alternatives');
    nearby.append(el('h3', 'Ближайшие варианты — отличаются от запроса'), el('p', 'Проверьте отличия в каждой карточке. Эти варианты не выполняют все указанные требования.', 'alternative-note'));
    const options = el('div', undefined, 'cards');
    alternatives.forEach(card => options.append(renderCard(card, true)));
    nearby.append(options);
    section.append(nearby);
  }
  if (!exactCards.length && !alternatives.length) {
    const recovery = el('div', undefined, 'empty');
    recovery.append(el('p', data.recovery_message || 'Попробуйте другую дату, бюджет или условия подбора.'));
    for (const suggestion of (Array.isArray(data.suggestions) ? data.suggestions : [])) {
      const item = el('div', undefined, 'suggestion');
      const button = el('button', suggestion.label);
      button.type = 'button';
      button.disabled = busy;
      button.addEventListener('click', () => { if (busy) return; resetBrief(); fill(suggestion.request); compareMode(false); search(); });
      item.append(button, el('p', suggestion.message, 'hint'));
      recovery.append(item);
    }
    section.append(recovery);
  }
  if (data.quality && data.quality.message) section.append(el('p', data.quality.message));
  if (data.exclusion_counts) {
    const detail = el('details');
    detail.append(el('summary', 'Почему другие профили не вошли'));
    if (data.exclusion_counting) detail.append(el('p', data.exclusion_counting));
    const labels = {date_outside_calendar:'Нет календаря на эту дату', date_unknown:'Доступность неизвестна', date_busy:'Заняты', date_unavailable:'Нет свободной даты', over_budget:'Выше бюджета', format_mismatch:'Другой формат', language_mismatch:'Другой язык', duration_exceeded:'Недостаточно часов', preference_unconfirmed:'Пожелание не подтверждено описанием', no_requirements:'Условия поиска не указаны'};
    const list = el('ul');
    Object.entries(data.exclusion_counts).forEach(([key, count]) => list.append(el('li', `${labels[key] || key}: ${count}`)));
    detail.append(list);
    const counts = [];
    if (data.total != null) counts.push(`Всего в каталоге: ${data.total}.`);
    if (data.city_category_count != null) counts.push(`В выбранных городе и категории: ${data.city_category_count}.`);
    if (data.eligible_count != null) counts.push(`Подходят: ${data.eligible_count}.`);
    detail.append(el('p', counts.join(' ')));
    section.append(detail);
  }
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

async function searchBrief() {
  if (busy || !aiAvailable || !aiForm.reportValidity()) return;
  if (!aiBrief.value.trim()) {
    aiStatus.textContent = 'Сначала опишите ваше событие.';
    return;
  }
  const text = aiBrief.value.trim();
  setBusy(true);
  aiStatus.className = 'ai-status';
  aiStatus.textContent = 'Ищем по описанию и проверяем пожелания…';
  aiFeedback.replaceChildren();
  aiFeedback.hidden = true;
  aiSummary.replaceChildren();
  aiSummary.hidden = true;
  results.replaceChildren();
  results.className = '';
  statusNode.className = '';
  statusNode.textContent = 'AI подбирает профили только по требованиям в описании…';
  try {
    const data = await api('/api/ai/search', post({text}));
    const parsed = data.parsed;
    renderBriefSummary(parsed);
    const feedback = [...(parsed.questions || []), ...(parsed.warnings || [])];
    feedback.forEach(message => aiFeedback.append(el('li', message)));
    aiFeedback.hidden = feedback.length === 0;
    if (!parsed.ready || !data.result) {
      aiStatus.textContent = 'Нужно уточнить описание. Дополните текст выше и снова нажмите «Найти по описанию».';
      statusNode.textContent = 'Ждём уточнения неоднозначных условий. Поиск ещё не выполнен.';
      return;
    }
    results.append(render(data.result, data.result.request_date, true));
    aiStatus.textContent = 'Поиск завершён. Учтены только требования из описания; незаданные условия не ограничивают выбор.';
    statusNode.textContent = [data.result.ai && data.result.ai.message, data.result.ranking_rule].filter(Boolean).join(' ') || 'Подбор по описанию готов.';
  } catch (error) {
    aiStatus.textContent = `Не удалось выполнить поиск по описанию: ${error.message}. Условия можно заполнить вручную.`;
    aiStatus.className = 'ai-status error';
    statusNode.textContent = 'Подбор по описанию не выполнен. Повторите запрос или воспользуйтесь ручной формой.';
  } finally {
    setBusy(false);
  }
}
aiForm.addEventListener('submit', event => { event.preventDefault(); searchBrief(); });

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
  clearBriefFeedback();
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
