const API='/api';
let token=localStorage.getItem('revify_token')||'';
let currentUser=null;
let leads=[];
let nextCursor=null;
let currentLeadId=null;
let currentLead=null;
let priorityLead=null;
let searchTimer=null;
const PAGE_SIZE=50;

const statusMeta={
  pending:['Pendiente','pending'],
  owner_absent:['No está el dueño','owner'],
  closed:['Local cerrado','closed'],
  follow_up:['Seguimiento','follow'],
  won:['Vendido','won'],
  lost:['No vendido','lost']
};
const paymentMeta={cash:'Efectivo',card:'Tarjeta',bizum:'Bizum',transfer:'Transferencia',other:'Otro'};
const activityMeta={visit:'Visita',demo:'Demo',follow_up:'Seguimiento',owner_absent:'No estaba el dueño',closed:'Local cerrado',no_interest:'No vendido',note:'Nota'};

function money(n){return new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format(Number(n||0))}
function dateTime(v){if(!v)return '—';return new Intl.DateTimeFormat('es-ES',{timeZone:'Europe/Madrid',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}
function localInputValue(v){if(!v)return '';const d=new Date(v);const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`}
function followUpLabel(v){return v?`Seguimiento: ${dateTime(v)}`:'Seguimiento pendiente'}
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function norm(v){return String(v||'').trim().toLowerCase().replace(/\s+/g,' ')}
function normPhone(v){return String(v||'').replace(/\D/g,'')}
async function confirmPossibleDuplicate(payload){
  const data=await api('/leads?search='+encodeURIComponent(payload.name)+'&limit=20');
  const duplicate=(data.items||[]).find(x=>{
    const sameName=norm(x.name)===norm(payload.name);
    const samePhone=normPhone(payload.phone)&&normPhone(x.phone)===normPhone(payload.phone);
    const samePlace=payload.address&&norm(x.address)===norm(payload.address)&&x.postal_code===payload.postal_code;
    return samePhone||(sameName&&samePlace);
  });
  if(!duplicate)return true;
  return confirm(`Posible duplicado: ${duplicate.name} ya existe en el CRM.\n\n¿Quieres crear igualmente este deal?`);
}
function hideScreens(){document.querySelectorAll('.screen').forEach(x=>x.classList.remove('active'))}
function setNav(name){document.querySelectorAll('.navbtn').forEach(x=>x.classList.toggle('active',x.dataset.nav===name))}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');clearTimeout(window.__t);window.__t=setTimeout(()=>t.classList.remove('show'),1800)}
function showLogin(){hideScreens();document.getElementById('screen-login').classList.add('active');document.querySelector('.navbar').style.display='none'}
function showAppNav(){document.querySelector('.navbar').style.display='grid'}
function showHome(){hideScreens();showAppNav();document.getElementById('screen-home').classList.add('active');setNav('home');loadDashboard()}
function showLeads(){hideScreens();showAppNav();document.getElementById('screen-leads').classList.add('active');setNav('leads');loadLeads(true)}
function showCreate(){
  hideScreens();showAppNav();document.getElementById('screen-create').classList.add('active');setNav('create');
  document.getElementById('dealForm')?.reset();
  toggleCreateSaleFields();
  calcCreateSaleTotal();
  setTimeout(()=>document.getElementById('newName')?.focus(),80);
}
function showSales(){hideScreens();showAppNav();document.getElementById('screen-sale').classList.add('active');setNav('sale');loadSales()}
function showMore(){hideScreens();showAppNav();document.getElementById('screen-more').classList.add('active');setNav('more')}
function pill(status){const m=statusMeta[status]||statusMeta.pending;return `<span class="status-pill ${m[1]}">${m[0]}</span>`}

async function api(path,opts={}){
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  if(token) headers.Authorization='Bearer '+token;
  const res=await fetch(API+path,{...opts,headers});
  if(res.status===401){token='';localStorage.removeItem('revify_token');showLogin();throw new Error('Sesión caducada')}
  const data=await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.detail||'Error de servidor');
  return data;
}

async function login(e){
  e.preventDefault();
  document.getElementById('loginError').textContent='';
  try{
    const data=await api('/login',{method:'POST',body:JSON.stringify({
      email:document.getElementById('loginEmail').value.trim(),
      password:document.getElementById('loginPassword').value
    })});
    token=data.access_token;localStorage.setItem('revify_token',token);currentUser=data.user;showHome();
  }catch(err){document.getElementById('loginError').textContent=err.message}
}

async function boot(){
  document.querySelector('.navbar').style.display='none';
  if(!token){showLogin();return}
  try{currentUser=await api('/me');showHome()}catch{showLogin()}
}

async function loadDashboard(){
  try{
    const m=await api('/metrics');
    document.getElementById('dash-visits').textContent=m.visits;
    document.getElementById('dash-demos').textContent=m.demos;
    document.getElementById('dash-sales').textContent=m.sales;
    document.getElementById('dash-revenue').textContent=money(m.revenue);
    const pct=Math.min(100,Math.round((m.sales/10)*100));
    document.getElementById('ring').style.setProperty('--val',pct);
    document.getElementById('ring-pct').textContent=pct+'%';
    document.getElementById('progress-text').textContent=m.sales+' de 10 ventas';
    priorityLead=m.priority_lead||null;
    renderTodayFollowups(m.followups_today||[]);
    const name=document.getElementById('priority-name');
    const address=document.getElementById('priority-address');
    const status=document.getElementById('priority-status');
    const avatar=document.getElementById('priority-avatar');
    if(priorityLead){
      name.textContent=priorityLead.name;
      address.textContent=(priorityLead.address||'Sin dirección')+(priorityLead.postal_code?' · '+priorityLead.postal_code:'');
      const sm=statusMeta[priorityLead.status]||statusMeta.pending;status.textContent=sm[0];status.className='status-pill '+sm[1];
      avatar.textContent=priorityLead.name.charAt(0).toUpperCase();
    }else{
      name.textContent='Sin tareas pendientes';address.textContent='Da de alta tu primer negocio';status.textContent='Todo al día';status.className='status-pill pending';avatar.textContent='✓';
    }
  }catch(err){toast(err.message)}
}
function renderTodayFollowups(items){
  const count=document.getElementById('followupsCount');
  const box=document.getElementById('followupsToday');
  if(count)count.textContent=items.length;
  if(!box)return;
  box.innerHTML=items.length?items.map(x=>`<button class="followup-row" onclick="openLead(${x.id})"><span><b>${escapeHtml(x.name)}</b><small>${dateTime(x.follow_up_at)}</small></span><span>›</span></button>`).join(''):'<div class="followup-empty">No tienes seguimientos programados para hoy.</div>';
}
function mapPriorityLead(){
  if(!priorityLead?.address){toast('Este negocio no tiene dirección');return}
  const q=[priorityLead.address,priorityLead.postal_code].filter(Boolean).join(', ');
  window.open('https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(q),'_blank','noopener');
}

function handleLeadSearch(){clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadLeads(true),180)}
async function loadLeads(reset=false){
  if(reset){leads=[];nextCursor=null}
  const q=(document.getElementById('leadSearch')?.value||'').trim();
  const params=new URLSearchParams({limit:String(PAGE_SIZE)});
  if(q) params.set('search',q);
  if(!reset&&nextCursor) params.set('cursor',nextCursor);
  try{
    const data=await api('/leads?'+params.toString());
    if(reset) leads=data.items;else leads.push(...data.items);
    nextCursor=data.next_cursor||null;
    renderLeads(data.summary);
  }catch(err){toast(err.message)}
}
function loadMoreLeads(){if(nextCursor)loadLeads(false)}
function renderLeads(summary={}){
  document.getElementById('sumTotal').textContent=summary.total??leads.length;
  document.getElementById('sumActive').textContent=summary.active??0;
  document.getElementById('sumLost').textContent=summary.lost??0;
  document.getElementById('sumWon').textContent=summary.won??0;
  document.getElementById('leadList').innerHTML=leads.map(x=>`<button class="lead-row" onclick="openLead(${x.id})"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><span><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.business_type||'Sin categoría')}${x.business_subtype?` · ${escapeHtml(x.business_subtype)}`:''} · ${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</small><small>${x.status==='won'?'Venta cerrada':x.status==='lost'?'No terminó en venta':x.status==='follow_up'?escapeHtml(followUpLabel(x.follow_up_at)):escapeHtml(x.next_action||'En curso')}</small><small class="record-time">Registrado: ${dateTime(x.created_at)}</small></span><span class="lead-right">${pill(x.status)}<em>Ver ficha ›</em></span></button>`).join('')||'<div style="color:#c3d2e8;font-size:9px;padding:14px;text-align:center">No hay resultados.</div>';
  const more=document.getElementById('loadMoreLeads');more.style.display=nextCursor?'block':'none';
}

async function openLead(id){
  try{
    const [x,h]=await Promise.all([api('/leads/'+id),api('/leads/'+id+'/activities?limit=20')]);
    currentLeadId=id;currentLead=x;
    hideScreens();showAppNav();document.getElementById('screen-lead-detail').classList.add('active');setNav('leads');
    const editable=x.status!=='won';
    const quick=`${x.phone?`<button onclick="callCurrentLead()">Llamar</button>`:''}${x.address?`<button onclick="mapCurrentLead()">Maps</button>`:''}`;
    const history=(h.items||[]).map(a=>`<div class="activity-row"><div><b>${escapeHtml(activityMeta[a.activity_type]||a.activity_type)}</b><small>${dateTime(a.created_at)}</small></div><p>${escapeHtml(a.notes||'Sin nota')}</p></div>`).join('')||'<div class="activity-empty">Todavía no hay visitas registradas.</div>';
    document.getElementById('leadDetail').innerHTML=`<div class="detail-card"><div class="detail-top"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><div><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</p>${pill(x.status)}</div></div><div class="detail-meta"><div><span>CATEGORÍA</span><b>${escapeHtml(x.business_type||'—')}</b></div><div><span>TIPO CONCRETO</span><b>${escapeHtml(x.business_subtype||'—')}</b></div><div><span>RESPONSABLE</span><b>${escapeHtml(x.owner_name||'—')}</b></div><div><span>TELÉFONO</span><b>${escapeHtml(x.phone||'—')}</b></div><div><span>CÓDIGO POSTAL</span><b>${escapeHtml(x.postal_code||'—')}</b></div><div><span>RESULTADO</span><b>${(statusMeta[x.status]||statusMeta.pending)[0]}</b></div>${x.status==='follow_up'?`<div><span>PRÓXIMO SEGUIMIENTO</span><b>${dateTime(x.follow_up_at)}</b></div>`:''}<div><span>REGISTRADO</span><b>${dateTime(x.created_at)}</b></div><div><span>ÚLTIMA ACTUALIZACIÓN</span><b>${dateTime(x.updated_at)}</b></div></div><div class="detail-actions">${editable?`<button class="blue" onclick="editLead(${x.id})">Editar deal</button><button onclick="showVisitForm(${x.id})">Nueva visita</button>`:'<button onclick="editLead(${x.id})">Editar datos</button><button onclick="showSales()">Ver venta</button>'}${quick}</div><div id="visitPanel"></div></div><div class="history-card"><div class="history-head"><b>Historial de actividad</b><span>${(h.items||[]).length}</span></div>${history}</div>`;
  }catch(err){toast(err.message)}
}

function callCurrentLead(){
  if(!currentLead?.phone)return;
  window.location.href='tel:'+currentLead.phone.replace(/[^+0-9]/g,'');
}
function mapCurrentLead(){
  if(!currentLead?.address)return;
  const q=[currentLead.address,currentLead.postal_code].filter(Boolean).join(', ');
  window.open('https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(q),'_blank','noopener');
}
function showVisitForm(id){
  const box=document.getElementById('visitPanel');if(!box)return;
  box.innerHTML=`<form class="visit-form" onsubmit="saveVisit(event,${id})"><div class="visit-title">Registrar nueva visita</div><label>RESULTADO</label><select id="visitStatus" onchange="toggleVisitFollowUp()"><option value="pending">Pendiente / en curso</option><option value="owner_absent">No está el dueño</option><option value="closed">Local cerrado</option><option value="follow_up">Seguimiento</option><option value="lost">No vendido</option></select><div id="visitFollowUpFields" style="display:none"><label>FECHA Y HORA DEL SEGUIMIENTO *</label><input id="visitFollowUpAt" type="datetime-local"></div><label>NOTA DE LA VISITA</label><textarea id="visitNotes" rows="3" placeholder="Ej. Hablar con Marta el jueves; interesada en 2 unidades..."></textarea><div class="visit-actions"><button type="button" onclick="document.getElementById('visitPanel').innerHTML=''">Cancelar</button><button class="blue">Guardar visita</button></div><small>Si ha comprado, usa “Editar deal” → Vendido para registrar también la venta.</small></form>`;
}
function toggleVisitFollowUp(){
  const on=document.getElementById('visitStatus')?.value==='follow_up';
  const box=document.getElementById('visitFollowUpFields');
  if(box)box.style.display=on?'block':'none';
}
async function saveVisit(e,id){
  e.preventDefault();
  const status=document.getElementById('visitStatus').value;
  const notes=document.getElementById('visitNotes').value.trim();
  const type={pending:'visit',owner_absent:'owner_absent',closed:'closed',follow_up:'follow_up',lost:'no_interest'}[status]||'visit';
  const patch={status};
  if(status==='follow_up'){
    const v=document.getElementById('visitFollowUpAt')?.value;
    if(!v){toast('Indica fecha y hora de seguimiento');return}
    patch.follow_up_at=new Date(v).toISOString();
  }
  try{
    await api('/leads/'+id,{method:'PATCH',body:JSON.stringify(patch)});
    await api('/leads/'+id+'/activities',{method:'POST',body:JSON.stringify({activity_type:type,notes})});
    toast('Visita registrada');
    await openLead(id);
    loadDashboard();
  }catch(err){toast(err.message)}
}

function businessTypeOptions(selected){
  const opts=['Restauración / Hostelería','Comercio / Retail','Belleza / Estética','Salud / Bienestar','Hogar / Reformas','Automoción / Movilidad','Servicios profesionales','Educación / Formación','Ocio / Turismo / Alojamiento','Otros servicios'];
  return opts.map(v=>`<option ${v===selected?'selected':''}>${escapeHtml(v)}</option>`).join('');
}
function editStatusOptions(selected,locked=false){
  if(locked)return '<option value="won" selected>Vendido</option>';
  return [
    ['pending','Pendiente / en curso'],
    ['owner_absent','No está el dueño'],
    ['closed','Local cerrado'],
    ['follow_up','Seguimiento'],
    ['lost','No vendido'],
    ['won','Vendido — registrar venta']
  ].map(([v,l])=>`<option value="${v}" ${v===selected?'selected':''}>${l}</option>`).join('');
}
function toggleEditSaleFields(originalStatus){
  const status=document.getElementById('editStatus')?.value;
  const box=document.getElementById('editSaleFields');
  const follow=document.getElementById('editFollowUpFields');
  if(box)box.style.display=(status==='won'&&originalStatus!=='won')?'block':'none';
  if(follow)follow.style.display=status==='follow_up'?'block':'none';
  calcEditSaleTotal();
}
function calcEditSaleTotal(){
  const q=Math.max(1,Number(document.getElementById('editSaleQuantity')?.value||1));
  const p=Math.max(.01,Number(document.getElementById('editSaleUnitPrice')?.value||25));
  const out=document.getElementById('editSaleTotal');
  if(out)out.textContent=money(q*p);
}
async function editLead(id){
  try{
    const x=await api('/leads/'+id);
    const locked=x.status==='won';
    document.getElementById('leadDetail').innerHTML=`<form class="create-card" onsubmit="saveLeadEdit(event,${x.id},'${x.status}')"><div class="create-grid">
      <div class="create-field full"><label>NOMBRE DEL NEGOCIO *</label><input id="editName" required value="${escapeHtml(x.name)}"></div>
      <div class="create-field full"><label>DIRECCIÓN</label><input id="editAddress" value="${escapeHtml(x.address||'')}"></div>
      <div class="create-field"><label>CÓDIGO POSTAL *</label><input id="editPostalCode" required inputmode="numeric" pattern="[0-9]{5}" maxlength="5" value="${escapeHtml(x.postal_code||'')}"></div>
      <div class="create-field"><label>CATEGORÍA *</label><select id="editBusinessType" required>${businessTypeOptions(x.business_type)}</select></div>
      <div class="create-field"><label>TIPO CONCRETO</label><input id="editBusinessSubtype" value="${escapeHtml(x.business_subtype||'')}"></div>
      <div class="create-field"><label>CONTACTO / DUEÑO</label><input id="editOwner" value="${escapeHtml(x.owner_name||'')}"></div>
      <div class="create-field"><label>TELÉFONO</label><input id="editPhone" inputmode="tel" value="${escapeHtml(x.phone||'')}"></div>
      <div class="create-field full"><label>ESTADO ACTUAL *</label><select id="editStatus" ${locked?'disabled':''} onchange="toggleEditSaleFields('${x.status}')">${editStatusOptions(x.status,locked)}</select></div>
      <div class="create-field full" id="editFollowUpFields" style="display:none"><label>FECHA Y HORA DEL SEGUIMIENTO *</label><input id="editFollowUpAt" type="datetime-local" value="${localInputValue(x.follow_up_at)}"></div>
      <div class="create-field full" id="editSaleFields" style="display:none"><div style="border:1px solid #dfe7f1;border-radius:12px;padding:9px;background:#f8fbff"><div style="font-size:11px;font-weight:900;color:#17365f;margin-bottom:3px">VENTA</div><div style="font-size:9px;color:#64748b;margin-bottom:10px">Este mismo deal pasará a Vendido y la venta aparecerá en Ventas.</div><div class="create-grid">
        <div class="create-field"><label>UNIDADES NFC</label><input id="editSaleQuantity" type="number" min="1" max="1000" value="1" oninput="calcEditSaleTotal()"></div>
        <div class="create-field"><label>PRECIO UNITARIO (€)</label><input id="editSaleUnitPrice" type="number" min="0.01" step="0.01" value="25.00" oninput="calcEditSaleTotal()"></div>
        <div class="create-field"><label>COBRADO CON</label><select id="editPaymentMethod"><option value="card" selected>Tarjeta</option><option value="cash">Efectivo</option><option value="bizum">Bizum</option><option value="transfer">Transferencia</option><option value="other">Otro</option></select></div>
        <div class="create-field"><label>ENTREGA</label><select id="editDelivered"><option value="true">Entregado</option><option value="false">Pendiente de entregar</option></select></div>
        <div class="create-field full" style="margin-bottom:0"><label>TOTAL VENTA</label><div class="total-box" style="margin-top:0"><span>Importe registrado</span><b id="editSaleTotal">€25,00</b></div></div>
      </div></div></div>
    </div><div style="display:grid;grid-template-columns:1fr 1fr;gap:7px"><button type="button" class="ghostbtn" onclick="openLead(${x.id})">Cancelar</button><button class="save-lead">Guardar cambios</button></div></form>`;
    toggleEditSaleFields(x.status);
  }catch(err){toast(err.message)}
}
async function saveLeadEdit(e,id,originalStatus){
  e.preventDefault();
  const status=originalStatus==='won'?'won':document.getElementById('editStatus').value;
  const payload={
    name:document.getElementById('editName').value.trim(),
    address:document.getElementById('editAddress').value.trim(),
    postal_code:document.getElementById('editPostalCode').value.replace(/\D/g,'').slice(0,5),
    business_type:document.getElementById('editBusinessType').value,
    business_subtype:document.getElementById('editBusinessSubtype').value.trim(),
    owner_name:document.getElementById('editOwner').value.trim(),
    phone:document.getElementById('editPhone').value.trim(),
    status
  };
  if(payload.postal_code.length!==5){toast('Código postal de 5 dígitos');return}
  if(status==='follow_up'){
    const v=document.getElementById('editFollowUpAt')?.value;
    if(!v){toast('Indica fecha y hora de seguimiento');return}
    payload.follow_up_at=new Date(v).toISOString();
  }
  if(status==='won'&&originalStatus!=='won'){
    payload.sale_quantity=Math.max(1,Number(document.getElementById('editSaleQuantity').value||1));
    payload.sale_unit_price=Math.max(.01,Number(document.getElementById('editSaleUnitPrice').value||25));
    payload.sale_payment_method=document.getElementById('editPaymentMethod').value;
    payload.sale_delivered=document.getElementById('editDelivered').value==='true';
  }
  try{
    await api('/leads/'+id,{method:'PATCH',body:JSON.stringify(payload)});
    toast(status==='won'&&originalStatus!=='won'?'Deal actualizado y venta registrada':'Deal actualizado');
    await openLead(id);
    loadDashboard();
  }catch(err){toast(err.message)}
}

async function cycleStatus(id,current){
  const order=['pending','owner_absent','closed','follow_up','lost'];
  const pos=Math.max(0,order.indexOf(current));
  const next=order[(pos+1)%order.length];
  try{await api('/leads/'+id,{method:'PATCH',body:JSON.stringify({status:next})});await openLead(id);toast('Estado actualizado')}catch(err){toast(err.message)}
}


function toggleCreateSaleFields(){
  const status=document.getElementById('newStatus')?.value;
  const box=document.getElementById('createSaleFields');
  const follow=document.getElementById('createFollowUpFields');
  if(box) box.style.display=status==='won'?'block':'none';
  if(follow) follow.style.display=status==='follow_up'?'block':'none';
}
function calcCreateSaleTotal(){
  const q=Math.max(1,Number(document.getElementById('newSaleQuantity')?.value||1));
  const p=Math.max(.01,Number(document.getElementById('newSaleUnitPrice')?.value||25));
  const total=document.getElementById('newSaleTotal');
  if(total) total.textContent=money(q*p);
}
async function saveLead(e){
  e.preventDefault();
  const status=document.getElementById('newStatus').value;
  const payload={
    name:document.getElementById('newName').value.trim(),
    address:document.getElementById('newAddress').value.trim(),
    postal_code:document.getElementById('newPostalCode').value.replace(/\D/g,'').slice(0,5),
    business_type:document.getElementById('newBusinessType').value,
    business_subtype:document.getElementById('newBusinessSubtype').value.trim(),
    owner_name:document.getElementById('newOwner').value.trim(),
    phone:document.getElementById('newPhone').value.trim(),
    initial_notes:document.getElementById('newNotes').value.trim(),
    status
  };
  if(payload.postal_code.length!==5){toast('Código postal de 5 dígitos');return}
  if(status==='follow_up'){
    const v=document.getElementById('newFollowUpAt')?.value;
    if(!v){toast('Indica fecha y hora de seguimiento');return}
    payload.follow_up_at=new Date(v).toISOString();
  }
  if(status==='won'){
    payload.sale_quantity=Math.max(1,Number(document.getElementById('newSaleQuantity').value||1));
    payload.sale_unit_price=Math.max(.01,Number(document.getElementById('newSaleUnitPrice').value||25));
    payload.sale_payment_method=document.getElementById('newPaymentMethod').value;
    payload.sale_delivered=document.getElementById('newDelivered').value==='true';
  }
  try{
    const proceed=await confirmPossibleDuplicate(payload);
    if(!proceed){toast('Alta cancelada');return}
    await api('/leads',{method:'POST',body:JSON.stringify(payload)});
    e.target.reset();toggleCreateSaleFields();calcCreateSaleTotal();showLeads();
    toast(status==='won'?'Deal y venta registrados':'Deal registrado');
  }catch(err){toast(err.message)}
}

async function loadSales(){
  try{
    const data=await api('/sales?limit=250');
    const s=data.summary||{};
    document.getElementById('salesCount').textContent=s.sales||0;
    document.getElementById('salesUnits').textContent=s.units||0;
    document.getElementById('salesAvg').textContent=money(s.avg_ticket||0);
    document.getElementById('salesRevenue').textContent=money(s.revenue||0);
    document.getElementById('salesList').innerHTML=(data.items||[]).map(x=>`<div class="lead-row"><span class="lead-avatar">${escapeHtml((x.lead_name||'V').charAt(0))}</span><span><b>${escapeHtml(x.lead_name||'Venta')}</b><small>${x.quantity} ud. × ${money(x.unit_price)} · ${escapeHtml(paymentMeta[x.payment_method]||x.payment_method)}</small><small>${x.delivered?'Entregado':'Pendiente de entregar'} · Registrado: ${dateTime(x.created_at)}</small></span><span class="lead-right"><strong>${money(x.total)}</strong><button class="head-cta" style="margin-top:6px;padding:7px 10px" onclick="editSale(${x.id},${x.quantity},${Number(x.unit_price)},'${x.payment_method}',${x.delivered})">Editar</button></span></div>`).join('')||'<div style="color:#c3d2e8;font-size:9px;padding:18px;text-align:center">Todavía no hay ventas. Las ventas se registran únicamente desde Alta.</div>';
  }catch(err){toast(err.message)}
}

async function editSale(id,quantity,unitPrice,paymentMethod,delivered){
  const q=prompt('Unidades NFC',String(quantity));if(q===null)return;
  const p=prompt('Precio unitario (€)',String(unitPrice));if(p===null)return;
  const pay=prompt('Método de cobro: cash, card, bizum, transfer u other',paymentMethod);if(pay===null)return;
  const del=confirm('¿La venta está entregada?\nAceptar = Sí · Cancelar = No');
  const payload={quantity:Number(q),unit_price:Number(p),payment_method:pay.trim().toLowerCase(),delivered:del};
  if(!Number.isInteger(payload.quantity)||payload.quantity<1||!Number.isFinite(payload.unit_price)||payload.unit_price<=0){toast('Revisa unidades y precio');return}
  if(!Object.keys(paymentMeta).includes(payload.payment_method)){toast('Método de cobro no válido');return}
  try{await api('/sales/'+id,{method:'PATCH',body:JSON.stringify(payload)});toast('Venta corregida');loadSales();loadDashboard()}catch(err){toast(err.message)}
}

function sellPriorityLead(){showCreate()}
function confirmLogout(){if(confirm('¿Quieres cerrar sesión?')){token='';currentUser=null;localStorage.removeItem('revify_token');showLogin()}}

boot();