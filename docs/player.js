const DATA_URL="./data/status.json";
const GATEWAY="https://live-source-gateway.onrender.com";
let channels=[];let hls=null;let currentId="";
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,s=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[s]));
function resolutionTier(s){const w=Number(s?.width)||0,h=Number(s?.height)||0;if((w>=1920&&h>=1080)||s?.["1080p"]===true)return 4;if(w>=1280&&h>=720)return 3;if(h>=480)return 2;return 0}
function fmtTime(v){try{return new Date(v).toLocaleString("zh-CN",{hour12:false})}catch{return v||"—"}}
function groups(){const s=$("group"),cur=s.value;const gs=[...new Set(channels.map(x=>x.group||"其他").filter(Boolean))].sort((a,b)=>a.localeCompare(b,"zh-CN"));s.innerHTML='<option value="">全部分组</option>'+gs.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join("");if(gs.includes(cur))s.value=cur}
function render(){
  const q=$("search").value.trim().toLowerCase(),g=$("group").value;
  const list=channels.filter(c=>
    (!q||(String(c.name||"")+" "+String(c.id||"")).toLowerCase().includes(q))&&
    (!g||(c.group||"其他")===g)
  );
  $("channelCount").textContent=list.length+" 个频道";
  $("channelHint").textContent=q
    ? "找到 "+list.length+" 个匹配频道，点击任意频道即可播放。"
    : "点击频道卡片即可播放，也可以搜索频道。";

  const box=$("channels");
  box.innerHTML=list.map(c=>{
    const sources=Array.isArray(c.sources)?c.sources:[];
    const hd=sources.filter(s=>resolutionTier(s)>=4).length;
    const active=String(c.id)===String(currentId);
    return '<article class="channel-card player-channel '+(active?'channel-selected':'')+'" data-id="'+esc(c.id)+'">'+
      '<div class="channel-head">'+
        '<div class="channel-main">'+
          '<div class="channel-name">'+esc(c.name||c.id)+'</div>'+
          '<div class="channel-id">'+esc(c.id||"")+'</div>'+
        '</div>'+
        '<span class="pill count">'+sources.length+' 条 · '+hd+' 条1080P</span>'+
      '</div>'+
      '<div class="channel-foot">'+
        '<span class="meta-line">'+(active?'正在播放 · ':'点击播放 · ')+'数据更新 '+esc(fmtTime(c.updated_at||""))+'</span>'+
        '<button class="play-channel" type="button">'+(active?'播放中':'播放')+'</button>'+
      '</div>'+
    '</article>';
  }).join("")||'<div class="empty">没有匹配的频道</div>';

  box.querySelectorAll(".player-channel").forEach(el=>{
    el.addEventListener("click",()=>play(channels.find(c=>String(c.id)===String(el.dataset.id))));
  });
}
function stop(){
  if(hls){try{hls.destroy()}catch(e){}hls=null}
  const v=$("player");
  v.pause();
  v.removeAttribute("src");
  v.load();
  currentId="";
  $("playerTitle").textContent="选择频道";
  $("playerStatus").textContent="请选择下方频道开始播放。";
  render();
}
function play(c){
  if(!c?.id)return;
  currentId=String(c.id);
  render();
  const v=$("player");const url=GATEWAY+"/hls/"+encodeURIComponent(c.id)+"/index.m3u8";if(hls){try{hls.destroy()}catch(e){}hls=null}v.pause();v.removeAttribute("src");v.load();$("playerTitle").textContent="正在播放："+(c.name||c.id);$("playerStatus").textContent="正在连接线路网关…";if(v.canPlayType("application/vnd.apple.mpegurl")){v.src=url;v.play().then(()=>$("playerStatus").textContent="播放中 · 网关自动调度线路").catch(()=>$("playerStatus").textContent="线路已加载，请点击播放器播放按钮。");return}if(window.Hls&&Hls.isSupported()){hls=new Hls({enableWorker:true,lowLatencyMode:true,maxBufferLength:12});hls.on(Hls.Events.MANIFEST_PARSED,()=>v.play().catch(()=>{}));hls.on(Hls.Events.ERROR,(e,d)=>{console.warn("HLS",d);if(d?.fatal)$("playerStatus").textContent="播放失败："+(d.details||"网关或上游线路异常")});hls.attachMedia(v);hls.loadSource(url);return}$("playerStatus").textContent="当前浏览器不支持 HLS。"}
async function load(){try{const r=await fetch(DATA_URL,{cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);const d=await r.json();channels=Array.isArray(d.channels)?d.channels:[];groups();render();const id=new URLSearchParams(location.search).get("id");if(id)play(channels.find(c=>String(c.id)===String(id)))}catch(e){$("playerStatus").textContent="频道列表读取失败："+e.message}}
$("search").addEventListener("input",render);
$("group").addEventListener("change",render);
$("search").addEventListener("keydown",e=>{
  if(e.key!=="Enter")return;
  const q=$("search").value.trim().toLowerCase();
  if(!q)return;
  const match=channels.find(c=>
    (String(c.name||"")+" "+String(c.id||"")).toLowerCase().includes(q)
  );
  if(match)play(match);
});
$("stopBtn").addEventListener("click",stop);
load();