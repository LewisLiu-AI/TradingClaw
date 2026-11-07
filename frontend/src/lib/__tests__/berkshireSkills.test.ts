import {
  AUTO_PROMPT,
  BERKSHIRE_CATEGORIES,
  BERKSHIRE_SKILLS,
  BERKSHIRE_TOTAL,
  QUICK_PICKS,
  getSkill,
} from "../berkshireSkills";

/**
 * The Berkshire catalogue is wired to real skill directories: `id` is passed to
 * the agent as load_skill("<id>"). A silent rename would turn a whole menu entry
 * into a no-op, so pin the exact list here.
 */
const EXPECTED_IDS = [
  "investment-research",
  "investment-team",
  "management-deep-dive",
  "private-company-research",
  "deep-company-series",
  "earnings-review",
  "earnings-team",
  "financial-data",
  "investment-checklist",
  "quality-screen",
  "industry-research",
  "industry-funnel",
  "bottleneck-hunter",
  "era-alpha",
  "portfolio-review",
  "thesis-tracker",
  "thesis-drift",
  "news-pulse",
  "income-investment",
  "dyp-ask",
  "wechat-article",
];

describe("berkshire skill catalogue", () => {
  it("exposes all 21 skills from scripts/user-skills/berkshire", () => {
    expect(BERKSHIRE_TOTAL).toBe(21);
    expect(BERKSHIRE_SKILLS.map((s) => s.id)).toEqual(EXPECTED_IDS);
  });

  it("has unique ids", () => {
    const ids = BERKSHIRE_SKILLS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("covers every category with at least one skill", () => {
    for (const category of BERKSHIRE_CATEGORIES) {
      expect(BERKSHIRE_SKILLS.some((s) => s.category === category.id)).toBe(true);
    }
  });

  it("builds prompts that name the skill and carry the subject", () => {
    for (const skill of BERKSHIRE_SKILLS) {
      const prompt = skill.prompt("测试标的 600000");
      expect(prompt).toContain(`load_skill("${skill.id}")`);
      expect(prompt).toContain("测试标的 600000");
    }
  });

  it("auto mode asks the agent to route itself and keeps the subject", () => {
    const prompt = AUTO_PROMPT("腾讯 00700");
    expect(prompt).toContain("腾讯 00700");
    expect(prompt).toContain("load_skill");
  });

  it("quick picks point at real skills", () => {
    expect(QUICK_PICKS.length).toBeGreaterThan(0);
    for (const pick of QUICK_PICKS) {
      expect(getSkill(pick.skillId)).toBeDefined();
    }
  });
});
