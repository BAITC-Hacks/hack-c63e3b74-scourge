const form = document.querySelector('#search-form');
const statusNode = document.querySelector('#status');
const results = document.querySelector('#results');
const submit = document.querySelector('#submit');
const toggle = document.querySelector('#compare-toggle');
const secondDate = document.querySelector('#compare-date');
const names = {dense:'Много вариантов', rare:'Редкая категория', no_matches:'Пустая выдача', category_absent:'Нет категории'};
let busy = false;
function el(tag, text, cls) {const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n;}
function compareMode(value){toggle.checked=value;document.querySelector('#compare-field').hidden=!value;secondDate.required=value;}
toggle.addEventListener('change',()=>compareMode(toggle.checked));
async function api(path, request){const response=await fetch(path,request);const data=await response.json();if(!response.ok)throw new Error(data.error || 'Ошибка сервиса');return data;}
function fill(request){for(const key of ['city','category','format','date','budget','language','duration_hours']){const input=form.elements.namedItem(key);input.value=request[key]===undefined?'':String(request[key]);if(input.tagName==='SELECT')input.value=String(request[key]||'').toLocaleLowerCase('ru');}}
function render(data, day){
  const section=el('section',undefined,'result-group');section.append(el('h3',new Date(day+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'})),el('p',data.message,'summary'));
  const cards=el('div',undefined,'cards');
  data.cards.forEach(card=>{const article=el('article',undefined,'card');const top=el('div',undefined,'card-top');const identity=el('div');identity.append(el('h4',card.name),el('div',`${card.category} · ${card.city} · ${card.id}`,'meta'));top.append(identity,el('div',`${card.price_kind==='starting'?'от ':''}${new Intl.NumberFormat('ru-RU').format(card.price)} ₸`,'price'));article.append(top);
    const badges=el('div',undefined,'badges');card.notices.forEach(notice=>badges.append(el('span',notice,notice==='Добавлен командой'?'badge team':'badge')));article.append(badges,el('p','ПОЧЕМУ ПОДХОДИТ','reason-heading'),el('p',card.explanation,'explanation'));cards.append(article);});
  section.append(cards);
  if(!data.cards.length)section.append(el('div','Попробуйте другую дату, увеличьте бюджет или измените условия.','empty'));
  if(data.quality.message)section.append(el('p',data.quality.message));
  const detail=el('details');detail.append(el('summary','Почему другие профили не вошли'));detail.append(el('p',data.exclusion_counting));
  const labels={date_outside_calendar:'Нет календаря на эту дату',date_busy:'Заняты',date_unavailable:'Нет свободной даты',over_budget:'Выше бюджета',format_mismatch:'Другой формат',language_mismatch:'Другой язык',duration_exceeded:'Недостаточно часов'};
  const list=el('ul');Object.entries(data.exclusion_counts).forEach(([key,count])=>list.append(el('li',`${labels[key]||key}: ${count}`)));detail.append(list,el('p',`Всего в каталоге: ${data.total}. В выбранных городе и категории: ${data.city_category_count}. Подходят: ${data.eligible_count}.`));section.append(detail);return section;
}
async function search(){
  if(busy || !form.reportValidity())return;
  busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);statusNode.className='';statusNode.textContent='Проверяем условия и календарь…';results.replaceChildren();
  const request=Object.fromEntries(new FormData(form));request.budget=Number(request.budget);request.duration_hours=request.duration_hours===''?null:Number(request.duration_hours);request.language=request.language||null;
  const dates=toggle.checked?[request.date,secondDate.value]:[request.date];results.className=dates.length>1?'compare-grid':'';
  try{const responses=await Promise.all(dates.map(day=>api('/api/recommend',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...request,date:day})})));responses.forEach((data,i)=>results.append(render(data,dates[i])));statusNode.textContent=dates.length>1?'Одинаковые условия, две даты. Сравните карточки и причины отсева.':'Подбор готов. Порядок: меньшая цена, затем id.';}
  catch(error){statusNode.textContent=error.message;statusNode.className='error';}
  finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}
}
form.addEventListener('submit',event=>{event.preventDefault();search();});
async function init(){try{const meta=await api('/api/meta');for(const [field,key] of Object.entries({city:'cities',category:'categories',format:'formats',language:'languages'})){const select=form.elements.namedItem(field);if(field==='language')select.append(new Option('Любой',''));meta[key].forEach(value=>select.append(new Option(value.charAt(0).toUpperCase()+value.slice(1),value)));}
  document.querySelector('#catalog').textContent=`${meta.total} профилей · добавлено командой: ${meta.team_count} · календарь осень–зима 2026`;
  const demos=document.querySelector('#demo-buttons');for(const demo of meta.demos){if(!names[demo.id])continue;const button=el('button',names[demo.id]);button.type='button';button.addEventListener('click',()=>{if(busy)return;fill(demo.request);compareMode(false);search();});demos.append(button);}
  const compare=el('button','Сравнить две даты');compare.type='button';compare.addEventListener('click',()=>{if(busy)return;fill(meta.demos.find(d=>d.id==='dense').request);compareMode(true);secondDate.value=meta.demos.find(d=>d.id==='other_date').request.date;search();});demos.append(compare);
  fill(meta.demos.find(d=>d.id==='dense').request);submit.disabled=false;
}catch(error){statusNode.textContent=`Не удалось загрузить каталог: ${error.message}. Обновите страницу.`;statusNode.className='error';}}
init();
