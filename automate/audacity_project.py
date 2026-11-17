"""Audacity 3 프로젝트의 저장된 파형·배치·게인을 읽기 전용으로 인계한다.

바이너리 필드 규약 참고: Audacity ProjectSerializer.cpp (GPL v2 or later)
https://github.com/audacity/audacity/blob/Audacity-3.7.7/libraries/lib-project-file-io/ProjectSerializer.cpp
지원 범위: float32, 한 트랙당 한 클립, 중앙 패닝, 빈 실시간 이펙트·엔벌로프.
미지원 편집은 근사 변환하지 않고 거절한다. 파형에 저장된 오프라인 효과는 보존한다.
"""

import argparse
from array import array
from contextlib import closing
from hashlib import sha256
import json
from math import isfinite, log10
from pathlib import Path
import sqlite3
import struct
import sys
import wave
import xml.etree.ElementTree as ET


FLOAT32 = 262159


def decode_document(dictionary, document):
    """Audacity 3의 고정 폭 리틀 엔디언 필드를 XML 트리로 읽는다."""
    data = dictionary + document
    position, char_size = 0, 0
    names, dictionaries, stack = {}, [], []
    root = None

    def read(format_code):
        nonlocal position
        size = struct.calcsize('<' + format_code)
        if position + size > len(data):
            raise ValueError('프로젝트 필드가 잘렸다.')
        result = struct.unpack_from('<' + format_code, data, position)[0]
        position += size
        return result

    def read_string(length):
        nonlocal position
        encoding = {1: 'utf-8', 2: 'utf-16le', 4: 'utf-32le'}.get(char_size)
        if not encoding or length < 0 or position + length > len(data):
            raise ValueError('프로젝트 문자열 범위 오류')
        value = data[position:position + length].decode(encoding)
        position += length
        return value

    try:
        while position < len(data):
            kind = read('B')
            if kind == 0:
                char_size = read('B')
            elif kind == 15:
                key = read('H')
                names[key] = read_string(read('H'))
            elif kind == 13:
                dictionaries.append((names.copy(), char_size))
            elif kind == 14:
                names, char_size = dictionaries.pop()
            elif kind == 1:
                element = ET.Element(names[read('H')])
                if stack:
                    stack[-1].append(element)
                elif root is None:
                    root = element
                else:
                    raise ValueError('프로젝트 루트가 여러 개다.')
                stack.append(element)
            elif kind == 2:
                if stack.pop().tag != names[read('H')]:
                    raise ValueError('프로젝트 태그가 일치하지 않는다.')
            elif kind in (11, 12):
                value = read_string(read('i'))
                if kind == 11:
                    stack[-1].text = (stack[-1].text or '') + value
            elif kind in (3, 4, 5, 6, 7, 8, 9, 10):
                name = names[read('H')]
                if kind == 3:
                    value = read_string(read('i'))
                else:
                    value = read({4: 'i', 5: 'B', 6: 'i', 7: 'q', 8: 'I', 9: 'f', 10: 'd'}[kind])
                    if kind in (9, 10):
                        read('i')
                stack[-1].set(name, str(value))
            else:
                raise ValueError(f'미지원 프로젝트 필드: {kind}')
    except (IndexError, KeyError, struct.error, UnicodeError) as error:
        raise ValueError('프로젝트 문서를 해석할 수 없다.') from error
    if stack or dictionaries or root is None or root.tag != 'project':
        raise ValueError('불완전한 프로젝트 문서')
    return root


