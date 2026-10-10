import {readdirSync} from 'node:fs'
import {spawnSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'

const folder = fileURLToPath(new URL('../../tests/', import.meta.url))
for (const file of readdirSync(folder).filter(file => /^test_.*\.mjs$/.test(file)).sort()) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(`../../tests/${file}`, import.meta.url))], {stdio: 'inherit'})
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status || 1)
}
