const API='/api';
let token=localStorage.getItem('revify_token')||'';
let reps=[];
let adminLeadCursor=null;
let adminLeadTimer=null;

function money(n){return new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR'}).format(Number(n||0))}
function esc(v){return String(v==null?'':v).replace(/[&<>'"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]})}
function statusLabel(s){return ({pending:'Pendiente',owner_absent:'No está el dueño',closed:'Local cerrado',follow_up:'Seguimiento',won:'Vendido',lost:'No interesado'})[s]||s}

async function req(path,opts){
  opts=opts||{};
  const headers=Object.assign({'Content-Type':'application/json'},opts.headers||{});
  if(token) headers.Authorization='Bearer '+token;
  const r=await fetch(API+path,Object.assign({},opts,{headers:headers}));
  const data=await r.json().catch(function(){return {}});
  if(r.status===401){localStorage.removeItem('revify_token');token='';showLogin();throw new Error(data.detail||'Sesión no válida')}
  if(!r.ok) throw new Error(data.detail||'Error de servidor');
  return data;
}

function showLogin(){
  document.getElementById('loginView').classList.remove('hidden');
  document.getElementById('adminView').classList.add('hidden');
}
function showAdmin(){
  document.getElementById('loginView').classList.add('hidden');
  document.getElementById('adminView').classList.remove('hidden');
}
function adminLogout(){localStorage.removeItem('revify_token');token='';showLogin()}

async function adminLogin(e){
  e.preventDefault();
  const err=document.getElementById('loginError');err.textContent='';
  try{
    const login=await fetch(API+'/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      email:document.getElementById('adminEmail').value.trim(),
      password:document.getElementById('adminPassword').value
    })});
    const data=await login.json().catch(function(){return {}});
    if(!login.ok) throw new Error(data.detail||'Email o contraseña incorrectos');
    token=data.access_token;localStorage.setItem('revify_token',token);
    const me=await req('/admin/me');
    document.getElementById('adminIdentity').textContent=me.email;
    showAdmin();await loadEverything();
  }catch(ex){err.textContent=ex.message;localStorage.removeItem('revify_token');token=''}
}

async function boot(){
  if(!token){showLogin();return}
  try{
    const me=await req('/admin/me');
    document.getElementById('adminIdentity').textContent=me.email;
    showAdmin();await loadEverything();
  }catch(ex){showLogin()}
}

function showTab(name){
  document.querySelectorAll('.tab').forEach(function(x){x.classList.add('hidden')});
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.nav').forEach(function(x){x.classList.toggle('active',x.dataset.tab===name)});
  const titles={dashboard:['Dashboard','Visión global de Revify'],team:['Comerciales','Gestiona quién puede acceder al CRM'],leads:['Negocios','Toda la cartera creada por el equipo'],security:['Seguridad','Tu acceso de administrador']};
  document.getElementById('pageTitle').textContent=titles[name][0];
  document.getElementById('pageSubtitle').textContent=titles[name][1];
  if(name==='leads') loadAdminLeads(true);
}

async function loadEverything(){await Promise.all([loadSummary(),loadReps()]);renderRepFilters();await loadAdminLeads(true)}

async function loadSummary(){
  const s=await req('/admin/summary');
  document.getElementById('kLeads').textContent=s.leads;
  document.getElementById('kLeads2').textContent=s.leads;
  document.getElementById('kSalesToday').textContent=s.sales_today;
  document.getElementById('kSalesToday2').textContent=s.sales_today;
  document.getElementById('kRevenueToday').textContent=money(s.revenue_today);
  document.getElementById('kRevenueToday2').textContent=money(s.revenue_today);
  document.getElementById('kConversion').textContent=s.conversion_pct+'%';
  document.getElementById('kUsers').textContent=s.active_users;
  document.getElementById('kVisits').textContent=s.visits_today;
  document.getElementById('kDemos').textContent=s.demos_today;
  document.getElementById('kSalesTotal').textContent=s.sales_total;
  document.getElementById('kRevenueTotal').textContent=money(s.revenue_total);
  document.getElementById('kWon').textContent=s.won_leads;
  renderBars('postalList',s.postal_codes.map(function(x){return [x.postal_code,x.leads]}));
  renderBars('categoryList',s.categories.map(function(x){return [x.category,x.leads]}));
}
function renderBars(id,rows){
  const max=Math.max.apply(null,[1].concat(rows.map(function(r){return r[1]})));
  document.getElementById(id).innerHTML=rows.length?rows.map(function(r){
    return '<div class="bar-row"><span title="'+esc(r[0])+'">'+esc(r[0])+'</span><div class="bar"><i style="width:'+Math.max(5,r[1]/max*100)+'%"></i></div><b>'+r[1]+'</b></div>';
  }).join(''):'<p style="font-size:10px;color:#8794a7">Aún no hay datos.</p>';
}

async function loadReps(){
  const data=await req('/admin/reps');reps=data.items;
  document.getElementById('repPerformance').innerHTML=reps.map(function(r){
    return '<tr><td><b>'+esc(r.email)+'</b></td><td>'+r.leads+'</td><td>'+r.visits+'</td><td>'+r.sales+'</td><td>'+r.conversion_pct+'%</td><td><b>'+money(r.revenue)+'</b></td></tr>';
  }).join('');
  document.getElementById('teamTable').innerHTML=reps.map(function(r){
    let buttons='';
    if(r.role!=='admin'){
      buttons='<button data-email="'+esc(r.email)+'" onclick="resetRepPassword('+r.id+',this.dataset.email)">Contraseña</button><button class="'+(r.is_active?'danger':'')+'" onclick="toggleRep('+r.id+','+(!r.is_active)+')">'+(r.is_active?'Pausar':'Activar')+'</button>';
    }
    return '<tr><td><b>'+esc(r.email)+'</b></td><td>'+esc(r.role)+'</td><td><span class="status '+(r.is_active?'on':'off')+'">'+(r.is_active?'Activo':'Pausado')+'</span></td><td>'+r.leads+'</td><td>'+r.sales+'</td><td>'+money(r.revenue)+'</td><td><div class="actions">'+buttons+'</div></td></tr>';
  }).join('');
}
function renderRepFilters(){
  const sel=document.getElementById('fRep');const current=sel.value;
  sel.innerHTML='<option value="">Todos los comerciales</option>'+reps.map(function(r){return '<option value="'+r.id+'">'+esc(r.email)+'</option>'}).join('');
  sel.value=current;
}

function debouncedAdminLeads(){clearTimeout(adminLeadTimer);adminLeadTimer=setTimeout(function(){loadAdminLeads(true)},180)}
async function loadAdminLeads(reset){
  if(reset) adminLeadCursor=null;
  const p=new URLSearchParams({limit:'50'});
  const search=document.getElementById('fSearch').value.trim();
  const postal=document.getElementById('fPostal').value.trim();
  const rep=document.getElementById('fRep').value;
  const status=document.getElementById('fStatus').value;
  const cat=document.getElementById('fCategory').value;
  if(search)p.set('search',search);if(postal)p.set('postal_code',postal);if(rep)p.set('assigned_user_id',rep);if(status)p.set('status',status);if(cat)p.set('business_type',cat);if(!reset&&adminLeadCursor)p.set('cursor',adminLeadCursor);
  const data=await req('/admin/leads?'+p.toString());adminLeadCursor=data.next_cursor||null;
  const html=data.items.map(function(x){
    return '<div class="lead-card"><div><h3>'+esc(x.name)+'</h3><p>'+esc(x.address||'Sin dirección')+' · '+esc(x.postal_code)+'</p></div><div class="meta">'+esc(x.business_type)+(x.business_subtype?' · '+esc(x.business_subtype):'')+'</div><div class="rep">'+esc(x.rep_email||'Sin asignar')+'</div><div><span class="badge">'+statusLabel(x.status)+'</span></div></div>';
  }).join('');
  const list=document.getElementById('adminLeadList');
  if(reset) list.innerHTML=html||'<p style="font-size:10px;color:#8794a7">No hay negocios con estos filtros.</p>';else list.insertAdjacentHTML('beforeend',html);
  document.getElementById('adminLoadMore').classList.toggle('hidden',!adminLeadCursor);
}

function openCreateCommercial(){
  document.getElementById('commercialModal').classList.remove('hidden');
  document.getElementById('createCommercialMsg').textContent='';
  document.getElementById('commercialEmail').value='';
  generateCommercialPassword();setTimeout(function(){document.getElementById('commercialEmail').focus()},50);
}
function closeCreateCommercial(){document.getElementById('commercialModal').classList.add('hidden')}
function generateCommercialPassword(){
  const chars='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$%';
  const arr=new Uint32Array(18);crypto.getRandomValues(arr);
  document.getElementById('commercialPassword').value=Array.from(arr,function(x){return chars[x%chars.length]}).join('');
}
async function createCommercial(e){
  e.preventDefault();
  const email=document.getElementById('commercialEmail').value.trim();
  const password=document.getElementById('commercialPassword').value;
  const msg=document.getElementById('createCommercialMsg');msg.textContent='';
  try{
    await req('/admin/users',{method:'POST',body:JSON.stringify({email:email,temporary_password:password})});
    closeCreateCommercial();
    const box=document.getElementById('credentialBox');
    box.innerHTML='<b>Acceso creado correctamente</b>Comparte estas credenciales con el comercial por el canal que prefieras.<code>Email: '+esc(email)+'<br>Contraseña temporal: '+esc(password)+'<br>CRM: https://revify-web-production.up.railway.app</code>';
    box.classList.remove('hidden');showTab('team');await loadReps();renderRepFilters();await loadSummary();
  }catch(ex){msg.textContent=ex.message}
}
async function toggleRep(id,isActive){
  try{await req('/admin/users/'+id+'/active',{method:'PATCH',body:JSON.stringify({is_active:isActive})});await loadReps();await loadSummary()}catch(ex){alert(ex.message)}
}
async function resetRepPassword(id,email){
  const p=prompt('Nueva contraseña temporal para '+email+' (mínimo 10 caracteres):');
  if(!p)return;if(p.length<10){alert('Debe tener al menos 10 caracteres.');return}
  try{
    await req('/admin/users/'+id+'/reset-password',{method:'POST',body:JSON.stringify({new_password:p})});
    const box=document.getElementById('credentialBox');
    box.innerHTML='<b>Contraseña restablecida</b><code>Email: '+esc(email)+'<br>Nueva contraseña temporal: '+esc(p)+'</code>';box.classList.remove('hidden');
  }catch(ex){alert(ex.message)}
}
async function changeMyPassword(e){
  e.preventDefault();
  const current=document.getElementById('currentPass').value;
  const next=document.getElementById('newPass').value;
  const next2=document.getElementById('newPass2').value;
  const msg=document.getElementById('passwordMsg');
  if(next!==next2){msg.textContent='Las contraseñas nuevas no coinciden.';return}
  try{
    await req('/account/password',{method:'POST',body:JSON.stringify({current_password:current,new_password:next})});
    msg.style.color='#0b7d51';msg.textContent='Contraseña cambiada correctamente.';e.target.reset();
  }catch(ex){msg.style.color='#d64555';msg.textContent=ex.message}
}
boot();