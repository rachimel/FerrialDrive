"""Ferrial Drive 실행 진입점."""

from argparse import ArgumentParser
from functools import partial

from ferrial_drive.rendering.canvas import default_game_render_driver
from ferrial_drive.runtime import run_application
from game.application import GameApplication


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="제작 에셋 없이 기본 도형으로 실행한다.")
    parser.add_argument("--mute", action="store_true", help="효과음을 끈다.")
    parser.add_argument("--frames", type=int, help="지정한 프레임 수를 표시한 후 종료한다.")
    parser.add_argument("--render-driver", choices=("opengl", "native_gl"), default=default_game_render_driver(),
                        help="기본은 직접 OpenGL이다. 비교용 SDL 렌더러는 opengl로 선택한다.")
    args = parser.parse_args()
    if args.frames is not None and args.frames < 1:
        parser.error("--frames는 양수 정수여야 한다.")
    create_game = partial(GameApplication, demo=args.demo, mute=args.mute)
    run_application(create_game, title="Ferrial Drive", frame_limit=args.frames, render_driver=args.render_driver)


if __name__ == "__main__":
    main()
