// UI contract checks without a browser or an external AI call.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.textContent = '';
    this._value = '';
    this.disabled = false;
    this.checked = false;
    this.hidden = false;
    this.listeners = {};
  }
  set value(value) {
    value = String(value);
    this._value = this.tagName === 'SELECT' && !this.children.some(option => option.value === value) ? '' : value;
  }
  get value() { return this._value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  reportValidity() { return this.valid !== false; }
  querySelectorAll(selector) { return descendants(this).filter(node => selector.split(',').map(s => s.trim().toUpperCase()).includes(node.tagName)); }
  set innerHTML(_) { throw new Error('Use textContent for untrusted content'); }
}
function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }
function allText(node) { return node.textContent + node.children.map(allText).join(' '); }
function option(value) { const node = new Element('option'); node.value = value; return node; }

const nodes = {};
for (const name of ['search-form', 'status', 'results', 'submit', 'compare-toggle', 'compare-date', 'compare-field', 'compare-note', 'ai-form', 'ai-brief', 'ai-parse', 'ai-status', 'ai-feedback', 'ai-summary', 'style-preferences', 'language-options']) nodes[`#${name}`] = new Element();
for (const id of ['#submit', '#ai-parse']) nodes[id].tagName = 'BUTTON';
for (const id of ['#ai-brief', '#style-preferences']) nodes[id].tagName = 'TEXTAREA';
for (const id of ['#compare-toggle', '#compare-date']) nodes[id].tagName = 'INPUT';
const fields = {};
for (const name of ['city', 'category', 'format', 'date', 'budget', 'duration_hours']) fields[name] = new Element(['city', 'category', 'format'].includes(name) ? 'select' : 'input');
fields.city.append(...['', 'алматы', 'астана'].map(option));
fields.category.append(...['', 'ведущий', 'отель'].map(option));
fields.format.append(...['', 'свадьба', 'день рождения'].map(option));
nodes['#search-form'].elements = {namedItem: name => fields[name]};
const languages = ['русский', 'казахский', 'английский'].map(value => {
  const node = new Element('input'); node.name = 'languages'; node.value = value; return node;
});
const context = vm.createContext({
  document: {
    querySelector: selector => nodes[selector],
    createElement: tag => new Element(tag),
    querySelectorAll: selector => selector === 'input[name="languages"]' ? languages : [...Object.values(nodes), ...Object.values(fields), ...languages].filter(node => ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(node.tagName)),
  },
  fetch: () => new Promise(() => {}),
  Date, Intl,
});
vm.runInContext(readFileSync(require('node:path').join(__dirname, '../web/app.js'), 'utf8'), context);
const baseResult = {cards:[], message:'Нет подходящих профилей', quality:{message:''}, exclusion_counts:{}, exclusion_counting:'', total:66, city_category_count:2, eligible_count:0};
const validRequest = {city:'Алматы', category:'Ведущий', format:'Свадьба', date:'2026-10-10', budget:800000, duration_hours:5, languages:['русский', 'казахский']};

