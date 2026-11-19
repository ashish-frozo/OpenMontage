import {build} from 'esbuild';
await build({entryPoints:['src.js'],outfile:'dist/runtime.js',bundle:true,define:{global:'globalThis'},format:'iife',platform:'browser'});
