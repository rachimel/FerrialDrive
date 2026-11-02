"""Start the upstream Blender MCP addon for the current asset pipeline.

No user preferences or Codex configuration are changed. Run in a separate
Blender instance with --factory-startup --python this_file.
"""
from pathlib import Path
import importlib.util
import sys
import bpy

ROOT = Path(__file__).resolve().parents[2]
addon_path = ROOT / '.venv-capability-test/Lib/site-packages/blender_mcp/bundled/addon.py'
spec = importlib.util.spec_from_file_location('capability_blender_mcp', addon_path)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
bpy.context.scene.blendermcp_port = 9876
server = addon.BlenderMCPServer(host='127.0.0.1', port=9876)
bpy.types.blendermcp_server = server
server.start()
bpy.context.scene.blendermcp_server_running = True
print('CAPABILITY_MCP_READY', flush=True)
