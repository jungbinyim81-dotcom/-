
// ---- 잠금: 서버에는 암호문만 있다. 비번으로 그 자리에서 푼다 ----
const BOX=JSON.parse(document.getElementById('D').textContent);
const KEY='gagyebu-pw';
let D=null,MS,DAT,GO;
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));

async function unlock(pw){
  const enc=new TextEncoder();
  const base=await crypto.subtle.importKey('raw',enc.encode(pw),'PBKDF2',
    false,['deriveKey']);
  const key=await crypto.subtle.deriveKey(
    {name:'PBKDF2',salt:b64(BOX.salt),iterations:BOX.iter,hash:'SHA-256'},
    base,{name:'AES-GCM',length:256},false,['decrypt']);
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:b64(BOX.iv)},
    key,b64(BOX.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}

async function tryOpen(pw,remember){
  const msg=document.getElementById('msg'), go=document.getElementById('go');
  msg.textContent=''; go.disabled=true; go.textContent='여는 중...';
  try{
    D=await unlock(pw);
    if(remember)localStorage.setItem(KEY,pw);
    MS=D.months;DAT=D.data;GO=D.grade_of;
    cur=MS.filter(m=>DAT[m]['완전']).pop()||MS[MS.length-1];
    document.getElementById('lock').classList.add('hide');
    document.getElementById('app').classList.add('on');
    render();
    return true;
  }catch(e){
    localStorage.removeItem(KEY);
    msg.textContent='비밀번호가 맞지 않습니다';
    document.getElementById('pw').value='';
    return false;
  }finally{ go.disabled=false; go.textContent='열기'; }
}

function openPlain(){
  D=BOX.plain;MS=D.months;DAT=D.data;GO=D.grade_of;
  cur=MS.filter(m=>DAT[m]['완전']).pop()||MS[MS.length-1];
  document.getElementById('lock').classList.add('hide');
  document.getElementById('app').classList.add('on');
  render();
}

window.addEventListener('DOMContentLoaded',()=>{
  if(BOX.plain){openPlain();return;}
  const pw=document.getElementById('pw'), go=document.getElementById('go');
  go.onclick=()=>tryOpen(pw.value,document.getElementById('rem').checked);
  pw.addEventListener('keydown',e=>{if(e.key==='Enter')go.click();});
  document.getElementById('lockout').onclick=e=>{
    e.preventDefault();localStorage.removeItem(KEY);location.reload();};
  const saved=localStorage.getItem(KEY);
  if(saved)tryOpen(saved,true).then(ok=>{if(!ok)pw.focus();});
  else pw.focus();
});

let cur=null;
const won=n=>Math.round(n).toLocaleString('ko-KR');
const man=n=>{const a=Math.abs(n);
 if(a>=100000000)return (n/100000000).toFixed(1)+'억';
 if(a>=10000)return Math.round(n/10000).toLocaleString('ko-KR')+'만';
 return won(n);};
let cur=MS.filter(m=>DAT[m]['완전']).pop()||MS[MS.length-1];
const prevOf=m=>{const i=MS.indexOf(m);return i>0?MS[i-1]:null;};
function delta(n,b){if(b===null||b===undefined)return['','z'];
 const d=n-b;if(Math.abs(d)<1)return['0','z'];
 return[(d>0?'+':'')+man(d),d>0?'u':'d0'];}

function tabs(){document.getElementById('tabs').innerHTML=MS.map(m=>{
 const d=DAT[m];return `<button class="tab${m===cur?' on':''}" data-m="${m}">
 ${+m.slice(5)}월<i>${d['완전']?d['일수']+'일':d['기간']+' *'}</i></button>`;}).join('');
 document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{cur=b.dataset.m;
  render();window.scrollTo({top:0,behavior:'smooth'});});}

function rows(obj,det,prev,color){
 const ks=Object.keys(obj).filter(k=>Math.abs(obj[k])>0.5).sort((a,b)=>obj[b]-obj[a]);
 if(!ks.length)return '<div class="list"><div class="tx" style="padding-left:13px">'+
  '<span></span><span class="n0">내역 없음</span><span></span></div></div>';
 const mx=Math.max(...ks.map(k=>obj[k]));
 return '<div class="list">'+ks.map(k=>{
  const v=obj[k],tx=det[k]||[],[dt,dc]=delta(v,prev?(prev[k]||0):null);
  return `<div class="it"><div class="ih">
   <span class="ar">&#9654;</span>
   <span class="nm">${k}<em>${tx.length}</em></span>
   <span class="rt"><span class="amt">${won(v)}</span>
    <span class="dl ${dc}">${dt}</span></span>
   <span class="bar"><i style="width:${(100*v/mx).toFixed(1)}%;
    background:var(--${color})"></i></span></div>
   <div class="det">${tx.map(t=>`<div class="tx"><span class="dt">${t[0]}</span>
    <span class="n0">${t[1]}</span><span class="a0">${won(t[2])}</span></div>`).join('')}
   </div></div>`;}).join('')+'</div>';}