async function run() {
  for (const suggestions of [undefined, null, {}, []]) {
    const result = context.render({...baseResult, suggestions}, '2026-09-24');
    assert.match(allText(result), /Нет подходящих профилей/);
    assert.match(allText(result), /Попробуйте другую дату/);
    assert.doesNotMatch(allText(result), /Invalid Date/);
  }
  const recovery = context.render({...baseResult, suggestions:[{label:'Другой бюджет', message:'Найден вариант', request:{}}], recovery_message:'Доступны изменения'}, '2026-09-24');
  assert.match(allText(recovery), /Другой бюджет/);
  assert.match(allText(recovery), /Доступны изменения/);

  const styleCard = {...baseResult, cards:[{name:'Имя', category:'Ведущий', city:'Алматы', id:'1', price:500000, price_kind:'starting', notices:[], explanation:'Факты', style_matches:[
    {preference:'Камерность', status:'supported', quote:'<img src=x onerror=alert(1)> Камерные свадьбы'},
    {preference:'Без конкурсов', status:'unknown', quote:'Это не подтверждено'},
  ]}]};
  const rendered = context.render(styleCard, '2026-10-10');
  assert.match(allText(rendered), /есть подтверждение в описании/);
  assert.match(allText(rendered), /<img src=x onerror=alert\(1\)>/);
  assert.match(allText(rendered), /Без конкурсов — нужно уточнить/);
  assert.doesNotMatch(allText(rendered), /Это не подтверждено/);
  assert.equal(descendants(rendered).some(node => node.tagName === 'IMG'), false);

  const partialResult = {cards:[], alternatives:[], message:'Пока нет вариантов', request_date:null};
  const withoutDate = context.render(partialResult, null, true);
  assert.match(allText(withoutDate), /Без ограничения даты/);
  assert.doesNotMatch(allText(withoutDate), /Invalid Date|undefined/);
  const nearbyCard = {...styleCard.cards[0], proposed_date:'2026-10-11', differences:[
    {field:'date', requested:'2026-10-10', actual:'2026-10-11', message:'На 10 октября занят. Свободен 11 октября.'},
    {field:'preferences', requested:'Без конкурсов', actual:null, message:'«Без конкурсов» — нужно уточнить.'},
  ]};
  const alternativeResult = {...partialResult, alternatives:[nearbyCard], message:'Точных совпадений нет. Вот близкий вариант.'};
  const nearby = context.render(alternativeResult, null, true);
  assert.match(allText(nearby), /Ближайшие варианты — отличаются от запроса/);
  assert.match(allText(nearby), /Предлагаемая дата: 11 октября 2026/);
  assert.match(allText(nearby), /На 10 октября занят/);
  assert.match(allText(nearby), /«Без конкурсов» — нужно уточнить/);
  assert.doesNotMatch(allText(nearby), /ПОЧЕМУ ПОДХОДИТ|Попробуйте другую дату/);
  assert.equal(descendants(nearby).some(node => node.className === 'card alternative-card'), true);

  context.fill(validRequest);
  let request = JSON.parse(JSON.stringify(context.requestPayload()));
  assert.deepEqual(request.languages, ['русский', 'казахский']);
  assert.equal(request.budget, 800000);
  context.fill({city:'Астана', language:'русский'});
  assert.equal(fields.city.value, 'астана');
  assert.equal(fields.category.value, '');
  assert.equal(fields.date.value, '');
  assert.equal(fields.budget.value, '');
  assert.deepEqual(languages.map(node => node.checked), [true, false, false]);

  vm.runInContext('aiAvailable = true', context);
  const calls = [];
  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => ({parsed:{request:{city:'Алматы'}, preferences:['Камерная атмосфера'], questions:['Какой день подразумевается под «скоро»?'], warnings:['Уточните неоднозначную дату'], ready:false}, result:null})};
  };
  nodes['#ai-brief'].value = 'Хочу камерную свадьбу в Алматы скоро';
  nodes['#compare-toggle'].checked = true;
  nodes['#style-preferences'].value = 'Предыдущее пожелание из ручной формы';
  context.fill(validRequest);
  nodes['#search-form'].valid = false;
  await context.searchBrief();
  assert.equal(calls.length, 1, 'One request must parse and search independently of manual form validation');
  assert.equal(calls[0].path, '/api/ai/search');
  assert.deepEqual(calls[0].request, {text:'Хочу камерную свадьбу в Алматы скоро'});
  assert.equal(fields.budget.value, '800000', 'Text search must not overwrite manual form values');
  assert.equal(fields.date.value, '2026-10-10');
  assert.equal(nodes['#compare-toggle'].checked, true);
  assert.equal(nodes['#style-preferences'].value, 'Предыдущее пожелание из ручной формы');
  assert.match(allText(nodes['#ai-feedback']), /Какой день/);
  assert.match(allText(nodes['#ai-feedback']), /неоднозначную дату/);
  assert.match(allText(nodes['#ai-summary']), /Учтено из описания/);
  assert.match(allText(nodes['#ai-summary']), /Бюджет не ограничен/);
  assert.equal(nodes['#results'].children.length, 0, 'Ambiguous requests must not display fabricated results');
  assert.match(nodes['#ai-status'].textContent, /Дополните текст выше/);
  assert.equal(nodes['#ai-parse'].disabled, false);

  const exactCard = {...styleCard.cards[0], style_matches:[]};
  const exactResult = {cards:[exactCard], alternatives:[], message:'Найден подходящий профиль', request_date:null, ai:{message:'Пожелания проверены'}, ranking_rule:'По совпадениям, затем цене и id.'};
  const searchResponse = {parsed:{request:{category:'Ведущий'}, preferences:[], questions:[], warnings:[], ready:true}, result:exactResult};
  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => searchResponse};
  };
  nodes['#ai-brief'].value = '  Нужен ведущий  ';
  fields.budget.value = '1';
  fields.date.value = '2030-01-01';
  let before = calls.length;
  await context.searchBrief();
  assert.equal(calls.length, before + 1, 'Text search must not require a second recommendation request');
  assert.deepEqual(calls.at(-1), {path:'/api/ai/search', request:{text:'Нужен ведущий'}});
  assert.match(allText(nodes['#results']), /Найден подходящий профиль/);
  assert.match(allText(nodes['#results']), /Имя/);
  assert.match(allText(nodes['#results']), /Без ограничения даты/);
  assert.match(allText(nodes['#ai-summary']), /Дата не указана/);
  assert.doesNotMatch(allText(nodes['#ai-summary']), /2030|800000|Предыдущее пожелание/);
  assert.match(nodes['#status'].textContent, /По совпадениям/);
  assert.equal(nodes['#ai-feedback'].hidden, true, 'Old clarification questions must clear');

  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => ({...searchResponse, result:alternativeResult})};
  };
  await context.searchBrief();
  assert.match(allText(nodes['#results']), /Ближайшие варианты/);
  assert.match(allText(nodes['#results']), /Предлагаемая дата/);
  assert.doesNotMatch(allText(nodes['#results']), /Найден подходящий профиль/);

  nodes['#compare-toggle'].listeners.change();
  assert.equal(nodes['#results'].children.length, 0, 'Switching manual comparison mode must clear text-search results');
  assert.equal(nodes['#ai-summary'].hidden, true);
  assert.equal(nodes['#ai-feedback'].hidden, true);

  let finishSearch;
  context.fetch = (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return new Promise(resolve => { finishSearch = () => resolve({ok:true, json:async () => searchResponse}); });
  };
  before = calls.length;
  const pendingSearch = context.searchBrief();
  await context.searchBrief();
  await context.search();
  assert.equal(calls.length, before + 1, 'Double submit and simultaneous manual search must not duplicate paid calls');
  assert.equal(nodes['#ai-parse'].disabled, true);
  finishSearch();
  await pendingSearch;
  assert.equal(nodes['#ai-parse'].disabled, false);
  assert.equal(nodes['#ai-brief'].listeners.input, undefined, 'Typing must not trigger paid calls');
  assert.equal(nodes['#ai-brief'].listeners.change, undefined);

  nodes['#search-form'].valid = true;
  context.fill(validRequest);
  context.compareMode(false);
  nodes['#style-preferences'].value = 'Камерная атмосфера';
  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => ({...baseResult, ai:{applied:false, message:'AI недоступен, применён обычный подбор.'}, ranking_rule:'По цене, затем id.'})};
  };
  await context.search();
  assert.equal(calls.at(-1).path, '/api/ai/recommend');
  assert.deepEqual(calls.at(-1).request.languages, ['русский', 'казахский']);
  assert.deepEqual(calls.at(-1).request.preferences, ['Камерная атмосфера']);
  assert.match(nodes['#status'].textContent, /AI недоступен/);
  assert.match(nodes['#status'].textContent, /По цене/);
  assert.equal(fields.city.disabled, false);
  assert.equal(nodes['#ai-summary'].hidden, true, 'Manual search must remove the previous AI summary');

  context.compareMode(true);
  nodes['#compare-date'].value = '2026-10-11';
  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => ({message:'Сравнение', changes:[], results:[baseResult, baseResult]})};
  };
  await context.search();
  assert.equal(calls.at(-1).path, '/api/compare');
  assert.equal(calls.at(-1).request.compare_date, '2026-10-11');
  assert.equal('preferences' in calls.at(-1).request, false);
  assert.match(nodes['#status'].textContent, /Пожелания к атмосфере не учитывались/);
  assert.equal(nodes['#compare-note'].hidden, false);

  context.compareMode(false);
  vm.runInContext('aiAvailable = false', context);
  nodes['#ai-parse'].disabled = true;
  context.fetch = async (path, config) => {
    calls.push({path, request:JSON.parse(config.body)});
    return {ok:true, json:async () => baseResult};
  };
  await context.search();
  assert.equal(calls.at(-1).path, '/api/recommend');
  assert.match(nodes['#status'].textContent, /пожелания к атмосфере не учитывались/);
  assert.equal(nodes['#ai-parse'].disabled, true, 'Unconfigured AI button must stay disabled after manual search');
  before = calls.length;
  await context.searchBrief();
  assert.equal(calls.length, before);

  nodes['#style-preferences'].value = 'a\nb\nc\nd\ne\nf';
  await context.search();
  assert.equal(calls.length, before);
  assert.match(nodes['#status'].textContent, /не больше 5/);

  vm.runInContext('aiAvailable = true', context);
  context.fetch = async () => ({ok:false, json:async () => ({error:'Сервис недоступен'})});
  await context.searchBrief();
  assert.equal(fields.budget.value, '800000', 'Failed AI parsing must preserve manual input');
  assert.match(nodes['#ai-status'].textContent, /Условия можно заполнить вручную/);
  assert.equal(nodes['#results'].children.length, 0, 'Failed AI search must not leave previous manual results visible');
  assert.equal(nodes['#ai-summary'].hidden, true);
  nodes['#ai-brief'].value = '   ';
  before = calls.length;
  await context.searchBrief();
  assert.equal(calls.length, before);
  assert.match(nodes['#ai-status'].textContent, /Сначала опишите/);
  context.resetBrief();
  assert.equal(nodes['#style-preferences'].value, '');
  assert.equal(nodes['#ai-brief'].value, '');
  assert.equal(nodes['#ai-feedback'].hidden, true);
  assert.equal(nodes['#ai-summary'].hidden, true);
  console.log('UI regression and AI integration checks passed');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
