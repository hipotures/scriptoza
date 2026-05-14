#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const args = new Map();
for (let i = 2; i < process.argv.length; i += 1) {
  const arg = process.argv[i];
  if (!arg.startsWith('--')) continue;
  const [key, inlineValue] = arg.split('=', 2);
  if (inlineValue !== undefined) {
    args.set(key, inlineValue);
  } else if (process.argv[i + 1] && !process.argv[i + 1].startsWith('--')) {
    args.set(key, process.argv[i + 1]);
    i += 1;
  } else {
    args.set(key, true);
  }
}

const mode = args.has('--delete') ? 'delete' : 'scan';
const chatUrl = args.has('--url') ? String(args.get('--url')) : null;
const limit = Number(args.get('--limit') || 5);
const delayMs = Number(args.get('--delay-ms') || 2500);
const cdpEndpoint = String(args.get('--cdp') || 'http://localhost:9222');
const envPath = String(args.get('--env') || path.join(process.cwd(), '.env'));
const ruleName = String(args.get('--reg') || args.get('--rule') || '');
const rawRegex = args.has('--regex');
const senderLabel = String(args.get('--sender-label') || 'You');
const includeAllSenders = args.has('--all-senders');

function usage() {
  console.log(`Usage:
  node delete-google-chat-messages.js --reg ENV_NAME [--limit N] [--delay-ms MS]
  node delete-google-chat-messages.js --delete --reg ENV_NAME --limit N --delay-ms MS

Rule values are literal text by default. Example .env:
  DELETE_LINKS="https://example.com/path/"

Options:
  --reg NAME          Environment variable name containing the match rule
  --delete            Actually delete matching messages. Omit for scan-only.
  --limit N           Maximum messages to delete in this run. Default: 5.
  --delay-ms MS       Delay after each delete. Minimum: 1000. Default: 2500.
  --url URL           Optional Google Chat conversation URL.
  --env PATH          Optional env file. Default: .env in current directory.
  --regex             Treat the env value as a raw JavaScript RegExp pattern.
  --sender-label TXT  Sender label for your own messages. Default: You.
  --all-senders       Scan all visible messages instead of only sender-label ones.
`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseEnvValue(value) {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const content = fs.readFileSync(filePath, 'utf8');
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = parseEnvValue(trimmed.slice(eq + 1));
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function buildMatcher(ruleValue) {
  if (!ruleValue) throw new Error(`Rule ${ruleName} is empty`);
  const pattern = rawRegex ? ruleValue : escapeRegExp(ruleValue);
  const regex = new RegExp(pattern);
  return {
    name: ruleName,
    value: ruleValue,
    regex,
    test(text) {
      regex.lastIndex = 0;
      return regex.test(text || '');
    },
  };
}

async function messageCandidates(page, matcher) {
  const groups = await page.locator('[role="group"]').evaluateAll(
    (elements, options) => {
      const { senderLabel: label, includeAll } = options;
      return elements.map((group, index) => {
        const text = group.textContent || '';
        const links = Array.from(group.querySelectorAll('a[href]')).map((link) => link.href);
        const ownMessage = includeAll || text.includes(label);
        return {
          index,
          text: text.replace(/\s+/g, ' ').trim(),
          links,
          ownMessage,
          haystack: `${text}\n${links.join('\n')}`,
        };
      });
    },
    { senderLabel, includeAll: includeAllSenders },
  );

  return groups.filter((candidate) => candidate.ownMessage && matcher.test(candidate.haystack));
}

async function getPage(browser, matcher) {
  const pages = browser.contexts().flatMap((context) => context.pages());
  if (chatUrl) {
    const exact = pages.find((page) => page.url() === chatUrl);
    if (exact) return exact;
    const fallback = pages.find((page) => page.url().includes('chat.google.com') && page.url().includes('/app/chat/'));
    return fallback || pages[0];
  }

  const chatPages = pages.filter((page) => page.url().includes('chat.google.com') && page.url().includes('/app/chat/'));
  if (chatPages.length === 0) return pages[0];

  let best = chatPages[0];
  let bestCount = -1;
  for (const page of chatPages) {
    const count = await messageCandidates(page, matcher).then((items) => items.length).catch(() => 0);
    if (count > bestCount) {
      best = page;
      bestCount = count;
    }
  }
  return best;
}

async function revealActionsForCandidate(page, matcher) {
  const groups = page.locator('[role="group"]');
  const count = await groups.count();
  for (let index = count - 1; index >= 0; index -= 1) {
    const group = groups.nth(index);
    const data = await group.evaluate((element) => {
      const text = element.textContent || '';
      const links = Array.from(element.querySelectorAll('a[href]')).map((link) => link.href);
      return { text, links, haystack: `${text}\n${links.join('\n')}` };
    });
    if (!matcher.test(data.haystack)) continue;
    if (!includeAllSenders && !data.text.includes(senderLabel)) continue;
    await page.keyboard.press('Escape').catch(() => {});
    await group.scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await group.hover({ force: true });
    await page.waitForTimeout(400);

    const links = group.locator('a[href]');
    const linkCount = await links.count();
    for (let linkIndex = 0; linkIndex < linkCount; linkIndex += 1) {
      const link = links.nth(linkIndex);
      const href = (await link.getAttribute('href')) || '';
      const text = await link.textContent().catch(() => '');
      if (matcher.test(`${href}\n${text || ''}`)) {
        await link.hover({ force: true });
        break;
      }
    }
    await page.waitForTimeout(900);

    const moreActions = page.getByRole('button', { name: 'More actions' }).last();
    if (await moreActions.isVisible().catch(() => false)) {
      try {
        await moreActions.click({ force: true, timeout: 5000 });
        await page.waitForTimeout(250);
        return { group, data };
      } catch (error) {
        console.log(`skip actions not clickable: ${data.links[0] || data.text.slice(0, 80)}`);
      }
    }
    console.log(`skip no actions: ${data.links[0] || data.text.slice(0, 80)}`);
  }
  return null;
}

async function deleteLatestVisibleCandidate(page, matcher) {
  const candidates = await messageCandidates(page, matcher);
  if (candidates.length === 0) return null;

  const actionTarget = await revealActionsForCandidate(page, matcher);
  if (!actionTarget) {
    throw new Error(`Could not reveal More actions for any visible message matching ${matcher.name}`);
  }

  await page.getByRole('menuitem', { name: 'Delete message' }).click();
  await page.waitForTimeout(400);

  const dialog = page
    .locator('[role="dialog"], [role="alertdialog"]')
    .filter({ hasText: 'Delete this entire thread permanently?' })
    .first();
  await dialog.waitFor({ state: 'visible', timeout: 5000 });
  const dialogText = (await dialog.textContent()) || '';
  if (!dialogText.includes('Delete this entire thread permanently?')) {
    await page.keyboard.press('Escape');
    throw new Error(`Delete dialog did not look like a message delete confirmation for rule ${matcher.name}`);
  }
  if (!matcher.test(dialogText)) {
    console.log(`dialog text is truncated; continuing with selected message for rule ${matcher.name}`);
  }

  await dialog.getByRole('button', { name: 'Delete' }).click();
  await page.waitForTimeout(1000);
  return actionTarget.data.links.find((link) => matcher.test(link)) || actionTarget.data.text.slice(0, 120);
}

async function main() {
  if (args.has('--help') || args.has('-h')) {
    usage();
    return;
  }
  if (!ruleName) throw new Error('Missing --reg ENV_NAME');
  if (!Number.isFinite(limit) || limit < 1) throw new Error('--limit must be a positive number');
  if (!Number.isFinite(delayMs) || delayMs < 1000) throw new Error('--delay-ms must be at least 1000');

  loadEnvFile(envPath);
  const ruleValue = process.env[ruleName];
  if (!ruleValue) throw new Error(`Missing rule ${ruleName}. Put it in ${envPath} or export it in the environment.`);
  const matcher = buildMatcher(ruleValue);

  const browser = await chromium.connectOverCDP(cdpEndpoint);
  const page = await getPage(browser, matcher);
  await page.bringToFront();
  if (chatUrl && !page.url().startsWith(chatUrl)) {
    await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
  }
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500);

  const candidates = await messageCandidates(page, matcher);
  console.log(
    `mode=${mode} rule=${ruleName} visible_matches=${candidates.length} limit=${limit} delay_ms=${delayMs}`,
  );
  for (const candidate of candidates.slice(-Math.min(candidates.length, 20))) {
    const firstMatch = candidate.links.find((link) => matcher.test(link)) || candidate.text.slice(0, 120);
    console.log(`${candidate.index}: ${firstMatch} :: ${candidate.text.slice(0, 120)}`);
  }

  if (mode !== 'delete') {
    await browser.close();
    return;
  }

  let deleted = 0;
  while (deleted < limit) {
    const visible = await messageCandidates(page, matcher);
    if (visible.length === 0) break;
    const label = await deleteLatestVisibleCandidate(page, matcher);
    if (!label) break;
    deleted += 1;
    console.log(`deleted ${deleted}/${limit}: ${label}`);
    await sleep(delayMs);
  }

  console.log(`done deleted=${deleted}`);
  await browser.close();
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
