import assert from 'node:assert/strict';
import {discover} from './discover.mjs';
let closed = false;
let options;
let next;
const rows = [{value: 'new-model', displayName: 'New model', supportedEffortLevels: ['ultra']}];
const result = await discover(({prompt, options: supplied}) => {
  options = supplied;
  next = prompt[Symbol.asyncIterator]().next();
  return {
    initializationResult: async () => {
      assert.equal(await Promise.race([next.then(() => 'input'), Promise.resolve('empty')]), 'empty');
      return {models: rows};
    },
    supportedModels: async () => rows,
    close: () => { closed = true; }
  };
}, '/fake/claude', '/scratch');
assert.deepEqual(result, rows);
assert.deepEqual(await next, {value: undefined, done: true});
assert.equal(closed, true);
assert.equal(options.persistSession, false);
assert.equal(options.pathToClaudeCodeExecutable, '/fake/claude');
assert.deepEqual(options.settingSources, []);
assert.equal(options.settings.disableAllHooks, true);
assert.equal(options.settings.syncClaudeAiSkills, false);
assert.equal(options.settings.syncClaudeAiPlugins, false);
assert.deepEqual(options.mcpServers, {});
assert.equal(options.strictMcpConfig, true);
assert.deepEqual(options.tools, []);
assert.equal((await options.canUseTool()).behavior, 'deny');
let failedClosed = false;
await assert.rejects(discover(() => ({initializationResult: async () => {throw Error('login');},
  close: () => {failedClosed = true;}}), '/fake/claude', '/scratch'));
assert.equal(failedClosed, true);
console.log('Claude helper contracts passed (fake SDK; no user messages or inference).');
