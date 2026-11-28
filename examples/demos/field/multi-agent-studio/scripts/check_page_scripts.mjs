// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const scripts = JSON.parse(readFileSync(0, 'utf8'));
for (const [index, [type, source]] of scripts.entries()) {
  try {
    if (type === 'module') new vm.SourceTextModule(source);
    else new vm.Script(source);
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    process.stdout.write('Inline script ' + (index + 1) + ': ' + error.message.slice(0, 180));
    process.exit(2);
  }
}
