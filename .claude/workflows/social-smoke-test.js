export const meta = {
  name: 'social-smoke-test',
  description: 'Real-world smoke test of the public-social-account-analyzer session-aware collectors (weibo / xiaohongshu / bilibili / douyin). For each entry in args.platforms it runs skill/scripts/collect.py against a real public account (optionally with an in-memory user-authorized cookie file), runs skill/scripts/run_pipeline.py --evidence-only, verifies the committed immutable workspaces, and greps the artifacts for cookie-value leakage. All output goes to isolated throwaway directories under args.outRoot (the orchestrator deletes them afterwards). Pass args = { platforms: [{ platform, url, cookieFile, limit, allowDiscovery }], outRoot }. Use whenever someone wants to check a real account end-to-end or re-validate a collector after a change.',
  phases: [
    { title: 'Collect' },
    { title: 'Analyze' },
    { title: 'Verify & aggregate' },
  ],
}

const REPO = '$CLAUDE_PROJECT_DIR'
const outRoot = (args && args.outRoot) || 'workspace/tmp'
const platforms = (args && args.platforms) || []

const COLLECTION_ARTIFACTS =
  'frozenset({"source/profile.json","source/posts.jsonl","normalized-posts.csv","task.json","collection-report.md"})'

function collectPrompt(p, index) {
  const cookieLine = p.cookieFile
    ? `COOKIE FILE: ${p.cookieFile}  (${p.platform} domain only; NEVER cat it, NEVER echo any value, NEVER copy it; reference values only as ****)`
    : 'NO COOKIE (anonymous path only).'
  const discoveryLine = p.allowDiscovery
    ? 'If the provided url yields ACCOUNT_UNAVAILABLE (e.g. a synthetic/404 profile), use WebSearch to find ONE real public account profile URL for this platform (e.g. an institutional/brand account), confirm the URL looks like a real profile page, and re-run collect.py into a NEW out dir. Document the substitution.'
    : 'Do NOT substitute the URL. If collection fails, report the failure as-is.'

  return `You are running a real-world smoke test of a collector in the public-social-account-analyzer skill.

REPO: ${REPO}
PLATFORM: ${p.platform}
URL: ${p.url}
LIMIT: ${p.limit || 10}
${cookieLine}
OUT DIR: ${outRoot}/${p.platform}-smoke-${index}
${discoveryLine}

STEPS:
1. cd ${REPO}
2. Run: python3 skill/scripts/collect.py "<url>" --limit ${p.limit || 10} ${
    p.cookieFile ? `--${p.platform}-cookie-file ${p.cookieFile}` : ''
  } --out ${outRoot}/${p.platform}-smoke-${index}
3. Verify .complete and manifest.json exist under the out dir.
4. Read task.json and manifest.json. Capture task_status, stop_reason, post count.
5. If a new URL was substituted, the actual out dir may differ; use the newest one created.

CONTRACT RULES (must hold):
- Never cat or echo the cookie file; never write cookie values into any output.
- Never bypass login / verification / rate-limit. A LOGIN_REQUIRED / VERIFICATION_REQUIRED / RATE_LIMITED / ACCESS_RESTRICTED / NO_PUBLIC_CONTENT stop is a legitimate, reportable outcome.
- report JSON exactly:
{
  "platform": "<platform>",
  "url_requested": "<original url>",
  "url_used": "<actual url used>",
  "url_substituted": true|false,
  "cookie_domain_accepted": true|false,
  "complete_exists": true|false,
  "collection_dir": "<out dir>",
  "task_status": "...",
  "stop_reason": "...",
  "posts_collected": N,
  "xhs_cards_collected": N,
  "browser_fallback_used": true|false,
  "errors": [...]
}`
}

