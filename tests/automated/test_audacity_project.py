"""Audacity 파형 인계의 게인·스테레오·배치 보존과 미지원 편집 거절을 검사한다."""

from array import array
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET

from automate.audacity_project import decode_document, export_tracks, read_tracks


def encode_document(root):
    names = sorted({value for element in root.iter() for value in (element.tag, *element.attrib)})
    identifiers = {name: index for index, name in enumerate(names)}
    dictionary = bytearray((0, 2))
    for name, identifier in identifiers.items():
        encoded = name.encode('utf-16le')
        dictionary.extend(struct.pack('<BHH', 15, identifier, len(encoded)) + encoded)
    document = bytearray()

    def write(element):
        document.extend(struct.pack('<BH', 1, identifiers[element.tag]))
        for name, value in element.attrib.items():
            encoded = value.encode('utf-16le')
            document.extend(struct.pack('<BHi', 3, identifiers[name], len(encoded)) + encoded)
        for child in element:
            write(child)
        document.extend(struct.pack('<BH', 2, identifiers[element.tag]))

    write(root)
    return bytes(dictionary), bytes(document)


class AudacityProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'fixture.aup3'
        self.project = ET.Element('project')
        ET.SubElement(self.project, 'effects', active='1')
        self.rows = []
        for channel in (0, 1):
            self.add_track('스테레오', channel, 3 if channel == 0 else 0, 1.4125375446,
                           [.5, -.25] if channel == 0 else [-.1, .3], .001)
        self.add_track('금속', 0, 0, .1584893192, [.8, -.5], 0)
        self.write_database()

    def add_track(self, name, channel, linked, gain, samples, offset):
        track = ET.SubElement(self.project, 'wavetrack', name=name, channel=str(channel),
                              linked=str(linked), gain=str(gain), pan='0', mute='0', solo='0', rate='8000')
        ET.SubElement(track, 'effects', active='1')
        clip = ET.SubElement(track, 'waveclip', offset=str(offset), trimLeft='0', trimRight='0',
                             clipStretchRatio='1', centShift='0')
        sequence = ET.SubElement(clip, 'sequence', sampleformat='262159', numsamples=str(len(samples)))
        block_id = len(self.rows) + 1
        ET.SubElement(sequence, 'waveblock', start='0', length=str(len(samples)), blockid=str(block_id))
        ET.SubElement(clip, 'envelope', numpoints='0')
        self.rows.append((block_id, 262159, struct.pack('<' + 'f' * len(samples), *samples)))

    def write_database(self):
        with closing(sqlite3.connect(self.source)) as database:
            database.execute('CREATE TABLE IF NOT EXISTS project(id INTEGER, dict BLOB, doc BLOB)')
            database.execute('CREATE TABLE IF NOT EXISTS autosave(id INTEGER)')
            database.execute('CREATE TABLE IF NOT EXISTS sampleblocks(blockid INTEGER, sampleformat INTEGER, samples BLOB)')
            database.execute('DELETE FROM project')
            database.execute('DELETE FROM sampleblocks')
            database.execute('INSERT INTO project VALUES(1, ?, ?)', encode_document(self.project))
            database.executemany('INSERT INTO sampleblocks VALUES(?, ?, ?)', self.rows)
            database.commit()

    def test_preserves_native_rate_stereo_padding_and_relative_gains_without_normalizing(self):
        original = self.source.read_bytes()
        result = export_tracks(self.source, self.root / 'export', {'스테레오': 'stereo.wav', '금속': 'metal.wav'})
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(result['headroom'], .5)
        with wave.open(str(self.root / 'export/stereo.wav')) as sound:
            self.assertEqual((sound.getnchannels(), sound.getframerate(), sound.getnframes()), (2, 8000, 10))
            samples = array('h', sound.readframes(10))
        self.assertEqual(samples[:16], array('h', [0] * 16))
        self.assertEqual(samples[16:], array('h', [round(v * .5 * 1.4125375446 * 32767)
                                                  for v in (.5, -.1, -.25, .3)]))
        with wave.open(str(self.root / 'export/metal.wav')) as sound:
            self.assertEqual(sound.getnchannels(), 1)
            samples = array('h', sound.readframes(2))
        self.assertEqual(samples, array('h', [round(v * .5 * .1584893192 * 32767) for v in (.8, -.5)]))

    def test_preserves_trimmed_waveform_and_visible_start(self):
        for track in self.project.findall('wavetrack')[:2]:
            track.find('waveclip').set('trimLeft', str(1 / 8000))
        self.write_database()
        tracks = read_tracks(self.source)
        self.assertAlmostEqual(tracks[0]['offset_seconds'], .001125)
        self.assertEqual(list(tracks[0]['channels'][0]), [-.25])

    def test_rejects_missing_blocks_and_unsaved_project(self):
        with closing(sqlite3.connect(self.source)) as database:
            database.execute('DELETE FROM sampleblocks WHERE blockid=1')
            database.commit()
        with self.assertRaisesRegex(ValueError, '블록'):
            read_tracks(self.source)
        self.write_database()
        with closing(sqlite3.connect(self.source)) as database:
            database.execute('INSERT INTO autosave VALUES(1)')
            database.commit()
        with self.assertRaisesRegex(ValueError, '저장하지 않은'):
            read_tracks(self.source)

    def test_rejects_effects_stretch_envelope_and_mismatched_stereo(self):
        track = self.project.find('wavetrack')
        for element, key, value in [(track.find('waveclip'), 'clipStretchRatio', '1.2'),
                                    (track.find('waveclip/envelope'), 'numpoints', '1'),
                                    (track, 'pan', '.5')]:
            previous = element.get(key)
            element.set(key, value)
            self.write_database()
            with self.assertRaises(ValueError):
                read_tracks(self.source)
            element.set(key, previous)
        ET.SubElement(track.find('effects'), 'effect', id='unsupported-plugin')
        self.write_database()
        with self.assertRaisesRegex(ValueError, '실시간 이펙트'):
            read_tracks(self.source)
        track.find('effects').clear()
        self.project.findall('wavetrack')[1].set('gain', '.1')
        self.write_database()
        with self.assertRaisesRegex(ValueError, '스테레오'):
            read_tracks(self.source)

    def test_rejects_clipping_and_escaping_names_before_creating_output(self):
        output = self.root / 'export'
        mapping = {'스테레오': 'stereo.wav', '금속': '../escape.wav'}
        with self.assertRaises(ValueError):
            export_tracks(self.source, output, mapping)
        self.assertFalse(output.exists())
        for track in self.project.findall('wavetrack')[:2]:
            track.set('gain', '8')
        self.write_database()
        with self.assertRaisesRegex(ValueError, '전체 감쇠'):
            export_tracks(self.source, output, {'스테레오': 'stereo.wav', '금속': 'metal.wav'})
        self.assertFalse(output.exists())

    def test_rejects_truncated_or_unknown_document_fields(self):
        dictionary, document = encode_document(self.project)
        for corrupted in (document[:-1], document + bytes((255,))):
            with self.assertRaises(ValueError):
                decode_document(dictionary, corrupted)


if __name__ == '__main__':
    unittest.main()
