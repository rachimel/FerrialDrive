"""기존 검토 이미지와 자세 목록으로 동작별 로컬 검토 화면을 만든다."""

import argparse
import html
import json
import os
from pathlib import Path


def create(catalog, review_directory):
    from PIL import Image, ImageDraw, ImageFont
    catalog = json.loads(Path(catalog).read_text(encoding='utf-8'))
    directory = Path(review_directory).resolve()
    review = json.loads((directory/'visual_review.json').read_text(encoding='utf-8'))
    theme = json.loads((Path(__file__).resolve().parents[1]/'theme_reference/theme.json').read_text(encoding='utf-8'))
    colors = theme['colors']
    font_path = Path(__file__).resolve().parents[2]/'data/fonts'/theme['fonts']['body']['path']
    if not font_path.exists():
        font_path = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/malgun.ttf'
    font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
    views = ['front', 'rear', 'left', 'right', 'top', 'bottom', 'oblique']
    evidence = {(e['frame'], e['view'], e['scale']): e['file'] for e in review['evidence']}
    poses = catalog['poses']
    pages = directory/'sheets'
    pages.mkdir(exist_ok=True)
    sheet_index = []
    for start in range(0, len(poses), 4):
        batch = poses[start:start+4]
        canvas = Image.new('RGB', (7*240, len(batch)*276), colors['background'])
        draw = ImageDraw.Draw(canvas)
        covered = []
        for row, pose in enumerate(batch):
            draw.text((8, row*276+3), f"P{pose['frame']:03d} · {pose['label']}", font=font, fill=colors['text'])
            for col, view in enumerate(views):
                path = directory/evidence[(pose['frame'], view, 'game')]
                with Image.open(path) as picture:
                    canvas.paste(picture.convert('RGBA'), (col*240, row*276+28), picture.getchannel('A'))
                covered.extend(evidence[(pose['frame'], view, scale)] for scale in ('detail', 'game'))
        output = pages/f'poses_{start//4+1:03d}.png'
        canvas.save(output)
        expanded = Image.new('RGB', (7*384, len(batch)*416), colors['background'])
        expanded_draw = ImageDraw.Draw(expanded)
        for row, pose in enumerate(batch):
            expanded_draw.text((8, row*416+3), f"P{pose['frame']:03d} · {pose['label']}", font=font, fill=colors['text'])
            for col, view in enumerate(views):
                with Image.open(directory/evidence[(pose['frame'], view, 'detail')]) as picture:
                    picture = picture.convert('RGBA').resize((384, 384), Image.Resampling.LANCZOS)
                    expanded.paste(picture, (col*384, row*416+28), picture.getchannel('A'))
        expanded.save(pages/f'detail_{start//4+1:03d}.png')
        sheet_index.append({'file': str(output.relative_to(directory)), 'pose_ids': [p['id'] for p in batch],
                            'game_images': [p for p in covered if '_game' in p],
                            'related_detail_images': [p for p in covered if '_detail' in p]})
    (pages/'index.json').write_text(json.dumps(sheet_index, ensure_ascii=False, indent=2), encoding='utf-8')
    payload = {'poses': poses, 'groups': catalog['groups'], 'pending': catalog.get('pending_design', []),
               'images': {str(p['frame']): {v: {s: evidence[(p['frame'], v, s)] for s in ('detail', 'game')}
                                         for v in views} for p in poses}, 'views': views}
    data = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    style = f"""
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:{colors['background']};color:{colors['text']};font:15px 'Malgun Gothic',sans-serif}}
    header{{padding:24px;border-bottom:1px solid {colors['line']}}}h1{{font-size:24px;margin:0 0 10px}}p{{line-height:1.6}}
    nav{{display:flex;gap:12px;padding:16px;position:sticky;top:0;background:{colors['panel']};z-index:1}}select,input,button{{background:{colors['input']};color:inherit;border:1px solid {colors['line']};padding:10px;border-radius:4px}}select{{max-width:65vw}}button{{cursor:pointer}}
    #status{{color:{colors['warning']}}}main{{padding:16px}}.group{{margin-bottom:28px}}.grid{{display:flex;flex-wrap:wrap;gap:12px}}article{{background:{colors['panel']};border:1px solid {colors['line']};padding:12px;width:340px}}article img{{width:150px;background:{colors['background']};cursor:zoom-in}}article h3{{font-size:16px;margin:0 0 8px}}small{{color:{colors['muted']}}}dialog{{width:min(1400px,96vw);max-height:94vh;background:{colors['panel']};color:inherit;border:1px solid {colors['line']}}}dialog::backdrop{{background:#000b}}.views{{display:flex;flex-wrap:wrap;gap:12px}}figure{{margin:0}}figure img{{width:min(384px,84vw)}}figcaption{{padding:6px}}.note{{color:{colors['warning']};font-size:13px}}footer{{padding:20px;color:{colors['muted']}}}
    """
    page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>메카 키포즈 검토</title><style>{style}</style>
    <header><h1>메카 키포즈 검토</h1><div id="status">정지 키포즈 후보 · 사이 동작 없음 · 각도 제한 미적용 · 사용자 피드백 대기</div><p>{len(poses)}개 자세 / {len(catalog['groups'])}개 동작·연결 묶음. 이미지를 누르면 6면과 사선을 확대한다.<br>번호는 자세 ID이며 재생 타이밍이 아니다. 같은 자세를 여러 동작에서 공유한다.</p></header>
    <nav><select id="group"></select><input id="query" placeholder="동작 또는 자세 검색"><button id="all">전체 보기</button></nav><main id="main"></main>
    <dialog id="detail"><button id="close">닫기</button><h2 id="pose-title"></h2><p id="pose-note"></p><label>표시 크기 <select id="scale"><option value="detail">확대</option><option value="game">240px</option></select></label><div class="views" id="views"></div></dialog>
    <footer><strong>미정·미검증</strong><ul>{''.join('<li>'+html.escape(n)+'</li>' for n in catalog.get('pending_design', []))}</ul><p>총 슬롯 접근은 손잡이 접촉 미해결 후보다. 대시 중 전환은 슬롯 접근 자세와 대시 자세의 관계 후보이며 전체 접촉 경로를 검증한 동작이 아니다.</p></footer>
    <script>const D={data};const $=s=>document.querySelector(s);const byId=Object.fromEntries(D.poses.map(p=>[p.id,p]));
    const sel=$('#group');sel.add(new Option('전체 묶음','all'));D.groups.forEach(g=>sel.add(new Option(g.label,g.id)));sel.value=D.groups[0].id;
    let active=null;const names={{front:'정면',rear:'후면',left:'기체 왼쪽',right:'기체 오른쪽',top:'위',bottom:'아래',oblique:'사선'}};
    function el(tag,text){{let n=document.createElement(tag);if(text)n.textContent=text;return n}}
    function showPose(p){{active=p;$('#pose-title').textContent=`P${{String(p.frame).padStart(3,'0')}} · ${{p.label}}`;$('#pose-note').textContent=(p.support?'지지: '+p.support+' · ':'')+(p.contact||'')+(p.provisional_lower_body_direction?' · 하체 방향 미확정 후보':'')+' '+(p.review_notes||[]).join(' · ');showViews();$('#detail').showModal()}}
    function showViews(){{let v=$('#views');v.replaceChildren();D.views.forEach(name=>{{let f=el('figure'),i=el('img');i.src=D.images[active.frame][name][$('#scale').value];i.alt=active.label+' '+names[name];f.append(i,el('figcaption',names[name]));v.append(f)}})}}
    function render(){{let root=$('#main');root.replaceChildren();let query=$('#query').value.toLowerCase();D.groups.filter(g=>(sel.value==='all'||g.id===sel.value)&&(g.label+' '+g.poses.map(id=>id+' '+byId[id].label).join(' ')).toLowerCase().includes(query)).forEach(g=>{{let section=el('section');section.className='group';section.append(el('h2',g.label));if(g.design_note){{let n=el('p',g.design_note);n.className='note';section.append(n)}}let grid=el('div');grid.className='grid';g.poses.forEach(id=>{{let p=byId[id],card=el('article');card.append(el('h3',`P${{String(p.frame).padStart(3,'0')}} · ${{p.label}}`));['oblique','front'].forEach(view=>{{let i=el('img');i.src=D.images[p.frame][view].game;i.alt=p.label;i.loading='lazy';i.onclick=()=>showPose(p);card.append(i)}});card.append(el('small',p.support||'정지 자세 후보'));if(p.review_notes){{let n=el('p',p.review_notes.join(' · '));n.className='note';card.append(n)}}grid.append(card)}});section.append(grid);root.append(section)}})}}
    sel.onchange=render;$('#query').oninput=render;$('#all').onclick=()=>{{sel.value='all';render()}};$('#close').onclick=()=>$('#detail').close();$('#scale').onchange=showViews;render();</script></html>'''
    (directory/'index.html').write_text(page, encoding='utf-8')
    print(json.dumps({'gallery': str(directory/'index.html'), 'sheets': len(sheet_index), 'poses': len(poses)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--review', required=True)
    args = parser.parse_args()
    create(args.catalog, args.review)