function analyzePrompt(item, collectResult, index) {
  return `You are analyzing a completed collection workspace for the public-social-account-analyzer smoke test.

REPO: ${REPO}
PLATFORM: ${item.platform}
COLLECTION DIR: ${collectResult.collection_dir || `${outRoot}/${item.platform}-smoke-${index}`}
ANALYSIS OUT: ${outRoot}/${item.platform}-smoke-${index}-analysis

STEPS:
1. cd ${REPO}
2. Run: python3 skill/scripts/run_pipeline.py --input "<collection_dir>" --output ${outRoot}/${item.platform}-smoke-${index}-analysis --evidence-only
3. Read task.json and delivery-summary.json in the analysis dir. Capture delivery_kind, delivery_ready, strategy_ready, collected count, stop_reason.

RULES:
- If the collection has zero valid posts, the evidence-only path must produce delivery_ready=true, strategy_ready=false and MUST NOT fabricate a content strategy. That is the correct outcome.
- Do NOT invent metrics. report JSON exactly:
{
  "platform": "<platform>",
  "analysis_dir": "<analysis dir>",
  "delivery_kind": "...",
  "delivery_ready": true|false,
  "strategy_ready": true|false,
  "collected": N,
  "analysis_stop_reason": "...",
  "errors": [...]
}`
}

function verifyPrompt(item, results, index) {
  return `You are verifying the smoke-test workspaces for the public-social-account-analyzer.

REPO: ${REPO}
PLATFORM: ${item.platform}
COLLECTION DIR: ${results.collection_dir || `${outRoot}/${item.platform}-smoke-${index}`}
ANALYSIS DIR: ${results.analysis_dir || `${outRoot}/${item.platform}-smoke-${index}-analysis`}
COLLECTION ARTIFACTS SET: ${COLLECTION_ARTIFACTS}

STEPS:
1. cd ${REPO}
2. Verify the committed collection workspace:
   python3 -c "import sys; sys.path.insert(0,'skill/scripts'); from immutable_workspace import verify_committed_workspace as v; from immutable_workspace import ANALYSIS_ARTIFACTS; print('collection', v('${results.collection_dir}', allowed_artifacts=${COLLECTION_ARTIFACTS}))"
   (if the dir doesn't exist, record that instead of an exception)
3. If an analysis dir exists, verify it with allowed_artifacts=ANALYSIS_ARTIFACTS.
4. Cookie-leak check — must produce NO output:
   grep -rInE "ALF=|SUB=|SCF=|XSRF-TOKEN|web_session|id_token|a1=|gid=|Cookie:" "<collection_dir>" "<analysis_dir>" 2>/dev/null | head -5
5. Confirm no cookie file was copied into either workspace tree.

report JSON exactly:
{
  "platform": "<platform>",
  "collection_verified": true|false|"missing",
  "collection_commit_sha256": "...",
  "analysis_verified": true|false|"missing",
  "analysis_commit_sha256": "...",
  "cookie_values_leaked": true|false,
  "leak_evidence": ["..."],
  "errors": [...]
}`
}

const results = await pipeline(
  platforms,
  (p, _item, i) =>
    agent(collectPrompt(p, i), {
      label: `collect:${p.platform}`,
      phase: 'Collect',
      agentType: 'general-purpose',
    }),
  (collectResult, p, i) =>
    agent(analyzePrompt(p, collectResult, i), {
      label: `analyze:${p.platform}`,
      phase: 'Analyze',
      agentType: 'general-purpose',
    }),
  (verifyInput, p, i) =>
    agent(verifyPrompt(p, verifyInput, i), {
      label: `verify:${p.platform}`,
      phase: 'Verify & aggregate',
      agentType: 'general-purpose',
    })
)

phase('Verify & aggregate')

const combined = results.filter(Boolean).map((r) => ({
  platform: r.platform,
  url_used: r.url_used,
  task_status: r.task_status,
  stop_reason: r.stop_reason,
  posts_collected: r.posts_collected,
  delivery_ready: r.delivery_ready,
  strategy_ready: r.strategy_ready,
  collection_verified: r.collection_verified,
  cookie_values_leaked: r.cookie_values_leaked,
  errors: r.errors,
}))

const aggregate = await agent(
  `Aggregate this smoke-test summary into a markdown comparison table plus a short verdict.

${JSON.stringify(combined, null, 2)}

For each platform row, show: platform, url_used, task_status/stop_reason, posts_collected, delivery_ready, strategy_ready, collection_verified, cookie_leak.

Then give a 3-5 sentence verdict on whether the new session-aware collection workflow works end-to-end on real platforms. Be honest about failures — a LOGIN_REQUIRED / NO_PUBLIC_CONTENT / ACCOUNT_UNAVAILABLE stop is itself a valid contract outcome to report, not something to hide.

Output ONLY the markdown table and the verdict paragraph.`,
  { label: 'aggregate', phase: 'Verify & aggregate', agentType: 'general-purpose' }
)

return { results: combined, aggregate }
