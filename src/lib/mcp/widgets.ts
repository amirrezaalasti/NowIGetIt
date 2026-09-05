import { MCP_APP_MIME, UI } from "./config";

const CSS = `
:root{color-scheme:dark;--bg:#0c1412;--ink:#e8f0ec;--muted:#9bb0a6;--accent:#3ecf8e;--hot:#f0c75e;--line:rgba(232,240,236,.12);--surface:rgba(255,255,255,.04);--danger:#fecaca}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
.wrap{padding:12px 14px 16px;display:flex;flex-direction:column;gap:10px;min-height:100%}
h1{font-size:16px;margin:0;font-weight:650}
.muted{color:var(--muted);font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:6px 12px;font-size:12px;cursor:pointer}
.chip:hover,.chip.on{border-color:var(--accent);color:var(--accent)}
.btn{border:0;background:var(--accent);color:#062016;border-radius:999px;padding:8px 14px;font-weight:650;cursor:pointer;font-size:13px}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
.btn:disabled{opacity:.5;cursor:wait}
.panel{border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:10px 12px}
ol{margin:0;padding:0;display:grid;grid-template-columns:1fr;gap:10px;list-style:none}
@media(min-width:540px){ol{grid-template-columns:1fr 1fr}}
li.card{border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:10px}
li.card.now{border-color:var(--accent)}
.bar{height:6px;background:var(--line);border-radius:99px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--accent);width:0}
video{width:100%;border-radius:12px;background:#000;max-height:360px}
img.frame{width:100%;border-radius:12px;background:#000;max-height:220px;object-fit:contain;margin:6px 0}
.ph{min-height:110px;border-radius:12px;background:#0003;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:12px;padding:12px;text-align:center;margin:6px 0}
.note{font-size:12px;color:var(--hot);margin:4px 0}
.ok{color:var(--accent)}
iframe.slide{width:100%;height:280px;border:1px solid var(--line);border-radius:12px;background:#fff}
.err{color:var(--danger);font-size:13px}
.reply{white-space:pre-wrap;font-size:13px}
input,textarea{width:100%;border:1px solid var(--line);background:#0003;color:var(--ink);border-radius:10px;padding:8px 10px;font:inherit}
.blocks{display:flex;flex-direction:column;gap:4px;max-height:140px;overflow:auto}
.block{text-align:left;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:6px 8px;font-size:12px;cursor:pointer}
.block.on{border-color:var(--accent)}
a{color:var(--accent)}
`;

const BRIDGE = `
function toolOutput(){
  try{ if(window.openai && window.openai.toolOutput) return window.openai.toolOutput; }catch(e){}
  return window.__nigi || {};
}
function onOutput(cb){
  cb(toolOutput()||{});
  window.addEventListener("message",function(ev){
    var d=ev.data; if(!d||typeof d!=="object") return;
    var p=d.params||{};
    var out=p.structuredContent||(p.result&&p.result.structuredContent)||p.toolOutput||(d.method==="ui/notifications/tool-result"?p:null);
    if(out&&typeof out==="object"&&!Array.isArray(out)) cb(out);
  });
  try{
    if(window.openai){
      var prev=window.openai.toolOutput;
      Object.defineProperty(window.openai,"toolOutput",{configurable:true,get:function(){return prev;},set:function(v){prev=v;cb(v||{});}});
    }
  }catch(e){}
}
var _rid=1;
function callTool(name,args){
  if(window.openai&&typeof window.openai.callTool==="function"){
    return window.openai.callTool(name,args);
  }
  return new Promise(function(resolve,reject){
    var id=_rid++;
    function onMsg(ev){
      var d=ev.data; if(!d||d.id!==id) return;
      window.removeEventListener("message",onMsg);
      if(d.error) reject(new Error(d.error.message||"Tool failed"));
      else resolve(d.result);
    }
    window.addEventListener("message",onMsg);
    window.parent.postMessage({jsonrpc:"2.0",id:id,method:"tools/call",params:{name:name,arguments:args}},"*");
    setTimeout(function(){ window.removeEventListener("message",onMsg); reject(new Error("Timed out")); },120000);
  });
}
function structured(result){
  if(!result) return {};
  if(result.structuredContent) return result.structuredContent;
  var c=result.content;
  if(Array.isArray(c)){
    for(var i=0;i<c.length;i++){
      if(c[i]&&c[i].type==="text"){
        try{ return JSON.parse(c[i].text); }catch(e){}
      }
    }
  }
  return result;
}
try{ window.parent.postMessage({jsonrpc:"2.0",method:"ui/initialize",params:{}},"*"); }catch(e){}
`;