def read_tracks(source):
    """원본을 수정하지 않고 저장된 각 채널의 float PCM과 정확한 배치를 읽는다."""
    source = Path(source).resolve()
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as database:
        if database.execute('SELECT COUNT(*) FROM autosave').fetchone()[0]:
            raise ValueError('저장하지 않은 작업이 있다. Audacity에서 저장한 뒤 인계한다.')
        row = database.execute('SELECT dict, doc FROM project WHERE id=1').fetchone()
        if row is None:
            raise ValueError('저장된 프로젝트가 없다.')
        root = decode_document(*row)
        for effects in root.iter('effects'):
            if len(effects):
                raise ValueError('실시간 이펙트는 Audacity에서 적용한 파형으로 인계한다.')
        channels = []
        for track in root.findall('wavetrack'):
            if any(float(track.get(key, '0')) != 0 for key in ('pan', 'mute', 'solo')):
                raise ValueError('패닝·음소거·솔로가 있는 트랙은 지원하지 않는다.')
            clips = track.findall('waveclip')
            if len(clips) != 1:
                raise ValueError('트랙당 한 클립만 지원한다.')
            clip = clips[0]
            if float(clip.get('clipStretchRatio', '1')) != 1 or float(clip.get('centShift', '0')) != 0:
                raise ValueError('실시간 속도·피치 편집은 먼저 파형에 적용한다.')
            if any(int(envelope.get('numpoints', '0')) for envelope in clip.iter('envelope')):
                raise ValueError('엔벌로프 편집은 먼저 파형에 적용한다.')
            rate = float(track.get('rate'))
            gain = float(track.get('gain', '1'))
            offset = float(clip.get('offset', '0'))
            left, right = (float(clip.get(key, '0')) for key in ('trimLeft', 'trimRight'))
            if (not all(isfinite(v) for v in (rate, gain, offset, left, right))
                    or not rate.is_integer() or not 8000 <= rate <= 192000
                    or min(gain, offset, left, right) < 0):
                raise ValueError('트랙 시간·게인·샘플레이트 범위 오류')
            sequence = clip.find('sequence')
            if sequence is None or int(sequence.get('sampleformat')) != FLOAT32:
                raise ValueError('저장된 float32 파형만 지원한다.')
            samples = array('f')
            for block in sequence.findall('waveblock'):
                row = database.execute('SELECT sampleformat, samples FROM sampleblocks WHERE blockid=?',
                                       (int(block.get('blockid')),)).fetchone()
                if row is None or row[0] != FLOAT32 or int(block.get('start')) != len(samples):
                    raise ValueError('PCM 블록 누락·형식·배치 오류')
                piece = array('f', row[1])
                if sys.byteorder != 'little':
                    piece.byteswap()
                if 'length' in block.attrib and len(piece) != int(block.get('length')):
                    raise ValueError('PCM 블록 길이가 일치하지 않는다.')
                samples.extend(piece)
            if len(samples) != int(sequence.get('numsamples')) or not all(map(isfinite, samples)):
                raise ValueError('PCM 길이·샘플 값 오류')
            start, stop = round(left * rate), len(samples) - round(right * rate)
            if not 0 <= start < stop <= len(samples):
                raise ValueError('클립 잘라내기 범위 오류')
            channels.append({'name': track.get('name'), 'rate': int(rate), 'gain': gain,
                             'offset_seconds': offset + left, 'linked': int(track.get('linked', '0')),
                             'channel': int(track.get('channel', '0')), 'samples': samples[start:stop]})
    tracks, index = [], 0
    while index < len(channels):
        first = channels[index]
        count = 2 if first['linked'] == 3 else 1
        group = channels[index:index + count]
        if first['linked'] not in (0, 3) or len(group) != count or first['channel'] != 0:
            raise ValueError('미지원 채널 연결')
        if count == 2:
            second = group[1]
            if second['channel'] != 1 or second['linked'] != 0 or any(
                    first[key] != second[key] for key in ('name', 'rate', 'gain', 'offset_seconds')):
                raise ValueError('스테레오 채널 정보가 다르다.')
            if len(first['samples']) != len(second['samples']):
                raise ValueError('스테레오 채널 길이가 다르다.')
        tracks.append(dict(name=first['name'], rate=first['rate'], gain=first['gain'],
                           offset_seconds=first['offset_seconds'], channels=[item['samples'] for item in group]))
        index += count
    if not tracks or len({item['name'] for item in tracks}) != len(tracks):
        raise ValueError('트랙이 없거나 이름이 중복됐다.')
    return tracks


def export_tracks(source, output, mapping, *, headroom=0.5):
    """트랙 게인과 같은 전체 감쇠를 굽고, 시작 시점은 앞 무음으로 보존한다."""
    if not isfinite(headroom) or not 0 < headroom <= 1:
        raise ValueError('전체 감쇠는 0 초과 1 이하다.')
    tracks = read_tracks(source)
    if set(mapping) != {item['name'] for item in tracks}:
        raise ValueError('출력 매핑은 모든 트랙과 정확히 일치해야 한다.')
    if len(set(mapping.values())) != len(mapping) or any(
            Path(name).name != name or '/' in name or '\\' in name or not name.endswith('.wav')
            for name in mapping.values()):
        raise ValueError('출력 파일명은 중복 없는 WAV 이름이어야 한다.')
    prepared, manifest = [], []
    for track in tracks:
        gain = track['gain'] * headroom
        channels = track['channels']
        peak = max(abs(value * gain) for channel in channels for value in channel)
        if peak >= 1:
            raise ValueError('전체 감쇠가 부족하다. 개별 트랙 정규화 없이 headroom을 낮춘다.')
        padding = round(track['offset_seconds'] * track['rate'])
        pcm = array('h', [0]) * (padding * len(channels))
        pcm.extend(round(value * gain * 32767) for frame in zip(*channels) for value in frame)
        if sys.byteorder != 'little':
            pcm.byteswap()
        prepared.append((mapping[track['name']], track['rate'], len(channels), pcm.tobytes()))
        manifest.append({key: value for key, value in track.items() if key != 'channels'} | {
            'gain_db': 20 * log10(track['gain']) if track['gain'] else None,
            'file': mapping[track['name']], 'channel_count': len(channels),
            'offset_frames': padding, 'frames': len(pcm) // len(channels), 'peak': peak})
    output = Path(output)
    if output.exists():
        raise ValueError('기존 출력 대신 새 폴더를 지정한다.')
    output.mkdir(parents=True)
    for name, rate, count, payload in prepared:
        with wave.open(str(output / name), 'wb') as target:
            target.setparams((count, 2, rate, 0, 'NONE', 'not compressed'))
            target.writeframes(payload)
    result = {'source': str(Path(source).resolve()), 'source_sha256': sha256(Path(source).read_bytes()).hexdigest(),
              'headroom': headroom, 'baked_track_gain': True, 'tracks': manifest}
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--headroom', type=float, default=0.5)
    args = parser.parse_args()
    if args.output is None:
        result = [{key: value for key, value in item.items() if key != 'channels'} |
                  {'channel_count': len(item['channels']), 'frames': len(item['channels'][0])}
                  for item in read_tracks(args.source)]
    else:
        if args.mapping is None:
            parser.error('출력에는 --mapping JSON이 필요하다.')
        result = export_tracks(args.source, args.output,
                               json.loads(args.mapping.read_text(encoding='utf-8')), headroom=args.headroom)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
