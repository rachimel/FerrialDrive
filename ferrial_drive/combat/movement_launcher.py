"""이동·전투 독립 테스트의 공통 실행 옵션. import만으로 창을 열지 않는다."""

import argparse
from pathlib import Path


def launch_movement_test(*, description, movement_speed_multiplier=1, overdrive_rainbow=False,
                         application_type=None, encounter_path=None, window_title=None):
    from ferrial_drive.combat.movement_application import MovementApplication
    from ferrial_drive.runtime import run_application

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, default=root / "samples/sword_movement/movement_config.json")
    parser.add_argument("--demo", action="store_true", help="게임 에셋 없는 기본 도형 시연")
    if encounter_path is not None:
        parser.add_argument("--encounter", type=Path, default=encounter_path, help="적 종류·출현·전투 수치 JSON")
    parser.add_argument("--overdrive-rainbow", action=argparse.BooleanOptionalAction, default=overdrive_rainbow,
                        help="오버드라이브 기체 림·검 Trail·HUD의 무지개 팔레트 시험")
    parser.add_argument("--mute", action="store_true", help="효과음 없이 실행")
    parser.add_argument("--frames", type=int)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--capture-frame", type=int, default=1)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--script", type=Path, help="60Hz 사전 지정 입력 JSON")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--settings-file", type=Path, help="게임 사용자 설정 저장 경로")
    parser.add_argument("--theme-file", type=Path, help="외부 편집기와 공유할 HUD 테마 파일")
    parser.add_argument("--preview-frame", type=Path, help="외부 도구의 축소 미리보기 출력")
    parser.add_argument("--preview-control", type=Path, help="외부 도구의 시연 상태 요청")
    parser.add_argument("--preview-hidden", action="store_true", help="별도 창 대신 외부 도구에 화면 전달")
    parser.add_argument("--record-directory", type=Path, help="기체 주변의 연속 검토 이미지")
    parser.add_argument("--record-step", type=int, default=2)
    args = parser.parse_args()
    program_type = application_type or MovementApplication
    encounter_options = {"encounter_path": args.encounter} if encounter_path is not None else {}
    program = program_type(args.config, demo=args.demo, capture=args.capture, capture_frame=args.capture_frame,
                                  report=args.report, script=args.script, profile=args.profile,
                                  record_directory=args.record_directory, record_step=args.record_step,
                                  settings_file=args.settings_file, movement_speed_multiplier=movement_speed_multiplier,
                                  mute=args.mute, theme_file=args.theme_file, preview_frame=args.preview_frame,
                                  preview_control=args.preview_control, preview_hidden=args.preview_hidden,
                                  overdrive_rainbow=args.overdrive_rainbow, **encounter_options)
    title = window_title or "Ferrial Drive | 이동·전투·UI V2"
    if args.overdrive_rainbow:
        title += " | Rainbow Overdrive"
    if movement_speed_multiplier != 1:
        title += f" | {movement_speed_multiplier:g}x Speed"
    run_application(program, width=program.window_size[0], height=program.window_size[1],
                    title=title, frame_limit=args.frames, timings=program.timings)
