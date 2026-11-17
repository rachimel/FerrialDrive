"""효과음 사건 중복·타이밍·채널 상한·장치 실패와 WAV 형식을 검사한다."""

from pathlib import Path
from copy import deepcopy
from dataclasses import replace
import json
import os
from math import cos, log10, pi, sin, sqrt
from random import Random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings
import wave

from automate.sound_effects import SAMPLE_RATE, process_samples, write_wav
from ferrial_drive.audio.effects import PicoSoundEffects, convert_playback_rate
from ferrial_drive.audio.processing import continuous_friction, diffuse_tail, focused_whoosh, layered_burst
from ferrial_drive.combat.movement_audio import MovementSoundCues
from ferrial_drive.combat.movement_combat import AttackStep


ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "samples/sound_effects/sound_bank.json"


class SoundCueTests(unittest.TestCase):
    def setUp(self):
        self.player = Mock()
        self.cues = MovementSoundCues(self.player, [[0.3, 0.8]] * 4, easing="linear")
        self.controller = SimpleNamespace(boost_remaining_seconds=0)

    def step(self, start, end, strike_id=1, clip="combo_01/e"):
        return AttackStep(strike_id, clip, start, end, 1, end-start, (0, 0), (0, 0))

    def test_swing_waits_for_active_window_and_plays_once_per_strike(self):
        self.cues.update(0.2, self.controller, [self.step(0, 0.2)], [])
        self.player.play.assert_not_called()
        self.cues.update(0.2, self.controller, [self.step(0.2, 0.4)], [])
        self.cues.update(0.2, self.controller, [self.step(0.4, 0.6)], [])
        self.player.play.assert_called_once_with("swing_1", energy_level=1)
        self.cues.update(0.5, self.controller, [self.step(0, 0.5, 2, "combo_02/e")], [])
        self.assertEqual(self.player.play.call_count, 2)

    def test_skipped_windows_and_multiple_attacks_in_one_frame_are_preserved(self):
        self.cues.update(1, self.controller,
            [self.step(0, 1), self.step(0, 0.7, 2, "combo_04/e")], [(1, "A"), (1, "B")])
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list],
                         ["swing_1", "swing_4", "hit"])

    def test_boost_preparation_is_silent_and_finished_boost_still_plays(self):
        self.cues.update(0.01, self.controller, [], [], prepare_before_seconds=0.08)
        self.player.play.assert_not_called()
        self.cues.update(0.4, self.controller, [], [], prepare_before_seconds=0.07)
        self.player.play.assert_called_once_with("boost")

    def test_zero_preparation_boost_and_reset(self):
        self.controller.boost_remaining_seconds = 0.2
        self.cues.update(0.01, self.controller, [], [])
        self.cues.update(0.01, self.controller, [], [])
        self.player.play.assert_called_once_with("boost")
        self.cues.reset()
        self.cues.update(0.01, self.controller, [self.step(0, 0.5)], [])
        self.assertEqual(self.player.play.call_count, 3)

    def test_normal_attack_footstep_plays_once_before_swing_and_resets(self):
        motion = json.loads(BANK.read_text(encoding="utf-8"))["motion"]
        cues = MovementSoundCues(self.player, [[.3, .8]] * 4, easing="linear", motion=motion)
        cues.update(.1, self.controller, [self.step(0, .1)], [])
        self.player.play.assert_not_called()
        cues.update(.1, self.controller, [self.step(.1, .2)], [])
        self.player.play.assert_called_once_with("step", gain=.3)
        cues.update(.2, self.controller, [self.step(.2, .4)], [])
        cues.update(.1, self.controller, [self.step(.4, .5)], [])
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list], ["step", "swing_1"])
        cues.reset()
        self.player.reset_mock()
        cues.update(.4, self.controller, [self.step(0, .4)], [])
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list], ["step", "swing_1"])

    def test_attack_steps_crossed_in_one_frame_play_for_each_grounded_strike(self):
        motion = json.loads(BANK.read_text(encoding="utf-8"))["motion"]
        cues = MovementSoundCues(self.player, [[.3, .8]] * 4, easing="linear", motion=motion)
        cues.update(.8, self.controller, [self.step(0, .5, 1), self.step(0, .5, 2, "combo_02/e")], [])
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list],
                         ["step", "swing_1", "step", "swing_2"])

    def test_sliding_and_boosted_strikes_do_not_emit_delayed_footsteps(self):
        motion = json.loads(BANK.read_text(encoding="utf-8"))["motion"]
        cues = MovementSoundCues(self.player, [[.3, .8]] * 4, easing="linear", motion=motion)
        for name in ("dash", "boosting"):
            cues.reset()
            self.player.reset_mock()
            cues.update(.25, self.controller, [replace(self.step(0, .25), **{name: True})], [])
            cues.update(.25, self.controller, [self.step(.25, .5)], [])
            self.assertEqual([call.args[0] for call in self.player.play.call_args_list], ["swing_1"])

    def test_run_contacts_follow_animation_phase_and_scrape_has_sparse_debris(self):
        for phase in (0.1, 0.2, 0.6, 0.7):
            self.cues.update(0.016, self.controller, [], [], run_phase=phase)
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list], ["step", "step"])
        self.player.reset_mock()
        self.cues.update(0.016, self.controller, [], [], scraping=True)
        self.cues.update(0.016, self.controller, [], [], scraping=True)
        self.player.play.assert_called_once_with("pebble")
        self.player.set_loop.assert_called_with("scrape", True, gain=1)
        self.cues.update(0.01, self.controller, [], [])
        self.player.set_loop.assert_called_with("scrape", False, gain=1)

    def test_swing_and_hit_receive_current_energy_level(self):
        self.cues.update(0.5, self.controller, [self.step(0, 0.5)], [(1, "A")], energy_level=3)
        self.assertEqual([call.kwargs for call in self.player.play.call_args_list],
                         [{"energy_level": 3}, {"energy_level": 3}])

    def test_dash_scrape_gain_restores_without_affecting_other_scraping(self):
        motion = json.loads(BANK.read_text(encoding="utf-8"))["motion"]
        cues = MovementSoundCues(self.player, [[.3, .8]] * 4, motion=motion)
        cues.update(.01, self.controller, [], [], scraping=True, dashing=True)
        self.player.set_loop.assert_called_with("scrape", True, gain=.85)
        cues.update(.01, self.controller, [], [], scraping=True, dashing=False)
        self.player.set_loop.assert_called_with("scrape", True, gain=1)
        self.controller.boost_remaining_seconds = .2
        cues.update(.01, self.controller, [], [], scraping=True, dashing=True)
        self.player.set_loop.assert_called_with("scrape", True, gain=1)

    def test_contact_sound_requires_hit_and_metal_scrape_requires_metal_target(self):
        self.cues.update(.01, self.controller, [], [], hit_materials={"A":"metal"})
        self.player.play.assert_not_called()
        self.cues.update(.1, self.controller, [], [(1,"B")], hit_materials={"A":"metal", "B":"generic"})
        self.player.play.assert_called_once_with("hit", energy_level=1)
        self.player.reset_mock()
        self.cues.update(.1, self.controller, [], [(1,"A"), (1,"B")], hit_materials={"A":"metal"})
        self.assertEqual([call.args[0] for call in self.player.play.call_args_list], ["hit", "hit_metal"])

    def test_dash_turbine_stops_during_boost_and_preparation(self):
        self.cues.update(.01, self.controller, [], [], dashing=True, scraping=True)
        self.assertIn(unittest.mock.call("dash_jet", True), self.player.set_loop.call_args_list)
        self.player.reset_mock()
        self.cues.update(.01, self.controller, [], [], dashing=True, prepare_before_seconds=.08)
        self.assertIn(unittest.mock.call("dash_jet", False), self.player.set_loop.call_args_list)
        self.controller.boost_remaining_seconds = .2
        self.player.reset_mock()
        self.cues.update(.01, self.controller, [], [], dashing=True)
        self.assertIn(unittest.mock.call("dash_jet", False), self.player.set_loop.call_args_list)

    def test_complete_metal_mix_replaces_base_hit_without_affecting_generic_contacts(self):
        self.player.bank = {"hit_metal": {"replaces_hit": True}}
        cues = MovementSoundCues(self.player, [[.3, .8]] * 4)
        cues.update(.1, self.controller, [], [(1, "A")], energy_level=3, hit_materials={"A": "metal"})
        self.player.play.assert_called_once_with("hit_metal", energy_level=3)
        self.player.reset_mock()
        cues.update(.1, self.controller, [], [(1, "B")], hit_materials={"B": "generic"})
        self.player.play.assert_called_once_with("hit", energy_level=1)
        self.player.reset_mock()
        cues.update(.1, self.controller, [], [(1, "A"), (1, "B")], hit_materials={"A": "metal"})
        self.player.play.assert_called_once_with("hit_metal", energy_level=1)

    def test_dash_ignition_plays_once_per_entry_and_restarts_after_leaving(self):
        for _ in range(5):
            self.cues.update(.016,self.controller,[],[],dashing=True)
        self.player.play.assert_called_once_with("dash_ignite")
        self.cues.update(.016,self.controller,[],[],dashing=False)
        self.cues.update(.016,self.controller,[],[],dashing=True)
        self.assertEqual(self.player.play.call_count,2)
        self.cues.reset()
        self.player.reset_mock()
        self.cues.update(.016,self.controller,[],[],dashing=True)
        self.player.play.assert_called_once_with("dash_ignite")


