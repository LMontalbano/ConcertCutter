// Charge les vrais modules TypeScript et les runes Svelte dans node:test.
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import ts from 'typescript'
import { compileModule } from 'svelte/compiler'

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith('.') && context.parentURL?.endsWith('.ts') &&
        !specifier.endsWith('.ts')) {
      return nextResolve(`${specifier}.ts`, context)
    }
    return nextResolve(specifier, context)
  },
  load(url, context, nextLoad) {
    if (!url.endsWith('.ts')) return nextLoad(url, context)
    let source = ts.transpileModule(readFileSync(new URL(url), 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
    }).outputText
    if (url.endsWith('.svelte.ts')) source = compileModule(source, { filename: url }).js.code
    return { format: 'module', source, shortCircuit: true }
  },
})
