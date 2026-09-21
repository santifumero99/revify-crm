const API='/api';
let token=localStorage.getItem('revify_token')||'';
let currentUser=null;
let leads=[];
let nextCursor=null;
let currentLeadId=null;
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

function money(n){return new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR',maximumFractionDigits:2}).format(Number(n||0))}\nfunction dateTime(v){if(!v)return '—';return new Intl.DateTimeFormat('es-ES',{timeZone:'Europe/Madrid',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(v))}
function escapeHtml(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
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
  document.getElementById('leadList').innerHTML=leads.map(x=>`<button class="lead-row" onclick="openLead(${x.id})"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><span><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.business_type||'Sin categoría')}${x.business_subtype?` · ${escapeHtml(x.business_subtype)}`:''} · ${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</small><small>${x.status==='won'?'Venta cerrada':x.status==='lost'?'No terminó en venta':escapeHtml(x.next_action||'En curso')}</small><small class="record-time">Registrado: ${dateTime(x.created_at)}</small></span><span class="lead-right">${pill(x.status)}<em>Ver ficha ›</em></span></button>`).join('')||'<div style="color:#c3d2e8;font-size:9px;padding:14px;text-align:center">No hay resultados.</div>';
  const more=document.getElementById('loadMoreLeads');more.style.display=nextCursor?'block':'none';
}

async function openLead(id){
  try{
    const x=await api('/leads/'+id);currentLeadId=id;
    hideScreens();showAppNav();document.getElementById('screen-lead-detail').classList.add('active');setNav('leads');
    const editable=x.status!=='won';
    document.getElementById('leadDetail').innerHTML=`<div class="detail-card"><div class="detail-top"><span class="lead-avatar">${escapeHtml(x.name.charAt(0))}</span><div><h3>${escapeHtml(x.name)}</h3><p>${escapeHtml(x.address||'Sin dirección')}${x.postal_code?` · ${escapeHtml(x.postal_code)}`:''}</p>${pill(x.status)}</div></div><div class="detail-meta"><div><span>CATEGORÍA</span><b>${escapeHtml(x.business_type||'—')}</b></div><div><span>TIPO CONCRETO</span><b>${escapeHtml(x.business_subtype||'—')}</b></div><div><span>RESPONSABLE</span><b>${escapeHtml(x.owner_name||'—')}</b></div><div><span>TELÉFONO</span><b>${escapeHtml(x.phone||'—')}</b></div><div><span>CÓDIGO POSTAL</span><b>${escapeHtml(x.postal_code||'—')}</b></div><div><span>RESULTADO</span><b>${(statusMeta[x.status]||statusMeta.pending)[0]}</b></div><div><span>REGISTRADO</span><b>${dateTime(x.created_at)}</b></div></div><div class="detail-actions">${editable?`<button onclick="cycleStatus(${x.id},'${x.status}')">Actualizar estado</button><button onclick="registerActivity(${x.id})">Registrar visita</button>`:'<button onclick="showSales()">Ver venta</button>'}</div></div>`;
  }catch(err){toast(err.message)}
}

async function cycleStatus(id,current){
  const order=['pending','owner_absent','closed','follow_up','lost'];
  const pos=Math.max(0,order.indexOf(current));
  const next=order[(pos+1)%order.length];
  try{await api('/leads/'+id,{method:'PATCH',body:JSON.stringify({status:next})});await openLead(id);toast('Estado actualizado')}catch(err){toast(err.message)}
}
async function registerActivity(id){
  try{await api('/leads/'+id+'/activities',{method:'POST',body:JSON.stringify({activity_type:'visit',notes:''})});toast('Visita registrada');await loadDashboard()}catch(err){toast(err.message)}
}

function toggleCreateSaleFields(){
  const won=document.getElementById('newStatus')?.value==='won';
  const box=document.getElementById('createSaleFields');
  if(box) box.style.display=won?'block':'none';
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
    status
  };
  if(payload.postal_code.length!==5){toast('Código postal de 5 dígitos');return}
  if(status==='won'){
    payload.sale_quantity=Math.max(1,Number(document.getElementById('newSaleQuantity').value||1));
    payload.sale_unit_price=Math.max(.01,Number(document.getElementById('newSaleUnitPrice').value||25));
    payload.sale_payment_method=document.getElementById('newPaymentMethod').value;
    payload.sale_delivered=document.getElementById('newDelivered').value==='true';
  }
  try{
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