class SoundPlayerTests(unittest.TestCase):
    def test_event_can_keep_original_pitch_while_other_events_follow_overdrive(self):
        player = self.player
        sample = next(iter(player.sounds))
        for name, follow in (('fixed_explosion', False), ('scaled_hit', True)):
            player.bank[name] = {'follow_rate_multiplier': follow,
                                 'layers': [{'files': [sample], 'volume': .4}]}
        player.set_rate_multiplier(1.1)
        with patch('ferrial_drive.audio.effects.convert_playback_rate',
                   wraps=convert_playback_rate) as convert:
            self.assertTrue(player.play('fixed_explosion'))
            convert.assert_not_called()
            self.assertTrue(player.play('scaled_hit'))
            self.assertAlmostEqual(convert.call_args.args[2], 1.1)

    def setUp(self):
        import pico2d.pico2d as pico
        self.pico = pico
        self.environment = patch.dict(os.environ, SDL_AUDIODRIVER="dummy")
        self.environment.start()
        pico.SDL_Init(pico.SDL_INIT_AUDIO)
        self.assertEqual(pico.Mix_OpenAudio(SAMPLE_RATE, pico.AUDIO_S16SYS, 2, 1024), 0)
        pico.audio_on = True
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        bank = json.loads(BANK.read_text(encoding="utf-8"))["events"]
        for name in {name for row in bank.values() for layer in row["layers"] for name in layer["files"]}:
            # 공개 가능한 고정 신호로 자원 수명·재생률만 검사한다.
            write_wav(self.directory / name, [((i % 32)/32-0.5)*0.2 for i in range(8820)])
        self.player = PicoSoundEffects(pico, BANK, self.directory)

    def tearDown(self):
        self.player.close()
        self.pico.Mix_CloseAudio()
        self.pico.SDL_QuitSubSystem(self.pico.SDL_INIT_AUDIO)
        self.temporary.cleanup()
        self.environment.stop()

    def test_channel_limit_cooldown_and_owned_channel_cleanup(self):
        pico, player = self.pico, self.player
        self.assertTrue(player.play("hit"))
        self.assertFalse(player.play("hit"))
        player.update(0.07)
        self.assertTrue(player.play("hit"))
        while player.play("swing_1"):
            pass
        self.assertFalse(player.play("swing_1"))
        channels = player.channels
        player.close()
        self.assertTrue(all(not pico.Mix_Playing(channel) for channel in channels))
        self.assertEqual(pico.Mix_AllocateChannels(-1), channels[0])
        self.assertFalse(player.play("hit"))
        self.assertFalse(player.sounds)

    def test_device_and_missing_asset_failures_leave_game_running(self):
        pico = self.pico
        pico.audio_on = False
        with warnings.catch_warnings(record=True) as emitted:
            player = PicoSoundEffects(pico, BANK, ROOT)
        self.assertTrue(emitted)
        self.assertFalse(player.play("boost"))
        pico.audio_on = True
        with warnings.catch_warnings(record=True):
            player = PicoSoundEffects(pico, BANK, ROOT)
        self.assertTrue(player.disabled_reason)
        self.assertEqual(player.channels, ())

    def test_level_layers_are_mixed_from_same_samples_and_rate_is_converted_in_memory(self):
        player = self.player
        self.assertTrue(player.play("swing_1", energy_level=1))
        self.assertNotIn("energy_swing.wav", player.layer_counts)
        self.assertTrue(player.play("swing_1", energy_level=2))
        self.assertEqual(player.layer_counts["energy_swing.wav"], 1)
        self.assertTrue(player.play("swing_1", energy_level=3))
        self.assertEqual(player.layer_counts["energy_swing.wav"], 2)
        converted = [voice for voice in player.voices.values() if voice["chunk"] is not None]
        self.assertTrue(any(voice["chunk"].contents.alen < len(player.pcm["energy_swing.wav"])*0.85 for voice in converted))
        self.assertTrue(all(voice["memory"] is not None for voice in converted))
        player.stop()
        self.assertEqual(player.voices, {})

    def test_scrape_loop_stays_alive_without_restart_and_stops_with_owned_channels(self):
        player = self.player
        for _ in range(4):
            player.set_loop("scrape", True)
        self.assertEqual(player.play_counts["scrape"], 1)
        self.assertTrue(player.voices)
        self.assertTrue(all(voice["loop"] for voice in player.voices.values()))
        player.set_loop("scrape", False)
        self.assertFalse(any(voice["loop"] for voice in player.voices.values()))
        player.stop()
        self.assertFalse(player.voices)

    def test_five_overlapping_four_layer_hits_keep_all_layers(self):
        player = self.player
        sample = next(iter(player.sounds))
        player.bank['four_layer_hit'] = {'layers': [{'files': [sample], 'volume': .1} for _ in range(4)]}
        for _ in range(5):
            self.assertTrue(player.play('four_layer_hit'))
        self.assertEqual(player.dropped_layers, 0)
        self.assertEqual(player.layer_counts[sample], 20)

    def test_overdrive_rate_restarts_loop_once_and_restores_normal_rate(self):
        player = self.player
        player.set_loop("scrape", True)
        player.set_rate_multiplier(1.1)
        player.set_loop("scrape", True)
        self.assertEqual(player.play_counts["scrape"], 2)
        self.assertTrue(any(voice["chunk"] is not None for voice in player.voices.values()))
        player.set_rate_multiplier(1.1)
        player.set_loop("scrape", True)
        self.assertEqual(player.play_counts["scrape"], 2)
        player.set_rate_multiplier(1)
        player.set_loop("scrape", True)
        self.assertEqual(player.play_counts["scrape"], 3)

    def test_user_bank_replaces_dry_swings_and_adds_events_without_required_game_assets(self):
        names = ["chosen_1.wav", "chosen_2.wav"]
        for name in names:
            write_wav(self.directory / name, [0.1] * 4410)
        overlay = self.directory / "bank.json"
        overlay.write_text(json.dumps({"files": {name: name for name in names},
            "replace_files": {"swing_air.wav": names, "swing_thrust.wav": names},
            "events": {"counter": {"layers": [{"files": [names[0]]}]}}}), encoding="utf-8")
        player = PicoSoundEffects(self.pico, BANK, self.directory, user_bank=overlay)
        try:
            self.assertNotIn("swing_air.wav", player.sounds)
            player.play("swing_1")
            player.play("swing_1")
            self.assertTrue(all(player.layer_counts[name] == 1 for name in names))
            self.assertTrue(player.play("counter"))
        finally:
            player.close()

    def test_processing_outputs_finite_faded_pcm_with_headroom(self):
        random = Random(22)
        source = [random.uniform(-0.5, 0.5) for _ in range(22050)]
        recipes = json.loads((ROOT / "samples/sound_effects/processing.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            for name, row in recipes.items():
                if row.get("processor"):
                    continue
                samples = process_samples(source, row)
                if not row.get("loop"):
                    self.assertEqual(len(samples), round(row["duration_seconds"] * SAMPLE_RATE))
                    self.assertEqual(samples[0], 0)
                    self.assertEqual(samples[-1], 0)
                self.assertLessEqual(max(abs(value) for value in samples), 0.580001)
                path = Path(temporary) / f"{name}.wav"
                write_wav(path, samples)
                with wave.open(str(path)) as wav_source:
                    self.assertEqual((wav_source.getnchannels(), wav_source.getsampwidth(), wav_source.getframerate()),
                                     (1, 2, SAMPLE_RATE))


class SoundActionIntegrationTests(unittest.TestCase):
    def setUp(self):
        from ferrial_drive.combat.movement_application import MovementApplication
        from ferrial_drive.ui_v2.movement_hud import MovementHud
        self.app = MovementApplication(ROOT / "samples/sword_movement/movement_config.json", demo=True)
        self.app.hud = MovementHud(ROOT / "samples/ui_unit_test_v2/ui_config.json",
                                   ROOT / "samples/ui_unit_test_v2/hud_sample.json")
        self.app.sound_player = Mock()

    def test_counter_activation_is_audible_once_and_deactivation_is_silent(self):
        self.app.perform_hud_action("counter")
        self.app.perform_hud_action("counter")
        self.app.sound_player.play.assert_called_once_with("counter")

    def test_ultimate_requires_readiness_and_does_not_replay_during_cooldown(self):
        self.app.perform_hud_action("ultimate")
        self.app.sound_player.play.assert_not_called()
        self.app.set_energy_level(3)
        self.app.perform_hud_action("ultimate")
        self.app.perform_hud_action("ultimate")
        self.app.sound_player.play.assert_called_once_with("ultimate")

    def test_pause_stops_audio_and_reset_resets_cues(self):
        self.app.paused = True
        self.app.update(0.1)
        self.app.sound_player.stop.assert_called_once()
        self.app.playback = Mock()
        self.app.sound_cues = Mock()
        self.app.reset()
        self.app.sound_cues.reset.assert_called_once()


class SoundProcessingTests(unittest.TestCase):
    def test_burst_varispeed_rises_continuously_without_shifting_layer_duration(self):
        source = [sin(2*pi*500*i/SAMPLE_RATE) for i in range(SAMPLE_RATE//2)]
        recipe = {"duration_seconds": .4, "layers": [
            {"source_index":0,"source_start_seconds":0,"source_end_seconds":.4,
             "duration_seconds":.4,"gain":1,"rate_start":.75,"rate_end":1.25,
             "attack_seconds":.002,"hold_seconds":.4,"decay_seconds":1,
             "highpass_hz":50,"lowpass_hz":6000}]}
        result = layered_burst([source], SAMPLE_RATE, recipe)
        def crossings(start, end):
            values = result[round(start*SAMPLE_RATE):round(end*SAMPLE_RATE)]
            return sum(a < 0 <= b for a,b in zip(values,values[1:]))
        self.assertEqual(len(result), round(.4*SAMPLE_RATE))
        self.assertGreater(crossings(.28,.36), crossings(.04,.12)*1.25)

    def test_layered_burst_preserves_headroom_and_adds_a_decaying_tail(self):
        random = Random(57)
        source = [random.uniform(-.6, .6) for _ in range(SAMPLE_RATE // 2)]
        recipe = {"duration_seconds": .3, "peak": .74, "layers": [
            {"source_index": 0, "source_start_seconds": 0, "source_end_seconds": .25,
             "duration_seconds": .2, "offset_seconds": .015, "gain": 1,
             "attack_seconds": .004, "hold_seconds": .035, "decay_seconds": .04,
             "highpass_hz": 180, "lowpass_hz": 5500}],
            "reverb": {"duration_seconds": .25, "pre_delay_seconds": .02, "taps": 12,
                       "wet": .4, "damping_hz": 3200}}
        result = layered_burst([source], SAMPLE_RATE, recipe)
        self.assertEqual(len(result), round(.3 * SAMPLE_RATE) + round(.25 * SAMPLE_RATE))
        self.assertAlmostEqual(max(map(abs, result)), .74)
        self.assertEqual(result[:round(.015 * SAMPLE_RATE)], [0] * round(.015 * SAMPLE_RATE))
        self.assertEqual(result[-1], 0)
        energy = lambda low, high: sum(v*v for v in result[round(low*SAMPLE_RATE):round(high*SAMPLE_RATE)])
        self.assertGreater(energy(.3, .45), 0)
        self.assertLess(energy(.3, .45), energy(.03, .18))
        self.assertEqual(result, layered_burst([source], SAMPLE_RATE, recipe))

    def test_layered_burst_checks_layer_bounds_and_rejects_silent_sources(self):
        source = [.1, -.1] * 500
        recipe = {"duration_seconds": .1, "layers": [
            {"source_index": 0, "source_start_seconds": 0, "source_end_seconds": .02,
             "duration_seconds": .05, "offset_seconds": 0, "gain": 1,
             "attack_seconds": .002, "hold_seconds": .01, "decay_seconds": .01,
             "highpass_hz": 200, "lowpass_hz": 4000}]}
        for changes in ({"offset_seconds": .08}, {"source_end_seconds": 1}, {"attack_seconds": 0}):
            invalid = deepcopy(recipe)
            invalid["layers"][0].update(changes)
            with self.assertRaises(ValueError):
                layered_burst([source], SAMPLE_RATE, invalid)
        with self.assertRaises(ValueError):
            layered_burst([[0] * 1000], SAMPLE_RATE, recipe)

    def test_whoosh_keeps_core_and_rejects_high_frequency_hiss(self):
        recipe = json.loads((ROOT / "samples/sound_effects/boost_processing.json").read_text(encoding="utf-8"))
        recipe.update(focus_start_hz=3000, focus_end_hz=3000)
        recipe.pop("reverb", None)
        source = [0.3*sin(2*pi*3000*i/SAMPLE_RATE) + 0.3*sin(2*pi*9000*i/SAMPLE_RATE) for i in range(SAMPLE_RATE)]
        result = focused_whoosh(source, SAMPLE_RATE, recipe)

        def amplitude(frequency):
            real = sum(v*cos(2*pi*frequency*i/SAMPLE_RATE) for i,v in enumerate(result))
            imaginary = sum(v*sin(2*pi*frequency*i/SAMPLE_RATE) for i,v in enumerate(result))
            return 2*sqrt(real*real+imaginary*imaginary)/len(result)

        self.assertEqual(len(result), round((recipe["end_seconds"]-recipe["start_seconds"])*SAMPLE_RATE))
        self.assertGreater(amplitude(3000), 0.03)
        self.assertLess(amplitude(9000)/amplitude(3000), 0.12)
        self.assertEqual((result[0], result[-1]), (0, 0))

    def test_circular_friction_has_no_empty_edges_or_rhythmic_volume_drop(self):
        random = Random(19)
        sources = [[random.uniform(-1,1)*(0.1+0.8*abs(sin(i/730))) for i in range(SAMPLE_RATE)] for _ in range(3)]
        recipe = json.loads((ROOT / "samples/sound_effects/processing.json").read_text(encoding="utf-8"))["ski_slide"]
        result = continuous_friction(sources, SAMPLE_RATE, recipe)
        hop = round(SAMPLE_RATE*0.1)
        rms = [sqrt(sum(v*v for v in result[i:i+hop])/len(result[i:i+hop])) for i in range(0,len(result),hop)]
        self.assertLess(20*log10(max(rms)/min(rms)), 4)
        self.assertGreater(min(rms), 0.01)
        delta_rms = sqrt(sum((b-a)**2 for a,b in zip(result,result[1:]))/(len(result)-1))
        self.assertLess(abs(result[-1]-result[0]), delta_rms*5)

    def test_reverb_preserves_start_and_adds_fading_non_looping_tail(self):
        recipe = json.loads((ROOT / "samples/sound_effects/boost_processing.json").read_text(encoding="utf-8"))["reverb"]
        source = [0.6] + [0.0]*2204
        result = diffuse_tail(source, SAMPLE_RATE, recipe)
        self.assertEqual(result[0], source[0])
        self.assertEqual(len(result), len(source)+round(recipe["duration_seconds"]*SAMPLE_RATE))
        self.assertGreater(sum(v*v for v in result[len(source):]), 0)
        self.assertLess(sum(v*v for v in result[-4410:]), sum(v*v for v in result[4410:8820]))
        self.assertEqual(result[-1], 0)


if __name__ == "__main__":
    unittest.main()