function render(){
 const d=DAT[cur],p=prevOf(cur),pd=p?DAT[p]:null;
 document.getElementById('sub').textContent=cur+' · '+d['기간']+
  (d['완전']?'':' · 부분월');
 tabs();
 const[i1,c1]=delta(d['수입합'],pd?pd['수입합']:null);
 const[s1,c2]=delta(d['소비합'],pd?pd['소비합']:null);
 const[b1,c3]=delta(d['수지'],pd?pd['수지']:null);
 const rate=d['소비율'],over=rate>100;
 let h=`<div class="head"><div class="big">
  <div><div class="l">수입</div><div class="v">${man(d['수입합'])}</div>
   <div class="d ${c1==='u'?'d0':'u'}">${i1}</div></div>
  <div><div class="l">소비</div><div class="v">${man(d['소비합'])}</div>
   <div class="d ${c2}">${s1}</div></div>
  <div><div class="l">수지</div>
   <div class="v" style="color:var(--${d['수지']<0?'up':'down'})">${man(d['수지'])}</div>
   <div class="d ${c3==='u'?'d0':'u'}">${b1}</div></div></div>
  <div class="rate"><div class="rl"><span>수입 대비 소비</span>
   <b style="color:var(--${over?'up':'down'})">${rate.toFixed(0)}%</b></div>
  <div class="track"><div class="fill" style="width:${Math.min(rate/150*100,100)}%;
   background:var(--${over?'up':'down'})"></div><div class="mark"></div></div>
  <div class="rl" style="margin-top:5px"><span style="font-size:10px">선이 100%</span>
   <span style="font-size:10px">${pd?'전월 '+pd['소비율'].toFixed(0)+'%':''}</span></div>`;
 if(pd&&d['완전']&&pd['완전']){
  const di=d['수입합']-pd['수입합'];
  const df=(d['등급']['내가 정하는 돈']||0)-(pd['등급']['내가 정하는 돈']||0);
  if(di>0&&df>0)h+=`<div class="warn">수입이 ${man(di)} 늘었는데
   <b>내가 정하는 돈도 ${man(df)} 늘었다.</b></div>`;
  else if(df<0)h+=`<div class="warn">내가 정하는 돈이
   <b>${man(-df)} 줄었다.</b></div>`;}
 h+='</div>';
 const mx=Math.max(...MS.map(m=>DAT[m]['소비합']));
 h+='<div class="mini">'+MS.map(m=>`<div class="${m===cur?'on':''}"
  style="height:${Math.max(100*DAT[m]['소비합']/mx,4)}%"><span>${+m.slice(5)}</span>
  </div>`).join('')+'</div>';
 h+=`<h2><span>수입</span><b>${won(d['수입합'])}</b></h2>`;
 h+=rows(d['수입'],d['수입내역'],pd?pd['수입']:null,'bar3');
 const byG={};Object.keys(d['소비']).forEach(k=>{
  const g=GO[k]||'내가 정하는 돈';(byG[g]=byG[g]||{})[k]=d['소비'][k];});
 h+=`<h2><span>소비</span><b>${won(d['소비합'])}</b></h2>`;
 const col={'내가 정하는 돈':'bar','줄이기 어려운 돈':'bar2','못 줄이는 돈':'bar3'};
 D.grades.forEach(g=>{if(!byG[g])return;
  const t=Object.values(byG[g]).reduce((a,b)=>a+b,0);
  const pt=pd?Object.keys(pd['소비']).filter(k=>(GO[k]||'')===g)
   .reduce((a,k)=>a+pd['소비'][k],0):null;
  const[dt,dc]=delta(t,pt);
  h+=`<div class="grp"><span>${g}</span><span><b>${won(t)}</b>
   <span class="dl ${dc}" style="display:inline;margin-left:7px">${dt}</span></span></div>`;
  const pg={};if(pd)Object.keys(pd['소비']).forEach(k=>{
   if((GO[k]||'')===g)pg[k]=pd['소비'][k];});
  h+=rows(byG[g],d['소비내역'],pd?pg:null,col[g]||'bar');});
 if(byG['소비 아님(자산)']){
  const t=Object.values(byG['소비 아님(자산)']).reduce((a,b)=>a+b,0);
  h+=`<div class="grp"><span>자산으로 남는 돈</span><span><b>${won(t)}</b></span></div>`;
  h+=rows(byG['소비 아님(자산)'],d['소비내역'],null,'bar3');}
 document.getElementById('view').innerHTML=h;
 document.querySelectorAll('.ih').forEach(el=>el.onclick=()=>
  el.parentElement.classList.toggle('open'));}
if('serviceWorker' in navigator)window.addEventListener('load',()=>
 navigator.serviceWorker.register('sw.js').catch(()=>{}));
