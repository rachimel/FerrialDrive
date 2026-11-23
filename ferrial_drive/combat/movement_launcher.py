"""이동·전투 독립 테스트의 공통 실행 옵션. import만으로 창을 열지 않는다."""

import argparse
from functools import partial
from pathlib import Path


def launch_movement_test(*, description, movement_speed_multiplier=1,
                         application_type=None, encounter_path=None, window_title=None, part_catalog=None,
                         settings_file=None):
    from ferrial_drive.combat.movement_application import MovementApplication
    from ferrial_drive.rendering.canvas import default_game_render_driver
    from ferrial_drive.runtime import run_application

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=root / "samples/sword_movement/movement_config.json")
    parser.add_argument("--demo", action="store_true", help="게임 에셋 없는 기본 도형 시연")
    if encounter_path is not None:
        parser.add_argument("--encounter", type=Path, default=encounter_path, help="적 종류·출현·전투 수치 JSON")
        parser.add_argument("--enemy-count", type=int, help="기본 출현 배치를 대체할 적 수")
        parser.add_argument("--enemy-spacing-m", type=float, default=12, help="부하 시험 대형의 기체 중심 간격(m)")
        parser.add_argument("--player-hp", type=int, help="교전 시작·재시작 때의 플레이어 최대 HP")
    parser.add_argument("--overdrive-rainbow", action="store_true",
                        help="오버드라이브 기체 림·검 Trail·HUD의 무지개 팔레트 시험")
    parser.add_argument("--mute", action="store_true", help="효과음 없이 실행")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--render-driver", choices=("opengl", "native_gl"), default=default_game_render_driver())
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--capture-frame", type=int, default=1)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--script", type=Path, help="60Hz 사전 지정 입력 JSON")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--settings-file", type=Path, default=settings_file, help="게임 사용자 설정 저장 경로")
    parser.add_argument("--theme-file", type=Path, help="외부 편집기와 공유할 HUD 테마 파일")
    parser.add_argument("--preview-frame", type=Path, help="외부 도구의 축소 미리보기 출력")
    parser.add_argument("--preview-control", type=Path, help="외부 도구의 시연 상태 요청")
    parser.add_argument("--preview-hidden", action="store_true", help="별도 창 대신 외부 도구에 화면 전달")
    parser.add_argument("--record-directory", type=Path, help="기체 주변의 연속 검토 이미지")
    parser.add_argument("--record-step", type=int, default=2)
    parser.add_argument("--part-catalog", type=Path, default=part_catalog, help="시험할 독립 파츠 GPU 카탈로그")
    parser.add_argument("--player-pipeline", choices=("baked", "pbr"), help="플레이어 전체의 단일 렌더 경로")
    parser.add_argument("--part-color-codec", choices=("ktx",), help="KTX2 파츠 색상 프로필 사용")
    parser.add_argument("--part-mixed", action="store_true", help="미검증 혼합 방향의 독립 파츠 합성도 비교")
    parser.add_argument("--part-step-directions", action="store_true", help="같은 파츠 아틀라스에서 방향 재투영만 끈다.")
    args = parser.parse_args()
    program_type = application_type or MovementApplication
    encounter_options = {}
    if encounter_path is not None:
        if args.player_hp is not None and args.player_hp < 1:
            parser.error("--player-hp는 양수 정수여야 한다.")
        encounter_options = dict(encounter_path=args.encounter, enemy_count=args.enemy_count,
                                 enemy_spacing_m=args.enemy_spacing_m, player_hp=args.player_hp)
    elif application_type is None and not args.demo:
        from ferrial_drive.combat.encounter_application import EncounterApplication

        program_type = EncounterApplication
        encounter_options = {"encounter_path": root / "game/training_encounter.json"}
    part_options = {"part_catalog": args.part_catalog, "part_mixed": args.part_mixed,
                    "part_step_directions": args.part_step_directions, "part_color_codec": args.part_color_codec,
                    "player_pipeline": args.player_pipeline}
    create_program = partial(program_type, args.config, demo=args.demo, capture=args.capture, capture_frame=args.capture_frame,
                                  report=args.report, script=args.script, profile=args.profile,
                                  record_directory=args.record_directory, record_step=args.record_step,
                                  settings_file=args.settings_file, movement_speed_multiplier=movement_speed_multiplier,
                                  mute=args.mute, theme_file=args.theme_file, preview_frame=args.preview_frame,
                                  preview_control=args.preview_control, preview_hidden=args.preview_hidden,
                                  overdrive_rainbow=args.overdrive_rainbow, **part_options, **encounter_options)
    title = window_title or "Ferrial Drive | 이동·전투·UI V2"
    if args.overdrive_rainbow:
        title += " | Rainbow Overdrive"
    if movement_speed_multiplier != 1:
        title += f" | {movement_speed_multiplier:g}x Speed"
    run_application(create_program, title=title, frame_limit=args.frames, render_driver=args.render_driver)
