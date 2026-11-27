// SPDX-License-Identifier: Apache-2.0
import {execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';

const run = promisify(execFile);
const file = fileURLToPath(new URL('./forecast.py', import.meta.url));

export function weatherTool(ctx) {
  function permitted() {
    const config = ctx.getRuntimeConfig?.() ?? ctx.runtimeConfig ?? ctx.config;
    const agent = config?.agents?.entries?.[ctx.agentId];
    return !ctx.sandboxed && agent?.sandbox?.mode === 'off' && agent.tools?.allow?.includes('bac_weather');
  }
  if (!permitted()) return null;
  return {
    name: 'bac_weather', label: 'MET Norway weather forecast',
    description: 'Find a city offline and get its MET Norway forecast. Use the location as the user wrote it. Most prominent namesakes resolve automatically. Only add country or region if specified. Ask the user when the tool returns ambiguous.',
    parameters: {type:'object', additionalProperties:false, required:['city'], properties:{
      city:{type:'string',minLength:1,maxLength:120}, country:{type:'string',description:'Country name or ISO code if specified.',maxLength:100},
      region:{type:'string',description:'Region name or code if specified.',maxLength:100}, days:{type:'integer',minimum:1,maximum:10}
    }},
    async execute(_id, args, signal) {
      if (!permitted()) throw Error('Weather tool unavailable for this agent.');
      const argv = ['-I', file, '--days', String(args.days ?? 4)];
      if (args.country) argv.push('--country', args.country);
      if (args.region) argv.push('--region', args.region);
      argv.push('--', args.city);
      try {
        const {stdout} = await run('python3', argv, {signal, timeout:25000, maxBuffer:65536});
        return {content:[{type:'text',text:stdout.trim()}], details:{}};
      } catch (error) {
        throw Error(error.stderr?.trim().slice(0,300) || 'Weather lookup unavailable.');
      }
    }
  };
}
