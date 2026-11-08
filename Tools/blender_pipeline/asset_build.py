"""별도 Blender 프로세스·패킹·완료 결과의 수명을 관리한다. 창을 열지 않는다."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from ferrial_drive.assets import SpriteBundle
from .pack_sprites import pack_rendered_frames
from .child_scope import ChildScope


ROOT = Path(__file__).resolve().parents[2]


def pipeline_signature():
    directory = Path(__file__).parent
    return hashlib.sha256(b''.join((directory / name).read_bytes() for name in
                                  ('render_asset_sample.py', 'pack_sprites.py', 'framing.py'))).hexdigest()


def find_blender(explicit=None):
    candidates = [explicit, os.environ.get('BLENDER_EXECUTABLE'), shutil.which('blender')]
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall') as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                                name = winreg.QueryValueEx(entry, 'DisplayName')[0]
                                if 'blender' in name.lower():
                                    candidates.append(Path(winreg.QueryValueEx(entry, 'InstallLocation')[0]) / 'blender.exe')
                        except OSError:
                            continue
            except OSError:
                continue
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
            if base:
                candidates.extend((Path(base) / 'Blender Foundation').glob('Blender*/blender.exe'))
                candidates.append(Path(base) / 'Steam/steamapps/common/Blender/blender.exe')
    if explicit:
        candidates = [explicit]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError('Blender를 찾지 못했다. --blender 경로 또는 BLENDER_EXECUTABLE을 지정한다.')


class AssetBuild:
    def __init__(self, config_path, *, blender=None, output_root=None, source_blend=None):
        self.config_path = Path(config_path).resolve()
        self.blender = blender
        self.source_blend = Path(source_blend).resolve() if source_blend else None
        self.output_root = Path(output_root or ROOT / 'output/asset_load_test').resolve()
        self.process = None
        self.log = None
        self.directory = None
        self.result = None
        self.error = None
        self.scope = None

    def cached_result(self):
        pointer = self.output_root / 'latest.json'
        if not pointer.is_file():
            return None
        try:
            data = json.loads(pointer.read_text(encoding='utf-8'))
            path = (self.output_root / data['bundle']).resolve()
            if self.output_root not in path.parents:
                return None
            bundle = SpriteBundle.load(path)
            metadata = json.loads(path.read_text(encoding='utf-8'))
            if (bundle.config_sha256 == hashlib.sha256(self.config_path.read_bytes()).hexdigest()
                    and metadata.get('pipeline_sha256') == pipeline_signature()
                    and metadata.get('source_sha256') == self.source_signature()):
                return path
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def source_signature(self):
        return hashlib.sha256(self.source_blend.read_bytes()).hexdigest() if self.source_blend else None

    def start(self):
        if self.process is not None:
            raise RuntimeError('이미 진행 중인 빌드다.')
        executable = find_blender(self.blender)
        self.source_sha256 = self.source_signature()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ') + '-' + uuid4().hex[:8]
        self.directory = self.output_root / stamp
        self.directory.mkdir(parents=True)
        config = self.directory / 'render_config.json'
        config.write_bytes(self.config_path.read_bytes())
        work_file = ROOT / 'Tools/blender_pipeline/workspace/asset_load_test' / stamp / 'sample.blend'
        command = [str(executable), '--background', '--factory-startup', '--python-exit-code', '1',
                   '--python', str(Path(__file__).with_name('render_asset_sample.py')), '--',
                   '--config', str(config), '--output', str(self.directory), '--work-file', str(work_file)]
        if self.source_blend:
            command.extend(('--source-blend', str(self.source_blend)))
        self.error, self.result = None, None
        self.log = (self.directory / 'blender.log').open('wb')
        try:
            self.scope = ChildScope()
            self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                            stdout=self.log, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), shell=False)
            self.scope.attach(self.process)
        except BaseException:
            self.close()
            raise

    def poll(self):
        if self.process is None or self.process.poll() is None:
            return None
        returncode = self.process.returncode
        self.process = None
        if self.scope:
            self.scope.close()
            self.scope = None
        self.log.close()
        self.log = None
        try:
            if returncode:
                raise RuntimeError(f'Blender 종료 코드 {returncode}. {self.directory / "blender.log"}')
            result = pack_rendered_frames(self.directory / 'rendered_frames.json')
            metadata = json.loads(result.read_text(encoding='utf-8'))
            metadata['pipeline_sha256'] = pipeline_signature()
            metadata['source_sha256'] = self.source_sha256
            result.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            SpriteBundle.load(result)
            pointer = self.output_root / 'latest.json'
            temporary = self.directory / 'latest.tmp'
            temporary.write_text(json.dumps({'bundle': result.relative_to(self.output_root).as_posix()}), encoding='utf-8')
            os.replace(temporary, pointer)
            self.result = result
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.error = str(error)
        return self.error is None

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            self.process = None
        if self.scope:
            self.scope.close()
            self.scope = None
        if self.log is not None:
            self.log.close()
            self.log = None
