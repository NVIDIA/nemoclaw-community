#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0

"""Build the editable UI fragment into a standalone page with a bundled 3D renderer."""
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import argparse
import subprocess
import tempfile
from app_publish import publish
from build_info import read as read_build_info

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true", help="Validate an app patch without writing to the source checkout")
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
# Validate inputs before importing the skill registry or assembling the page.
# Missing files should leave the last working build intact and identify the cause.
required = ['RELEASE_NOTES.md', 'scripts/app_publish.py', 'scripts/serve.py', 'scripts/resource_links.py', 'scripts/studio.py', 'scripts/container_runtime.py',
            'scripts/agent_runtime.py', 'scripts/role_boundaries.py', 'src/goal-examples.json', 'src/avatar-catalog.json',
            'src/assets/agent-harness-big-picture.png', 'src/assets/openshell-overview.png', 'src/assets/open-task-nemoclaw.jpg',
            'runtime/research-guard/index.mjs', 'runtime/research-guard/openclaw.plugin.json',
            'runtime/research-guard/weather/tool.mjs', 'runtime/research-guard/weather/forecast.py',
            'runtime/research-guard/weather/cities.tsv.gz']
for name in required:
    if not (ROOT / name).is_file():
        raise ValueError('Incomplete app bundle: missing ' + name)
from role_boundaries import BUILTIN_SKILL_INSTRUCTIONS, ROLE_TEMPLATES, SKILL_CATALOG
required += [f'skills/bac-{name}/SKILL.md' for name in SKILL_CATALOG if name not in BUILTIN_SKILL_INSTRUCTIONS]
required += ['scenario/' + goal['document'] for goal in json.loads((ROOT / 'src/goal-examples.json').read_text())
             if goal.get('document')]
for name in required:
    if not (ROOT / name).is_file():
        raise ValueError('Incomplete app bundle: missing ' + name)

build_info = read_build_info(ROOT)
revision = hashlib.sha256(json.dumps(build_info, sort_keys=True).encode())
revision_files = [ROOT / 'RELEASE_NOTES.md', ROOT / 'VERSION', ROOT / 'docker/runtime-lock.json',
                  ROOT / 'scripts/build.py', ROOT / 'scripts/role_boundaries.py',
                  *(path for path in (ROOT / 'src').rglob('*') if path.is_file())]
for goal in json.loads((ROOT / 'src/goal-examples.json').read_text()):
    if goal.get('document'):
        revision_files.append(ROOT / 'scenario' / goal['document'])
for path in sorted(path for path in set(revision_files) if path.is_file()):
    revision.update(str(path.relative_to(ROOT)).encode())
    revision.update(path.read_bytes())
build_info['appRevision'] = revision.hexdigest()[:16]
# Reject accidental JavaScript/file overwrites before publishing the generated page.
for stylesheet in (ROOT / 'src').glob('*.css'):
    css = re.sub(r'/\*.*?\*/', '', stylesheet.read_text(encoding='utf-8'), flags=re.S)
    if re.search(r'^\s*(?://|(?:const|let|var|function|async function|import|export)\s)', css, re.M):
        raise ValueError(f'JavaScript found in stylesheet: {stylesheet.name}')
    if not css.strip() or css.count('{') != css.count('}'):
        raise ValueError(f'Empty or unbalanced stylesheet: {stylesheet.name}')
