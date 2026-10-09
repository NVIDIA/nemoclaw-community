# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gateway_compat", ROOT / "scripts/prepare-brev-gateway-compat.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def launcher(compiled=False):
    fs_name = "node_fs_1.default" if compiled else "fs"
    return '''function build(options) {
  const env = {};
  const dockerSocket = "/var/run/docker.sock";
  const containerName = "test-gateway";
  const args = [
    "run", "--rm", "--name", containerName,
    "--network", "host", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
  ];
  if (FS.existsSync(dockerSocket)) args.push("--volume", dockerSocket + ":" + dockerSocket + ":ro");
  return {args, env};
}'''.replace("FS", fs_name)


class GatewayCompatibilityTest(unittest.TestCase):
    def test_host_identity_and_persistent_state_reach_container(self):
        for compiled in (False, True):
            with self.subTest(compiled=compiled):
                text = module.patched_launcher(launcher(compiled), compiled)
                self.assertEqual(module.patched_launcher(text, compiled), text)
                # Execute the resulting launcher: addEnv only passes the variable
                # name, so setting its value in the child environment is essential.
                program = '''
const vm = require('node:vm');
const fixture = JSON.parse(process.argv[1]);
const fs = {existsSync:()=>true,statSync:()=>({gid:121})};
const context = {fs,node_fs_1:{default:fs},process:{getuid:()=>1000,getgid:()=>1000},
  addEnv:(args,key,value)=>{if(typeof value==='string')args.push('--env',key);}};
vm.createContext(context);
vm.runInContext(fixture,context);
console.log(JSON.stringify(context.build({stateDir:'/private/gateway'})));
'''
                result = subprocess.run(["node", "-e", program, json.dumps(text)], check=True, capture_output=True, text=True)
                built = json.loads(result.stdout)
                args = built["args"]
                for flag, value in (("--user", "1000:1000"), ("--group-add", "121"),
                                    ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"),
                                    ("--env", "XDG_STATE_HOME")):
                    self.assertEqual(args[args.index(flag) + 1], value)
                self.assertEqual(built["env"]["XDG_STATE_HOME"], "/private/gateway")

    def test_changed_or_duplicate_launcher_is_rejected(self):
        for text in (launcher().replace('"ALL"', '"NET_RAW"'), launcher() + launcher()):
            with self.assertRaises(ValueError):
                module.patched_launcher(text, False)

    def test_partial_patch_is_rejected(self):
        text = module.patched_launcher(launcher(), False)
        with self.assertRaises(ValueError):
            module.patched_launcher(text.replace('env.XDG_STATE_HOME = options.stateDir;', ''), False)

    def test_invalid_compiled_file_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "src/lib/onboard/docker-driver-gateway-compat.ts"
            compiled = root / "dist/lib/onboard/docker-driver-gateway-compat.js"
            source.parent.mkdir(parents=True)
            compiled.parent.mkdir(parents=True)
            source.write_text(launcher())
            compiled.write_text("unknown runtime")
            with self.assertRaises(ValueError):
                module.prepare(root)
            self.assertEqual(source.read_text(), launcher())


if __name__ == "__main__":
    unittest.main()
