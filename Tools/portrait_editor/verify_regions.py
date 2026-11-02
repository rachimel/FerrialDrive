"""Real-window verification using the editor's own input handlers.

Only file dialogs are supplied deterministic paths. This is not an OS-mouse test.
"""
import argparse
import copy
import json
import time

import numpy as np
import pygame

from app import Editor
from core import ROOT, WORK
from region_document import RegionDocument


def main():
    args = argparse.Namespace(verify=True, project=None, width=1600, height=940,
                              seconds=0, measure=False, autoplay=False, pose=None)
    app = Editor(args)
    qa = WORK / 'qa' / 'regions'
    qa.mkdir(parents=True, exist_ok=True)
    baseline = copy.deepcopy(app.project.data)
    report = {}
    try:
        started = time.perf_counter()
        while app.canvas.model is None:
            for event in pygame.event.get():
                app.handle(event)
            app.poll_build()
            if time.perf_counter() - started > 60:
                raise TimeoutError('Live2D preview initialization timed out')
            time.sleep(.02)

        def render(capture=None):
            app.canvas.draw(app, app.render_ui())
            if capture:
                app.canvas.capture(qa / capture)
            pygame.display.flip()

        app.click('ai_regions')
        assert app.regions is not None
        region = app.regions
        paths = {'image': ROOT / 'data' / 'live2d-test-image.png',
                 'save': qa / 'checked.regions.zip', 'open': qa / 'checked.regions.zip',
                 'export': qa}
        region.dialog = lambda kind: str(paths[kind])

        def click(name, value=None):
            render()
            rect = next(rect for action, rect, data in region.ui.hits
                        if action == name and (value is None or data == value))
            app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
            app.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=rect.center))
            render()

        def key(value, mod=0):
            app.handle(pygame.event.Event(pygame.KEYDOWN, key=value, mod=mod))

        def point(x, y):
            region.geometry(app.size)
            return (round(region.image_rect.x + x * region.scale),
                    round(region.image_rect.y + y * region.scale))

        def stroke(points):
            positions = [point(*p) for p in points]
            app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=positions[0]))
            for position in positions[1:]:
                app.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=position, rel=(0, 0), buttons=(1, 0, 0)))
            app.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=positions[-1]))
            render()

        click('image')
        assert region.document.image.get_size() == (896, 1152)
        click('rename')
        key(pygame.K_a, pygame.KMOD_CTRL)
        app.handle(pygame.event.Event(pygame.TEXTINPUT, text='머리카락'))
        key(pygame.K_RETURN)
        assert region.document.current['name'] == '머리카락'
        stroke([(355, 170), (370, 140), (430, 125), (485, 170), (495, 220)])
        initial = pygame.surfarray.array2d(region.document.mask())
        click('eraser')
        stroke([(430, 125)])
        assert not np.array_equal(pygame.surfarray.array2d(region.document.mask()), initial)
        key(pygame.K_z, pygame.KMOD_CTRL)
        np.testing.assert_array_equal(pygame.surfarray.array2d(region.document.mask()), initial)
        click('add')
        click('rename')
        key(pygame.K_a, pygame.KMOD_CTRL)
        app.handle(pygame.event.Event(pygame.TEXTINPUT, text='왼쪽 눈'))
        key(pygame.K_RETURN)
        click('brush')
        region.radius = 10
        stroke([(395, 181), (414, 184)])
        key(pygame.K_s, pygame.KMOD_CTRL)
        assert not region.document.dirty
        expected = copy.deepcopy(region.document.regions)
        click('export')
        outputs = sorted(qa.glob('ai-regions-*/manifest.json'), key=lambda p: p.stat().st_mtime)
        output = outputs[-1].parent
        manifest = json.loads(outputs[-1].read_text(encoding='utf-8'))
        assert len(manifest['regions']) == 2 and manifest['size'] == [896, 1152]
        click('open')
        assert region.document.regions == json.loads(json.dumps(expected))
        render('regions-workspace.png')

        # Zoom, pan, and a compact resize must still paint in original coordinates.
        for size in [(1280, 800), (1600, 940)]:
            app.native_window.size = size
            app.handle(pygame.event.Event(pygame.VIDEORESIZE, w=size[0], h=size[1], size=size))
            region.zoom = 2.
            region.pan = [15., 280.]
            render()
            if size == (1280, 800):
                render('regions-compact.png')
        region.fit()
        render()
        stroke([(450, 210)])
        click('back')
        assert region.pending is not None
        click('cancel')
        assert app.regions is region and region.pending is None
        click('back')
        click('save_continue')
        assert app.regions is None
        assert app.project.data == baseline
        render()

        # Exercise application quit with BOTH workspaces dirty. The second prompt
        # must return to the rigging UI rather than becoming invisible behind masks.
        app.click('ai_regions')
        app.regions.replace(RegionDocument.load(paths['save']))
        app.regions.document.rename('종료 확인용')
        app.project.checkpoint()
        app.project.data['motion']['duration'] = 3.
        app.project.changed()
        app.handle(pygame.event.Event(pygame.QUIT))
        assert app.regions.pending is not None
        app.regions.action('discard')
        assert app.regions is None and app.modal is not None and app.running
        app.action('modal_cancel')
        app.action('undo')
        assert app.project.data == baseline
        report = {'file_menu_entry': True, 'image_open_via_dialog_adapter': True,
                  'region_names_and_two_independent_masks': True, 'brush_eraser_undo': True,
                  'portable_save_reopen': True, 'original_pixel_size_export': True,
                  'unsaved_cancel_and_save_on_return': True, 'dual_workspace_quit_guard': True,
                  'rig_project_unchanged': True, 'compact_and_zoom_render': True,
                  'bundle': str(output), 'captures': [str(qa / 'regions-workspace.png'), str(qa / 'regions-compact.png')],
                  'method': 'Real OpenGL window; production menu/input handlers; deterministic file-dialog paths. Not OS-mouse or AI extraction verification.'}
        (qa / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        app.executor.shutdown(wait=True, cancel_futures=True)
        app.canvas.close()
        import live2d
        live2d.dispose()
        pygame.quit()


if __name__ == '__main__':
    main()
