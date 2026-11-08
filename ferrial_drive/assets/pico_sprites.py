"""독립 테스트도 게임과 같은 공통 에셋 표시 경로를 사용한다."""

from .catalog import AssetDefinition, AssetDocument
from .pico_assets import PicoAssetResource
from .pico_opacity import DEFAULT_SHADOW_OPACITY


class PicoSprite:
    def __init__(self, bundle, *, filtering='bicubic'):
        self.bundle = bundle
        document = AssetDocument(AssetDefinition('legacy_sprite', 'bundle', bundle.body.image_path),
            {'body': bundle.body, 'shadow': bundle.shadow}, (bundle.body.image_path, bundle.shadow.image_path),
            bundle.asset_id, next(iter(bundle.directions.values())))
        self.resource = PicoAssetResource(document, filtering=filtering)
        self.pico, self.textures = self.resource.pico, self.resource.textures

    def draw(self, direction, frame_index, x, y, *, scale=1.0, body=True, shadow=True,
             shadow_opacity=DEFAULT_SHADOW_OPACITY):
        self.resource.draw(self.bundle.directions[direction], frame_index, x, y,
                           scale=scale, body=body, shadow=shadow, shadow_opacity=shadow_opacity)

    def render_batch(self):
        return self.resource.render_batch()

    def close(self):
        self.resource.close()
