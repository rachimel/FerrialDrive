"""Panel geometry contracts at normal and compact editor sizes."""
import unittest
from workspace_ui import layout,DEFAULT_LAYOUT,MENUS,CURVE_CONTEXT,context_rect
import pygame


class LayoutTests(unittest.TestCase):
    def test_curve_actions_are_context_only_and_popup_stays_on_screen(self):
        self.assertEqual(set(MENUS),{'file','edit','view'})
        context_actions={item[0] for item in CURVE_CONTEXT if item}
        for _,items in MENUS.values():
            self.assertFalse(context_actions.intersection(item[0] for item in items if item))
        for size in [(1280,800),(1600,940)]:
            for point in [(0,0),(size[0]-1,size[1]-1),(-100,-100),(size[0]+100,size[1]+100)]:
                self.assertTrue(pygame.Rect(0,0,*size).contains(context_rect(size,point)))
    def test_regions_do_not_overlap_at_supported_sizes(self):
        for size in [(1280,800),(1366,900),(1600,940),(1920,1080)]:
            for settings in [DEFAULT_LAYOUT,{'left':360,'right':400,'curve':470},{'left':230,'right':288,'curve':240}]:
                with self.subTest(size=size,settings=settings):
                    parts=layout(size,settings)
                    self.assertFalse(parts['left'].colliderect(parts['center']))
                    self.assertFalse(parts['right'].colliderect(parts['center']))
                    self.assertFalse(parts['preview'].colliderect(parts['player']))
                    self.assertFalse(parts['player'].colliderect(parts['curve']))
                    self.assertTrue(parts['curve'].contains(parts['graph']))
                    self.assertTrue(parts['player'].contains(parts['timeline']))
                    self.assertGreater(parts['graph'].h,70)
                    self.assertGreaterEqual(parts['center'].w,612)
                    self.assertTrue(parts['left'].contains(parts['parts']))
                    self.assertFalse(parts['parts'].colliderect(parts['poses']))


if __name__=='__main__':unittest.main()