function htmlDoc(title: string, body: string, script: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>${title}</title>
<style>${CSS}</style>
</head>
<body>
<div class="wrap" id="app"></div>
<script>
${BRIDGE}
${script}
</script>
</body>
</html>`;
}

export const JOB_PROGRESS_HTML = htmlDoc(
  "Now I Get It — job",
  "",
  `
var el=document.getElementById("app");
var state={};
var timer=null;
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
function followUp(text){
  try{
    var o=window.openai||{};
    if(typeof o.sendFollowUpMessage==="function") return o.sendFollowUpMessage({prompt:text});
    if(typeof o.sendFollowupMessage==="function") return o.sendFollowupMessage({prompt:text});
  }catch(e){}
}
function sceneStatus(sc){
  if(sc.clip_url) return "clip ready";
  if(sc.preview_url){
    if(sc.vlm && sc.vlm.approved===false) return "needs work";
    return "preview";
  }
  if(sc.has_code) return "code saved";
  return "planned";
}
function render(){
  var s=state||{};
  var status=s.status||"unknown";
  var list=s.scenes||[];
  var prog=s.codegen_progress||{};
  var saved=Number(prog.saved);
  if(!saved) saved=list.filter(function(x){return x.has_code||x.preview_url;}).length;
  var total=Number(prog.total)||list.length||1;
  var pct=Math.round(100*saved/Math.max(total,1));
  var writing=s.next_step==="write_next_scene";
  var confirmed=!!((s.options||{}).production_options_confirmed);
  var current=s.current_scene_id||"";
  var head="Video job";
  if(s.has_final_video||s.video_url) head="Video is ready";
  else if(status==="running"||s.running) head="Rendering clips…";
  else if(writing) head="Writing Manim · "+saved+" of "+total;
  else if(s.awaiting_render) head="Ready to render — confirm in chat";
  else if(s.awaiting_user||s.awaiting_plan||status==="awaiting_plan") head=confirmed?"Review this storyboard":"Pick audio, subtitles, and voice";
  else if(status==="error") head=s.error||"Render failed";
  var scenes=list.map(function(sc,i){
    var st=sceneStatus(sc);
    var now=sc.id&&sc.id===current?" now":"";
    var img=sc.preview_url?('<img class="frame" alt="'+esc(sc.title||"")+'" src="'+esc(sc.preview_url)+'"/>'):
      ('<div class="ph">'+esc(sc.visual_description||sc.narration||("Scene "+(i+1)+" — waiting for preview"))+'</div>');
    var clip=sc.clip_url?('<video controls playsinline src="'+esc(sc.clip_url)+'"></video>'):"";
    var vlm="";
    if(sc.vlm){
      var ok=sc.vlm.approved!==false;
      vlm='<div class="'+(ok?"ok":"note")+'">'+(ok?"Looks good":"Needs work");
      if(sc.vlm.issues&&sc.vlm.issues.length) vlm+=" — "+esc(sc.vlm.issues.join("; "));
      vlm+="</div>";
    }
    var ask=(sc.preview_url||sc.has_code)?
      ('<div class="row">'+
        '<button class="chip ask-fix" type="button">Fix this scene</button>'+
        '<button class="chip ask-ok" type="button">Looks good</button>'+
      '</div>'):"";
    return '<li class="card'+now+'" data-id="'+esc(sc.id||"")+'" data-title="'+esc(sc.title||"")+'">'+
      '<div class="muted">Scene '+(i+1)+' · '+esc(st)+'</div>'+
      img+
      '<label class="muted">Title</label>'+
      '<input class="scene-title" value="'+esc(sc.title||("Scene "+(i+1)))+'"/>'+
      (sc.duration_seconds?('<div class="muted">'+sc.duration_seconds+'s</div>'):'')+
      vlm+
      '<label class="muted">Narration</label>'+
      '<textarea class="scene-nar" rows="3">'+esc(sc.narration||"")+'</textarea>'+
      '<button class="chip save-scene" type="button">Save scene</button>'+
      ask+clip+
    '</li>';
  }).join("");
  var video=s.video_url?('<video controls playsinline src="'+esc(s.video_url)+'"></video>'):"";
  var opt=s.options||{};
  var options='<div class="panel"><div class="muted">'+(confirmed?"Voice, language, audio":"Choose these before we build — spoken audio, subtitles, and voice")+'</div>'+
    '<input id="voice" placeholder="Voice (Kore, alloy, …)" value="'+esc(opt.tts_voice||"")+'"/>'+
    '<input id="lang" placeholder="Language" value="'+esc(opt.language||"en")+'"/>'+
    '<label class="muted"><input type="checkbox" id="audio"'+(opt.include_audio===true?" checked":"")+'> Spoken audio</label>'+
    '<label class="muted"><input type="checkbox" id="subs"'+(opt.include_subtitles===true?" checked":"")+'> Subtitles</label>'+
    '<button class="chip" type="button" id="save-opts">'+(confirmed?"Update options":"Save audio & subtitles")+'</button></div>';
  var actions="";
  if(s.has_final_video||s.video_url){
    actions="";
  } else if(status==="running"||s.running){
    actions='<p class="muted">Rendering clips — previews appear here as each scene finishes.</p>';
  } else if(writing){
    actions='<p class="muted">Each scene still appears here as it is written. Tap Fix this scene if a frame looks wrong.</p>';
  } else if(status==="awaiting_render"||s.awaiting_render){
    actions='<p class="muted">Storyboard and Manim are ready. Confirm in chat to start the full render.</p>';
  } else if(status==="error"){
    actions='<p class="err">'+esc(s.error||s.message||"Render failed")+'</p>';
  } else if(status==="awaiting_plan"||s.awaiting_plan||s.awaiting_user){
    actions='<p class="muted">'+(confirmed?"Review this storyboard in chat. Say if you want changes before it renders.":"Review the storyboard, then choose spoken audio, subtitles, and voice before we write Manim.")+'</p>';
  }
  var open=s.library_url?('<a class="btn ghost" href="'+esc(s.library_url)+'" target="_blank" rel="noreferrer">Open in Now I Get It</a>'):"";
  var bar=(list.length && !s.has_final_video)?('<div class="bar" aria-hidden="true"><i style="width:'+pct+'%"></i></div><div class="muted">'+saved+' / '+total+' scenes</div>'):"";
  el.innerHTML='<h1>'+esc(s.title||"Video job")+'</h1>'+
    '<div class="muted">'+esc(head)+'</div>'+
    bar+
    video+
    (scenes?'<ol>'+scenes+'</ol>':'')+
    (s.job_id?options:"")+
    '<div class="row">'+actions+open+'</div>'+
    '<div class="err" id="err"></div>';
  el.querySelectorAll(".save-scene").forEach(function(btn){
    btn.onclick=function(){
      var li=btn.closest("li"); if(!li||!state.job_id) return;
      var err=document.getElementById("err"); if(err) err.textContent="";
      callTool("update_scene",{
        job_id:state.job_id,
        scene_id:li.getAttribute("data-id"),
        title:(li.querySelector(".scene-title")||{}).value,
        narration:(li.querySelector(".scene-nar")||{}).value
      }).then(function(r){ apply(structured(r)); }).catch(function(e){ if(err) err.textContent=e.message; });
    };
  });
  el.querySelectorAll(".ask-fix").forEach(function(btn){
    btn.onclick=function(){
      var li=btn.closest("li"); if(!li) return;
      var title=li.getAttribute("data-title")||"this scene";
      followUp("The preview for "+title+" ("+li.getAttribute("data-id")+") looks wrong. Fix the layout and resubmit that scene before continuing.");
    };
  });
  el.querySelectorAll(".ask-ok").forEach(function(btn){
    btn.onclick=function(){
      var li=btn.closest("li"); if(!li) return;
      followUp("The preview for "+(li.getAttribute("data-title")||"this scene")+" looks good. Continue.");
    };
  });
  var saveOpts=document.getElementById("save-opts");
  if(saveOpts){
    saveOpts.onclick=function(){
      var err=document.getElementById("err"); if(err) err.textContent="";
      var voice=(document.getElementById("voice")||{}).value;
      var args={
        job_id:state.job_id,
        language:(document.getElementById("lang")||{}).value,
        include_audio:!!(document.getElementById("audio")||{}).checked,
        include_subtitles:!!(document.getElementById("subs")||{}).checked
      };
      if(voice) args.tts_voice=voice;
      callTool("update_video_options",args).then(function(r){ apply(structured(r)); }).catch(function(e){ if(err) err.textContent=e.message; });
    };
  }
}
function apply(next){
  if(!next||typeof next!=="object") return;
  state=Object.assign({},state,next);
  render();
  var st=state.status||"";
  var running=st==="running"||state.running;
  var writing=state.next_step==="write_next_scene";
  if((running||writing) && state.job_id && !timer){
    timer=setInterval(function(){
      callTool("get_job",{job_id:state.job_id}).then(function(r){
        apply(structured(r));
        var n=state.status||"";
        if(n==="complete"||n==="awaiting_plan"||n==="error"||state.video_url){ clearInterval(timer); timer=null; }
        if(n==="awaiting_render" && state.awaiting_render){ clearInterval(timer); timer=null; }
      }).catch(function(){});
    },4000);
  }
}
onOutput(apply);
`,
);

export const VIDEO_PLAYER_HTML = htmlDoc(
  "Now I Get It — video",
  "",
  `
var el=document.getElementById("app");
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
onOutput(function(s){
  s=s||{};
  var open=s.library_url?('<a class="btn ghost" href="'+esc(s.library_url)+'" target="_blank" rel="noreferrer">Open in Library</a>'):"";
  el.innerHTML='<h1>'+esc(s.title||"Explanation")+'</h1>'+
    (s.video_url?('<video controls autoplay playsinline src="'+esc(s.video_url)+'"></video>'):'<p class="muted">Video is not ready yet. Ask to check the job.</p>')+
    ((s.scenes||[]).map(function(sc){
      return sc.preview_url?('<img class="frame" alt="'+esc(sc.title||"")+'" src="'+esc(sc.preview_url)+'"/>'):"";
    }).join(""))+
    '<div class="row">'+open+'</div>';
  try{ if(window.openai&&window.openai.requestDisplayMode) window.openai.requestDisplayMode({mode:"pip"}); }catch(e){}
});
`,
);

export const SLIDES_TUTOR_HTML = htmlDoc(
  "Now I Get It — slides",
  "",
  `
var el=document.getElementById("app");
var state={slide_index:0,block_id:null,reply:"",busy:false,conversation:[]};
var ACTIONS=[["explain","Explain"],["quiz","Quiz"],["simplify","Simplify"],["deepen","Deepen"],["key_takeaways","Takeaways"],["misconceptions","Misconceptions"],["summarize_slide","Summarize"],["turn_into_video_prompt","Video prompt"]];
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
function slides(){ return state.slides||[]; }
function current(){ return slides()[state.slide_index]||slides()[0]||null; }
function render(){
  var s=current();
  var idx=state.slide_index||0;
  var total=slides().length;
  var blocks=(s&&s.blocks||[]).map(function(b){
    var on=b.id===state.block_id?" on":"";
    return '<button class="block'+on+'" data-id="'+esc(b.id)+'">'+
      (b.image_url?('<img class="frame" alt="" src="'+esc(b.image_url)+'"/>'):"")+
      esc((b.type||"block")+" · "+(b.text||"").slice(0,140))+
    '</button>';
  }).join("");
  var chips=ACTIONS.map(function(a){
    return '<button class="chip" data-act="'+a[0]+'">'+a[1]+'</button>';
  }).join("");
  el.innerHTML='<h1>'+esc(state.title||"Document")+'</h1>'+
    '<div class="muted">Slide '+(idx+1)+' / '+total+(s&&s.title?(" · "+esc(s.title)):"")+'</div>'+
    (s&&s.html_url?('<iframe class="slide" src="'+esc(s.html_url)+'" title="slide"></iframe>'):'<p class="muted">No slide HTML yet.</p>')+
    '<div class="row"><button class="btn ghost" id="prev">Prev</button><button class="btn ghost" id="next">Next</button>'+
    (state.understand_url?('<a class="btn ghost" href="'+esc(state.understand_url)+'" target="_blank" rel="noreferrer">Open in Understand</a>'):"")+'</div>'+
    '<div class="blocks">'+blocks+'</div>'+
    '<div class="row">'+chips+'</div>'+
    '<textarea id="follow" rows="2" placeholder="Ask a follow-up…"></textarea>'+
    '<button class="btn" id="ask">Ask</button>'+
    (state.reply?'<div class="panel reply">'+esc(state.reply)+'</div>':'')+
    '<div class="err" id="err"></div>';
  document.getElementById("prev").onclick=function(){ if(idx>0){ state.slide_index=idx-1; state.block_id=null; render(); } };
  document.getElementById("next").onclick=function(){ if(idx<total-1){ state.slide_index=idx+1; state.block_id=null; render(); } };
  el.querySelectorAll(".block").forEach(function(btn){
    btn.onclick=function(){ state.block_id=btn.getAttribute("data-id"); render(); };
  });
  el.querySelectorAll(".chip").forEach(function(btn){
    btn.onclick=function(){ runAsk(btn.getAttribute("data-act"),""); };
  });
  document.getElementById("ask").onclick=function(){
    var msg=document.getElementById("follow").value||"";
    runAsk("freeform",msg);
  };
}
function runAsk(action,message){
  var s=current(); if(!s||!state.doc_id) return;
  var err=document.getElementById("err");
  if(err) err.textContent="";
  callTool("ask_document",{
    doc_id:state.doc_id,
    slide_id:s.id,
    block_id:state.block_id||undefined,
    action:action,
    message:message||"",
    conversation:state.conversation||[]
  }).then(function(r){
    var out=structured(r);
    state.reply=out.reply||out.video_prompt||"";
    if(message||state.reply){
      state.conversation=(state.conversation||[]).concat(
        message?[{role:"user",content:message}]:[],
        state.reply?[{role:"assistant",content:state.reply}]:[]
      ).slice(-12);
    }
    render();
  }).catch(function(e){
    var box=document.getElementById("err");
    if(box) box.textContent=e.message;
  });
}
onOutput(function(next){
  if(!next||typeof next!=="object") return;
  state=Object.assign(state,next);
  if(next.current_slide_id){
    var i=(state.slides||[]).findIndex(function(x){return x.id===next.current_slide_id;});
    if(i>=0) state.slide_index=i;
  }
  render();
});
`,
);

export const PODCAST_PLAYER_HTML = htmlDoc(
  "Now I Get It — podcast",
  "",
  `
var el=document.getElementById("app");
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
onOutput(function(s){
  s=s||{};
  var script=s.script||{};
  var chapters=script.chapters||[];
  var audio=s.audio_url?('<audio controls src="'+esc(s.audio_url)+'" style="width:100%"></audio>'):'<p class="muted">Transcript is ready'+(s.audio_skipped?" (no TTS on this server).":".")+'</p>';
  var ch=chapters.map(function(c){
    return '<li class="card"><strong>'+esc(c.title||c.id)+'</strong><div class="muted">'+(c.lines||[]).length+' lines</div></li>';
  }).join("");
  var take=(s.takeaways||[]).map(function(t){return '<li>'+esc(t)+'</li>';}).join("");
  el.innerHTML='<h1>'+esc(s.title||"Podcast")+'</h1>'+
    '<div class="muted">'+esc(script.tagline||"")+'</div>'+audio+
    (ch?'<ol>'+ch+'</ol>':'')+
    (take?'<div class="panel"><p class="muted">Takeaways</p><ul>'+take+'</ul></div>':'')+
    (s.learn_url?'<div class="row"><a class="btn ghost" href="'+esc(s.learn_url)+'" target="_blank" rel="noreferrer">Open in Learn</a></div>':'');
});
`,
);

export const QUIZ_RUNNER_HTML = htmlDoc(
  "Now I Get It — quiz",
  "",
  `
var el=document.getElementById("app");
var state={};
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
function render(){
  var s=state||{};
  var paper=s.paper||{};
  var qs=paper.questions||[];
  var grade=s.grade;
  var list=qs.map(function(q,i){
    var choices=(q.choices||[]).map(function(c){
      return '<label class="block"><input type="radio" name="'+esc(q.id)+'" value="'+esc(c.id)+'"/> '+esc(c.text)+'</label>';
    }).join("");
    if(q.type==="numeric"||q.type==="short_answer"){
      choices='<input data-qid="'+esc(q.id)+'" placeholder="Answer"/>';
    }
    var mark="";
    if(grade&&grade.questions){
      var g=grade.questions.find(function(x){return x.question_id===q.id;});
      if(g) mark='<div class="'+(g.correct?"ok":"err")+'">'+(g.correct?"Correct":"Not quite")+' — '+esc(g.explanation||"")+'</div>';
    }
    return '<li class="card"><div class="muted">Q'+(i+1)+'</div><p>'+esc(q.prompt)+'</p>'+choices+mark+'</li>';
  }).join("");
  var score=grade?('<div class="panel">Score '+grade.correct_count+' / '+grade.total+'</div>'):"";
  el.innerHTML='<h1>'+esc(s.title||paper.title||"Quiz")+'</h1>'+
    '<p class="muted">'+esc(paper.intro||"")+'</p>'+
    score+'<ol>'+list+'</ol>'+
    '<div class="row"><button class="btn" id="score">Score quiz</button>'+
    (s.learn_url?'<a class="btn ghost" href="'+esc(s.learn_url)+'" target="_blank" rel="noreferrer">Open in Learn</a>':'')+
    '</div><div class="err" id="err"></div>';
  var btn=document.getElementById("score");
  if(btn) btn.onclick=function(){
    var answers=[];
    qs.forEach(function(q){
      var val="";
      var radios=el.querySelectorAll('input[name="'+q.id+'"]');
      radios.forEach(function(r){ if(r.checked) val=r.value; });
      var inp=el.querySelector('input[data-qid="'+q.id+'"]');
      if(inp) val=inp.value;
      answers.push({question_id:q.id, answer:val});
    });
    callTool("grade_quiz",{id:s.id, answers:answers}).then(function(r){
      var next=structured(r);
      state=Object.assign({},state,next);
      render();
    }).catch(function(e){ var err=document.getElementById("err"); if(err) err.textContent=e.message; });
  };
}
onOutput(function(s){ state=Object.assign({},state,s||{}); render(); });
`,
);

export const INTERACTIVE_LAB_HTML = htmlDoc(
  "Now I Get It — lab",
  "",
  `
var el=document.getElementById("app");
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"})[c];}); }
onOutput(function(s){
  s=s||{};
  var lesson=s.lesson||{};
  var phases=lesson.phases||[];
  var params=lesson.parameters||[];
  var readouts=lesson.readouts||[];
  var phaseList=phases.map(function(p){
    return '<li class="card"><div class="muted">'+esc(p.kind)+'</div><strong>'+esc(p.title)+'</strong><p class="muted">'+esc(p.coach||"").slice(0,220)+'</p></li>';
  }).join("");
  var sliders=params.map(function(p){
    return '<div class="muted">'+esc(p.label)+' ('+esc(p.unit||"")+') · '+p.min+'–'+p.max+' default '+p.default+'</div>';
  }).join("");
  el.innerHTML='<h1>'+esc(s.title||lesson.title||"Lab")+'</h1>'+
    '<p class="muted">'+esc(lesson.core_question||lesson.tagline||"")+'</p>'+
    '<div class="panel">'+esc((lesson.visual&&lesson.visual.kind)||"visual")+' · '+params.length+' sliders · '+phases.length+' phases</div>'+
    sliders+
    (readouts.length?'<div class="muted">Live readouts: '+readouts.map(function(r){return r.label;}).join(", ")+'</div>':'')+
    '<ol>'+phaseList+'</ol>'+
    (s.learn_url?'<div class="row"><a class="btn" href="'+esc(s.learn_url)+'" target="_blank" rel="noreferrer">Open the lab</a></div>':'');
});
`,
);

export const WIDGETS: Record<string, { uri: string; name: string; title: string; html: string }> = {
  "job-progress": {
    uri: UI.jobProgress,
    name: "job-progress",
    title: "Job progress and storyboard",
    html: JOB_PROGRESS_HTML,
  },
  "video-player": {
    uri: UI.videoPlayer,
    name: "video-player",
    title: "Video player",
    html: VIDEO_PLAYER_HTML,
  },
  "slides-tutor": {
    uri: UI.slidesTutor,
    name: "slides-tutor",
    title: "Interactive slides tutor",
    html: SLIDES_TUTOR_HTML,
  },
  "podcast-player": {
    uri: UI.podcastPlayer,
    name: "podcast-player",
    title: "Podcast player",
    html: PODCAST_PLAYER_HTML,
  },
  "quiz-runner": {
    uri: UI.quizRunner,
    name: "quiz-runner",
    title: "Quiz",
    html: QUIZ_RUNNER_HTML,
  },
  "interactive-lab": {
    uri: UI.interactiveLab,
    name: "interactive-lab",
    title: "Interactive lab",
    html: INTERACTIVE_LAB_HTML,
  },
};

export function resourceResult(uri: string, html: string) {
  return {
    contents: [
      {
        uri,
        mimeType: MCP_APP_MIME,
        text: html,
      },
    ],
  };
}
