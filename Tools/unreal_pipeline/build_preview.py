"""동작의 방향별 프레임을 12fps 로컬 검토 페이지와 GIF로 묶는다."""
import argparse
import html
import json
import os
from pathlib import Path


def main():
    from motion_review import Image, ImageDraw, save_gif
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    theme = json.loads((root/"Tools/theme_reference/theme.json").read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    views = catalog.get("views", [["oblique", "사선"], ["side", "측면"]])
    title = catalog.get("title", "Unreal 왕복 애니메이션 · 검토용 초안")
    source_label = catalog.get("source_label", "Blender")
    output = args.review.resolve()
    atlas = output/"atlas"
    atlas.mkdir(exist_ok=True)
    media = output / "media"
    media.mkdir(exist_ok=True)
    cards, animation_data = [], []
    background = theme["colors"]["background"]
    for clip in catalog["clips"]:
        frames = list(range(clip["start"],clip["end"]+1))
        size, count = 240, len(frames)
        sheet = Image.new("RGB",(size*count,size*len(views)),background)
        contact = Image.new("RGB",(size*6,(size+20)*len(views)*((count+5)//6)),background)
        playback = [Image.new("RGB", (size*len(views), size), background) for _ in frames]
        draw = ImageDraw.Draw(contact)
        for row, (view, view_label) in enumerate(views):
            for index, frame in enumerate(frames):
                path = output/"frames"/f"{view}_f{frame}_game.png"
                image = Image.open(path).convert("RGBA")
                tile = Image.new("RGBA",image.size,background)
                tile.alpha_composite(image)
                tile = tile.convert("RGB")
                sheet.paste(tile,(index*size,row*size))
                playback[index].paste(tile, (row*size, 0))
                y = (row*((count+5)//6)+index//6)*(size+20)
                contact.paste(tile,((index%6)*size,y))
                draw.text(((index%6)*size+8,y+size+2),f"{view} {index+1}/{count}",fill=theme["colors"]["text"])
        name = clip["name"]
        sheet.save(atlas/(name+".webp"),lossless=True)
        contact.save(atlas/(name+"_contact.jpg"),quality=93)
        save_gif(media/(name+".gif"), playback, clip["fps"])
        save_gif(media/(name+"_slow.gif"), playback, clip["fps"], slow=True)
        animation_data.append({"name":name,"count":count,"fps":clip["fps"],"image":"atlas/"+name+".webp"})
        safe = html.escape(name)
        directions = [("front","정면"),("rear","후면"),("left","좌측"),("right","우측"),("top","위"),("bottom","아래")]
        orbit = ''
        if all((output/f'poses/{name}/{direction}_detail.png').is_file() for direction, _ in directions):
            orbit = '<details><summary>6면 확대</summary><div style="display:grid;grid-template-columns:repeat(3,1fr)">'
            for direction,label in directions:
                filename = f'poses/{safe}/{direction}_detail.png'
                orbit += f'<a href="{filename}" target="_blank"><img src="{filename}" style="width:100%" alt="{label}">{label}</a>'
            orbit += '</div></details>'
        label = html.escape(clip.get('label', name))
        review_note = ('<p class="note">'+html.escape(clip['review_note'])+'</p>') if clip.get('review_note') else ''
        detail = (' · <a href="'+html.escape(clip['detail'], quote=True)+'" target="_blank">원본 확대</a>') if clip.get('detail') else ''
        cards.append(f'<article data-name="{safe}"><h2>{label}</h2><div>{count}프레임 · {clip["fps"]}fps · {html.escape(source_label)}</div><canvas width="{240*len(views)}" height="240"></canvas><input type="range" min="0" max="{count-1}" value="0">{review_note}<a href="media/{safe}.gif" target="_blank">정상 재생</a> · <a href="media/{safe}_slow.gif" target="_blank">느린 재생</a> · <a href="atlas/{safe}_contact.jpg" target="_blank">전체 프레임 확대</a>{detail}{orbit}</article>')
    variables = ";".join("--"+key.replace("_","-")+":"+value for key,value in theme["colors"].items())
    fonts = "".join("@font-face{font-family:FD"+role+";src:url('"+Path(os.path.relpath(root/"data/fonts"/theme["fonts"][role]["path"],output)).as_posix()+"')}" for role in ("title","body"))
    document = '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>Unreal 왕복 애니메이션 초안</title>
<style>:root{THEME}*{box-sizing:border-box}body{margin:0;background:var(--background);color:var(--text);font:16px sans-serif}header{position:sticky;top:0;padding:16px;background:var(--panel-surface);z-index:2}h1{font-size:20px;margin:0 0 8px}button,input{font:inherit}button{background:var(--button);color:var(--button-text);border:0;padding:8px 16px;margin-right:12px}input[type=search]{background:var(--input);color:var(--text);border:1px solid var(--line);padding:8px}main{padding:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:12px}article{padding:12px;background:var(--panel);min-width:0}h2{font-size:18px;margin:0 0 8px}canvas{display:block;width:100%;max-width:640px;aspect-ratio:2}a{color:var(--accent)}article input{width:100%}.note{color:var(--muted);font-size:14px;margin:8px 0 0}</style>
<header><h1>Unreal 왕복 애니메이션 · 검토용 초안</h1><button id="play">일시 정지</button><input id="search" type="search" placeholder="동작 ID 검색"><p class="note">사선 / 측면 · 12fps. 관절·파지·체중 이동을 검토한다. 사용자 품질 승인과 Pico2D 연결은 별도다.</p></header><main>CARDS</main>
<script>const clips=DATA;let playing=true;const views=clips.map((clip,i)=>{const card=document.querySelectorAll('article')[i],canvas=card.querySelector('canvas'),slider=card.querySelector('input'),image=new Image();image.src=clip.image;const state={clip,card,canvas,slider,image,frame:0};slider.oninput=()=>{state.frame=+slider.value;draw(state)};image.onload=()=>draw(state);return state});function draw(s){if(!s.image.complete)return;const c=s.canvas.getContext('2d');c.clearRect(0,0,480,240);for(let i=0;i<2;i++)c.drawImage(s.image,s.frame*240,i*240,240,240,i*240,0,240,240);s.slider.value=s.frame}let previous=0;function loop(t){if(t-previous>=1000/12){if(playing)for(const s of views){if(s.card.hidden)continue;s.frame=(s.frame+1)%s.clip.count;draw(s)}previous=t}requestAnimationFrame(loop)}requestAnimationFrame(loop);document.querySelector('#play').onclick=()=>{playing=!playing;document.querySelector('#play').textContent=playing?'일시 정지':'재생'};document.querySelector('#search').oninput=e=>{for(const s of views)s.card.hidden=!s.clip.name.includes(e.target.value)};</script></html>'''
    document = document.replace("<style>","<style>"+fonts).replace("THEME",variables).replace("CARDS","".join(cards)).replace("DATA",json.dumps(animation_data))
    document = document.replace('Unreal 왕복 애니메이션 · 검토용 초안', html.escape(title))
    document = document.replace('Unreal 왕복 애니메이션 초안', html.escape(title))
    document = document.replace('사선 / 측면 · 12fps.', ' / '.join(html.escape(label) for _, label in views)+' · 12fps. 검토용 반복 재생.')
    document = document.replace('aspect-ratio:2}', f'aspect-ratio:{len(views)}}}')
    document = document.replace('clearRect(0,0,480,240)', 'clearRect(0,0,s.canvas.width,240)').replace('i<2;i++', f'i<{len(views)};i++')
    document = document.replace('function loop(t){', 'function loop(t){if(!previous)previous=t;')
    document = document.replace('if(t-previous>=1000/12){', 'if(t-previous>=1000/12){const steps=Math.floor((t-previous)/(1000/12));')
    document = document.replace('s.frame=(s.frame+1)%s.clip.count', 's.frame=(s.frame+steps)%s.clip.count').replace('previous=t}', 'previous+=steps*(1000/12)}')
    document = document.replace("font:16px sans-serif", "font:18px FDbody,sans-serif").replace("h1{font-size:20px", "h1{font-family:FDtitle,sans-serif;font-weight:normal;font-size:20px")
    (output/"index.html").write_text(document,encoding="utf-8")
    print(json.dumps({"clips":len(animation_data),"preview":str(output/"index.html")}))


if __name__ == "__main__":
    main()
