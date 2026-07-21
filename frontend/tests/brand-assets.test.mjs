import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(frontendRoot, "..");

test("selected brand assets are promoted to stable production paths", () => {
  assert.equal(
    existsSync(join(frontendRoot, "public", "brand", "aragonteam-lockup.png")),
    true,
  );
  assert.equal(
    existsSync(join(frontendRoot, "public", "brand", "aragonteam-icon.png")),
    true,
  );
  assert.equal(existsSync(join(frontendRoot, "app", "icon.png")), true);
});

test("selected lockup replaces text-only branding in the main brand surfaces", () => {
  const sidebar = readFileSync(
    join(frontendRoot, "components", "layout", "Sidebar.tsx"),
    "utf8",
  );
  const login = readFileSync(join(frontendRoot, "app", "login", "page.tsx"), "utf8");
  const layout = readFileSync(join(frontendRoot, "app", "layout.tsx"), "utf8");

  assert.match(sidebar, /<BrandLockup/);
  assert.doesNotMatch(sidebar, />\s*A\s*<\/span>/);
  assert.equal((login.match(/<BrandLockup/g) ?? []).length, 2);
  assert.match(layout, /\/brand\/aragonteam-icon\.png/);
});

test("discarded logo candidates are removed after promotion", () => {
  assert.equal(
    existsSync(join(projectRoot, "docs", "imgs", "logo-candidates")),
    false,
  );
});
