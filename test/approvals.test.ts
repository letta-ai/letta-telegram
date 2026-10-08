import { describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";
import { ApprovalManager, type ApprovalApi } from "../src/telegram/approvals.ts";
import type { ApprovalRequest } from "../src/types.ts";
const config = (extra: Record<string, string> = {}) =>
  loadConfig({
    TELEGRAM_BOT_TOKEN: "x",
    LETTA_API_KEY: "y",
    LETTA_AGENT_ID: "agent-1",
    TELEGRAM_ADMIN_USER_IDS: "1",
    APPROVAL_TIMEOUT_SECONDS: "1",
    ...extra,
  });
const req: ApprovalRequest = {
  route: { chatId: "-100", topicId: "8" },
  requesterId: "2",
  toolName: "Bash",
  toolInput: { command: "<danger>" },
};
function fake() {
  const sent: any[] = [],
    edits: any[] = [],
    answers: any[] = [];
  const api: ApprovalApi = {
    async sendMessage(...a: any[]) {
      sent.push(a);
      return { message_id: 10 };
    },
    async editMessageText(...a: any[]) {
      edits.push(a);
    },
    async answerCallbackQuery(...a: any[]) {
      answers.push(a);
    },
  };
  return { api, sent, edits, answers };
}
const data = (f: ReturnType<typeof fake>) => f.sent[0][2].reply_markup.inline_keyboard[0][0].callback_data;
describe("approvals", () => {
  test("admins authorize and requests settle exactly once", async () => {
    const f = fake(),
      m = new ApprovalManager(config(), f.api),
      p = m.request(req);
    await Bun.sleep(0);
    const d = data(f);
    await Promise.all([m.handle("q1", "1", d), m.handle("q2", "1", d)]);
    expect(await p).toMatchObject({ allow: true, decidedBy: "1" });
    expect(m.pendingCount).toBe(0);
    expect(f.edits.at(-1)?.[3].reply_markup.inline_keyboard).toEqual([]);
  });
  test("unauthorized clicks alert and do not settle", async () => {
    const f = fake(),
      m = new ApprovalManager(config(), f.api),
      p = m.request(req);
    await Bun.sleep(0);
    await m.handle("q", "9", data(f));
    expect(m.pendingCount).toBe(1);
    expect(f.answers[0][1]).toMatchObject({ show_alert: true });
    await m.cancelAll();
    expect((await p).allow).toBe(false);
  });
  test("requester mode permits requester", async () => {
    const f = fake(),
      m = new ApprovalManager(config({ APPROVAL_MODE: "requester" }), f.api),
      p = m.request({ ...req, approvalMode: "requester" });
    await Bun.sleep(0);
    await m.handle("q", "2", data(f).replace(":y", ":n"));
    expect(await p).toMatchObject({ allow: false, decidedBy: "2" });
  });
  test("timeout resolves and removes controls", async () => {
    const f = fake(),
      m = new ApprovalManager(config({ APPROVAL_TIMEOUT_SECONDS: "0" }), f.api),
      p = m.request(req);
    expect((await p).message).toMatch(/timed out/i);
    await Bun.sleep(0);
    expect(f.edits.at(-1)?.[2]).toMatch(/Timed out/);
  });
});
