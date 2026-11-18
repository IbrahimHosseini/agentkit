// Empty streaming input keeps initialization available without a user turn.
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
export async function discover(query, executable, cwd) {
  let release;
  const done = new Promise(resolve => { release = resolve; });
  async function* emptyInput() { await done; }
  const session = query({prompt: emptyInput(), options: {
    pathToClaudeCodeExecutable: executable, cwd, persistSession: false,
    settingSources: [], settings: {disableAllHooks: true, syncClaudeAiSkills: false,
      syncClaudeAiPlugins: false}, hooks: {}, mcpServers: {}, strictMcpConfig: true,
    plugins: [], tools: [], permissionMode: 'default',
    canUseTool: async () => ({behavior: 'deny', message: 'Catalog discovery only'})
  }});
  try {
    const initialized = await session.initializationResult();
    return typeof session.supportedModels === 'function'
      ? await session.supportedModels() : initialized.models;
  } finally { release(); session.close(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const {query} = await import(pathToFileURL(join(process.argv[2], 'node_modules',
      '@anthropic-ai', 'claude-agent-sdk', 'sdk.mjs')).href);
    const rows = await discover(query, process.argv[3], process.argv[4]);
    process.stdout.write(JSON.stringify(rows));
  } catch { process.stderr.write('Claude SDK initialization failed; check CLI login and version.\n'); process.exitCode = 1; }
}