fragment = (ROOT / 'src/bac-planner.html').read_text(encoding='utf-8')
crew_catalog = json.loads((ROOT / 'src/crew-catalog.json').read_text(encoding='utf-8'))
fragment = fragment.replace('/* CREW_CATALOG */', json.dumps(crew_catalog).replace('</', '<\\/'))
campus = (ROOT / 'src/campus.html').read_text(encoding='utf-8')
studio = (ROOT / 'src/studio.html').read_text(encoding='utf-8').replace('/* STUDIO_CSS */', (ROOT / 'src/studio.css').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/studio-rooms.css').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/studio-sound.css').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/studio-artifacts.css').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/studio-controls.css').read_text(encoding='utf-8') + '\n' + (ROOT / 'src/studio-scenarios.css').read_text(encoding='utf-8'))
campus = campus.replace('<div class="campus-layout">', studio + '\n<div class="campus-layout">')
campus = campus.replace('/* CAMPUS_CSS */', (ROOT / 'src/campus.css').read_text(encoding='utf-8'))
fragment = fragment.replace('<!-- AGENT_CAMPUS -->', campus)
vendor = (ROOT / 'src/vendor/three-r180.cjs').read_text(encoding='utf-8')
three_license = (ROOT / 'src/vendor/three-LICENSE.txt').read_text(encoding='utf-8')
vendor = '/*\n' + three_license.rstrip() + '\n*/\n' + vendor
open_task_art = 'data:image/jpeg;base64,' + base64.b64encode((ROOT / 'src/assets/open-task-nemoclaw.jpg').read_bytes()).decode('ascii')
world_scene = (ROOT / 'src/world-scene.js').read_text(encoding='utf-8').replace('__OPEN_TASK_ART_DATA_URL__', open_task_art)
stage_scenarios = json.dumps(json.loads((ROOT / 'src/stage-scenarios.json').read_text(encoding='utf-8'))).replace('</', '<\\/')
fragment = fragment.replace('/* STAGE_SCENARIOS */', stage_scenarios)
world_scene = world_scene.replace('/* AGENT_CHARACTER */', (ROOT / 'src/agent-character.js').read_text(encoding='utf-8')).replace('/* WORLD_ROOMS */', (ROOT / 'src/world-rooms.js').read_text(encoding='utf-8').replace('/* LOUNGE_LIFE */', (ROOT / 'src/world-lounge.js').read_text(encoding='utf-8'))).replace('/* WORLD_NAVIGATION */', (ROOT / 'src/world-navigation.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* WORLD_VISITOR_TRAVEL */', (ROOT / 'src/world-visitor-travel.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* WORLD_CREW_EXCHANGE */', (ROOT / 'src/world-crew-exchange.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* WORLD_SCENARIOS */', (ROOT / 'src/world-scenarios.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* WORLD_PROTECTION */', (ROOT / 'src/world-protection.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* WORLD_ROUNDTABLE */', (ROOT / 'src/world-roundtable.js').read_text(encoding='utf-8'))
world_scene = world_scene.replace('/* BUILD_VERSION */', json.dumps(build_info['version']).replace('</', '<\\/'))
world_scene = world_scene.replace('/* AVATAR_PALETTES */', json.dumps(json.loads((ROOT / 'src/avatar-catalog.json').read_text())['palettes']).replace('</', '<\\/'))
campus_js = '(function(){const exports={};\n' + vendor + '\nconst THREE=exports;\n' + (ROOT / 'src/campus.js').read_text(encoding='utf-8').replace('/* STUDIO_SOUND */', (ROOT / 'src/studio-sound.js').read_text(encoding='utf-8')).replace('/* WORLD_SCENE */', world_scene) + '\n})();'
fragment = fragment.replace('<!-- CAMPUS_SCRIPT -->', '<script>' + campus_js.replace('</script', '<\\/script') + '</script>')
studio_js = (ROOT / 'src/studio.js').read_text(encoding='utf-8')
goals = json.loads((ROOT / 'src/goal-examples.json').read_text())
for goal in goals:
    if goal.get('document'):
        goal['documentContent'] = (ROOT / 'scenario' / goal['document']).read_text()
for marker, value in [('BUILD_INFO', build_info), ('GOAL_EXAMPLES', goals)]:
    studio_js = studio_js.replace('/* ' + marker + ' */', json.dumps(value).replace('</', '<\\/'))
studio_js = studio_js.replace('/* RELEASE_NOTES */',
                              json.dumps((ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8')).replace('</', '<\\/'))
# Keep assembly explicit and fail on missing/duplicate include markers.
for module in ('json', 'compare', 'settings', 'crew', 'telemetry',
               'scenarios', 'world', 'surfaces', 'chat', 'rooms', 'identity', 'safety', 'policies', 'demo-guide', 'diagnostics'):
    marker = '/* STUDIO_' + module.upper() + ' */'
    if studio_js.count(marker) != 1:
        raise ValueError('Expected one include marker: ' + marker)
    studio_js = studio_js.replace(marker, (ROOT / ('src/studio-' + module + '.js')).read_text(encoding='utf-8'))
studio_js = studio_js.replace('/* AVATAR_CATALOG */', json.dumps(json.loads((ROOT / 'src/avatar-catalog.json').read_text())).replace('</', '<\\/'))
agent_big_picture = 'data:image/png;base64,' + base64.b64encode(
    (ROOT / 'src/assets/agent-harness-big-picture.png').read_bytes()).decode('ascii')
openshell_overview = 'data:image/png;base64,' + base64.b64encode(
    (ROOT / 'src/assets/openshell-overview.png').read_bytes()).decode('ascii')
studio_js = studio_js.replace('__AGENT_BIG_PICTURE_DATA_URL__', agent_big_picture)
studio_js = studio_js.replace('__OPENSHELL_OVERVIEW_DATA_URL__', openshell_overview)
studio_js = studio_js.replace('/* ROLE_TEMPLATES */', json.dumps(ROLE_TEMPLATES).replace('</', '<\\/'))

fragment = fragment.replace('<!-- STUDIO_SCRIPT -->', '<script>' + studio_js.replace('</script', '<\\/script') + '</script>')
fragment = fragment.replace('<!-- NVIDIA_THEME -->', '<style>\n' + (ROOT / 'src/nvidia-theme.css').read_text(encoding='utf-8') + '\n</style>')
version = build_info['version']
page = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Build your agent, explore skills, and collaborate with a team of specialists.">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; frame-src 'self' blob:; base-uri 'none'; form-action 'none'; object-src 'none'">
<title>Multi-Agent Studio</title>
<style>
:root{color-scheme:dark;background:#0c0c0c;--browser-viewport-height:100vh}
@supports(height:100dvh){:root{--browser-viewport-height:100dvh}}
body{margin:0;padding:0;width:100%;max-width:none}
</style>
</head><body>
'''+fragment+'''
<noscript>Enable JavaScript to use the interactive planner.</noscript>
</body></html>
'''
if args.check:
    # Validate the same assembled page we will serve; source modules contain
    # include markers and cannot all be checked as independent scripts.
    for source in (ROOT / 'scripts').glob('*.py'):
        compile(source.read_bytes(), str(source), 'exec')
    with tempfile.TemporaryDirectory(prefix='bac-app-check-') as folder:
        for index, script in enumerate(re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.S | re.I)):
            target = Path(folder) / f'inline-{index}.js'
            target.write_text(script, encoding='utf-8')
            subprocess.run(['node', '--check', str(target)], check=True)
        for source in (ROOT / 'scripts').glob('*.mjs'):
            subprocess.run(['node', '--check', str(source)], check=True)
    print('App files, Python and bundled JavaScript validated.')
else:
    publish(ROOT / 'app', page, build_info)
    print('Built app/index.html (bundled Three.js; no runtime downloads).')
