"""렌더된 동작 표본을 로컬 HTML 검토 페이지로 묶는다."""
import argparse
import json
from pathlib import Path


def build(index_path, output):
    from PIL import Image
    output = Path(output)
    index = json.loads(Path(index_path).read_text(encoding='utf-8'))
    clips = index['clips']
    atlas = output / 'atlas'
    atlas.mkdir(exist_ok=True)
    for clip in clips:
        count = len(clip['frames'])
        for view in ['oblique', 'side']:
            paths = [output / 'frames' / clip['name'] / f'{view}_{i:03}.png' for i in range(count)]
            with Image.open(paths[0]) as first:
                size = first.width
            sheet = Image.new('RGB', (size*6, size*((count+5)//6)), '#11151c')
            for i, path in enumerate(paths):
                with Image.open(path) as frame:
                    sheet.paste(frame.convert('RGB'), ((i%6)*size, (i//6)*size))
            sheet.save(atlas / f'{clip["name"]}_{view}.webp', quality=85)
        clip['size'] = size
        clip['count'] = count
    detail = '<details><summary>손 · 하박 확대 검토 — 네 방향</summary>'
    for name,label in [('sword_idle','검 대기'),('down','내려베기'),('thrust','찌르기'),('gun_aim','총 양손 조준')]:
        detail += f'<h3>{label}</h3><div class="views">'
        for view,view_label in [('front','정면'),('side','측면'),('reverse','반대 사선'),('palm','손바닥 쪽')]:
            path=f'hand_review/fixed_{name}_{view}.png'
            detail += f'<figure><a href="{path}" target="_blank"><img src="{path}" style="width:100%" alt="{label} {view_label}"></a><figcaption>{view_label} · 클릭하여 원본 확대</figcaption></figure>'
        detail += '</div>'
    detail += '</details>'
    html = TEMPLATE.replace('__DATA__', json.dumps(clips, ensure_ascii=False).replace('</', '<\\/')).replace('__DETAIL__',detail)
    (output / 'preview.html').write_text(html, encoding='utf-8')
    return {'clips':len(clips), 'html':str(output/'preview.html')}


TEMPLATE = r'''<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>메카 동작 검토</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#10141b;color:#e1e9f2;font:15px system-ui,sans-serif}header{padding:22px 28px;border-bottom:1px solid #334052}h1{font-size:23px;margin:0 0 8px}p{color:#a5b4c6;margin:6px 0;line-height:1.6}main{display:grid;grid-template-columns:270px 1fr;max-width:1500px;margin:auto}nav{padding:18px;border-right:1px solid #334052;max-height:88vh;overflow:auto}button,select,input{font:inherit}button,select{background:#202b3a;border:1px solid #3b4d63;color:#e1e9f2;border-radius:7px;padding:9px 13px;cursor:pointer}button:hover,button.active{background:#244760;border-color:#52b9e8}nav button{width:100%;text-align:left;margin:3px 0;font-size:13px}nav h3{font-size:12px;color:#80c8ec;margin:20px 0 7px}section{padding:22px;min-width:0}.views{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0;background:#080c11;border:1px solid #334052;border-radius:10px;overflow:hidden}canvas{display:block;width:100%;aspect-ratio:1;object-fit:contain}figcaption{padding:9px 13px;color:#9cacc0;font-size:12px}.bar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:15px 0}input[type=range]{width:100%;accent-color:#5bc8ef}.tag{background:#253347;color:#9fd7f4;border-radius:5px;padding:5px 9px;font-size:12px}.events{min-height:25px;color:#ffcc75}#strip{display:flex;overflow:auto;gap:5px;padding:12px 0}#strip button{min-width:46px;padding:9px 5px}#strip .hit{border-bottom:3px solid #ffaa55}h2{font-size:20px}.note{border-left:3px solid #dcad66;background:#272319;padding:12px;margin-top:15px;color:#e0c99f;font-size:13px}@media(max-width:800px){main{grid-template-columns:1fr}nav{max-height:210px;border-bottom:1px solid #334052}.views{grid-template-columns:1fr 1fr}section{padding:12px}}
</style>
<header><h1>기본 무기 · 애니메이션 초안</h1><p>중립 모델 기반 / 12fps / 동작 폭·스텝·체중 이동 검토</p></header>
<main><nav id="list"></nav><section><div class="bar"><span class="tag" id="count"></span><span class="tag">외관 검토용 초안</span></div><h2 id="title"></h2><div class="views"><figure><canvas id="a" width="640" height="640"></canvas><figcaption>사선 · 전체 실루엣</figcaption></figure><figure><canvas id="b" width="640" height="640"></canvas><figcaption>측면 · 보폭과 체중 이동</figcaption></figure></div>
<div class="bar"><button id="play">일시정지</button><button id="prev">◀ 한 프레임</button><button id="next">한 프레임 ▶</button><button id="combo">4타 연속 재생</button><label>속도 <select id="speed"><option value="0.5">0.5배</option><option value="1" selected>1배 · 12fps</option><option value="1.5">1.5배</option></select></label><label><input id="repeat" type="checkbox" checked>반복</label><label><input id="ghost" type="checkbox">이전 포즈 겹치기</label></div>
<input id="seek" type="range" min="0" value="0"><div class="bar"><span id="frame"></span><span id="event" class="events"></span></div><div id="strip"></div><div class="note" id="note"></div><p>스페이스: 재생/정지 · ←/→: 프레임 이동. 타격·발사 표시는 초안 이벤트이며 게임 판정 확정값이 아니야.</p>__DETAIL__</section></main>
<script>
const clips=__DATA__;
const $=id=>document.getElementById(id);let selected=0,frame=0,playing=true,combo=false,last=0,acc=0,images={};
const groups={'대기':c=>c.name.endsWith('idle')||c.name==='gun_aim','무기·자세 전환':c=>c.name.includes('_to_'),'발사':c=>c.name.endsWith('_fire'),'검 콤보':c=>c.name.startsWith('combo_'),'걷기·달리기':c=>c.name.includes('_walk_')||c.name.includes('_run_'),'이동 전환':c=>/accelerate|decelerate|dash/.test(c.name)};
for(const [label,test]of Object.entries(groups)){const h=document.createElement('h3');h.textContent=label;$('list').append(h);clips.forEach((c,i)=>{if(test(c)){const b=document.createElement('button');b.textContent=c.label;b.dataset.index=i;b.onclick=()=>{combo=false;select(i)};$('list').append(b)}})}
function select(i){selected=i;frame=0;acc=0;const c=clips[i];$('title').textContent=c.label;$('count').textContent=`${clips.length}개 동작 · ${c.count}프레임 · ${(c.count/12).toFixed(2)}초`;$('seek').max=c.count-1;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',Number(b.dataset.index)===i));images={};for(const view of ['oblique','side']){const im=new Image();im.onload=draw;im.src=`atlas/${c.name}_${view}.webp`;images[view]=im}$('strip').replaceChildren();for(let n=0;n<c.count;n++){const b=document.createElement('button');b.textContent=n+1;b.className=c.events.some(e=>e.clip_frame===n)?'hit':'';b.onclick=()=>{playing=false;frame=n;draw()};$('strip').append(b)}$('note').textContent=c.name.includes('_to_')?'전환 초안: 수납 접촉·발도 궤적과 손의 연속성은 특히 확인이 필요해.':c.name==='gun_aim'||c.name==='aim_fire'?'양손 조준: 보조손의 접촉과 팔꿈치 방향을 측면에서도 확인해줘.':'과장된 준비·동작·회복을 보는 초안이야. 관절·장갑 간섭과 발 접지는 최종 승인 전 검토 대상이야.';draw()}
function paint(canvas,im){const ctx=canvas.getContext('2d'),c=clips[selected],s=c.size;ctx.clearRect(0,0,640,640);if(!im?.complete||!im.naturalWidth)return;const render=(f,alpha)=>{ctx.globalAlpha=alpha;ctx.drawImage(im,(f%6)*s,Math.floor(f/6)*s,s,s,0,0,640,640)};render(frame,1);if($('ghost').checked&&frame>0)render(frame-1,.22);ctx.globalAlpha=1}
function draw(){paint($('a'),images.oblique);paint($('b'),images.side);$('seek').value=frame;$('frame').textContent=`${frame+1} / ${clips[selected].count} · ${(frame/12).toFixed(2)}초`;$('play').textContent=playing?'일시정지':'재생';$('event').textContent=clips[selected].events.filter(e=>e.clip_frame===frame).map(e=>({hit:'● 유효타',fire:'● 발사',attach_hand:'손 장착',attach_mount:'수납'}[e.type]||e.type)).join(' · ');[...$('strip').children].forEach((b,i)=>b.classList.toggle('active',i===frame))}
function step(d){playing=false;frame=Math.max(0,Math.min(clips[selected].count-1,frame+d));draw()}
$('prev').onclick=()=>step(-1);$('next').onclick=()=>step(1);$('play').onclick=()=>{playing=!playing;if(playing&&frame===clips[selected].count-1)frame=0;draw()};$('seek').oninput=e=>{playing=false;frame=Number(e.target.value);draw()};$('ghost').onchange=draw;
$('combo').onclick=()=>{combo=true;select(clips.findIndex(c=>c.name==='combo_1'));playing=true;draw()};document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT'||e.target.tagName==='INPUT')return;if(e.code==='Space'){e.preventDefault();$('play').click()}if(e.code==='ArrowLeft')step(-1);if(e.code==='ArrowRight')step(1)});
function tick(now){if(last&&playing){acc+=Math.min(now-last,150)*Number($('speed').value);while(acc>=1000/12){acc-=1000/12;frame++;if(frame>=clips[selected].count){if(combo){let n=Number(clips[selected].name.slice(-1));if(n<4){select(clips.findIndex(c=>c.name===`combo_${n+1}`));break}else if($('repeat').checked){select(clips.findIndex(c=>c.name==='combo_1'));break}else{frame--;playing=false}}else if($('repeat').checked)frame=0;else{frame--;playing=false}}}draw()}last=now;requestAnimationFrame(tick)}select(0);requestAnimationFrame(tick);
</script></html>'''

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--index',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(build(args.index,args.output))
