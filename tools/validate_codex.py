#!/usr/bin/env python3
"""Check the Codex plugin and marketplace against the rules in the Codex
source (codex-rs/core-plugins: manifest.rs, marketplace.rs) and the
plugin-creator spec. Run: python3 tools/validate_codex.py"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def check_path(errs: list[str], root: Path, field: str, value: str) -> None:
    if not value.startswith("./") or value == "./" or ".." in value.split("/"):
        errs.append(f"{field}: path must start with ./, stay in the plugin and not be ./ ({value})")
    elif not (root / value[2:]).exists():
        errs.append(f"{field}: {value} does not exist")


def check_interface(errs: list[str], where: str, iface: dict, root: Path | None = None) -> None:
    for k in ("displayName", "shortDescription", "developerName", "category"):
        if not iface.get(k):
            errs.append(f"{where}.interface.{k} is required")
    # Directory submission limits (developers.openai.com/plugins/deploy/submission)
    for k, n in (("displayName", 30), ("shortDescription", 30), ("longDescription", 4000), ("developerName", 80)):
        if len(iface.get(k) or "") > n:
            errs.append(f"{where}.interface.{k} is longer than {n} characters")
    if root is not None:
        for k in ("logo", "composerIcon"):
            if not iface.get(k):
                errs.append(f"{where}.interface.{k} is required for directory submission")
            else:
                check_path(errs, root, f"{where}.interface.{k}", iface[k])
    for k in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        if k in iface and not str(iface[k]).startswith("https://"):
            errs.append(f"{where}.interface.{k} must be an absolute https:// URL")
    prompts = iface.get("defaultPrompt", [])
    prompts = [prompts] if isinstance(prompts, str) else prompts
    if len(prompts) > 3:
        errs.append(f"{where}.interface.defaultPrompt: at most 3")
    for p in prompts:
        if not p.strip() or len(p) > 128:
            errs.append(f"{where}.interface.defaultPrompt: empty or over 128 characters: {p!r}")


def validate_plugin(root: Path) -> list[str]:
    errs: list[str] = []
    portable = root / "plugin.json"
    legacy = root / ".codex-plugin" / "plugin.json"
    if not portable.exists() and not legacy.exists():
        return [f"{root}: no plugin.json or .codex-plugin/plugin.json"]
    for mf in (portable, legacy):
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        where = str(mf.relative_to(ROOT))
        if m.get("name") != root.name or not KEBAB.match(m.get("name", "")):
            errs.append(f"{where}: name must be kebab-case and match the folder name {root.name}")
        if not SEMVER.match(m.get("version", "")):
            errs.append(f"{where}: version must be strict semver")
        if not m.get("description"):
            errs.append(f"{where}: description is required")
        if not (m.get("author") or {}).get("name"):
            errs.append(f"{where}: author.name is required")
        if "hooks" in m:
            errs.append(f"{where}: hooks are not allowed in directory plugins")
        for k in ("skills", "apps"):
            if isinstance(m.get(k), str):
                check_path(errs, root, f"{where}.{k}", m[k])
        iface = m.get("interface") or ((m.get("extensions") or {}).get("com.openai") or {}).get("interface")
        if not iface:
            errs.append(f"{where}: interface metadata is missing")
        else:
            check_interface(errs, where, iface, root)
        onboarding = ((m.get("extensions") or {}).get("com.openai") or {}).get("onboardingSkill")
        if onboarding:
            check_path(errs, root, f"{where}.onboardingSkill", onboarding)
        if "TODO" in mf.read_text(encoding="utf-8"):
            errs.append(f"{where}: leftover TODO")
    if portable.exists() and legacy.exists():
        a, b = json.loads(portable.read_text()), json.loads(legacy.read_text())
        if a["version"] != b["version"] or a["name"] != b["name"]:
            errs.append("plugin.json and .codex-plugin/plugin.json disagree on name or version")
    skills = sorted((root / "skills").glob("*/SKILL.md"))
    if not skills:
        errs.append("no skills/*/SKILL.md")
    for s in skills:
        text = s.read_text(encoding="utf-8")
        fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not fm:
            errs.append(f"{s.relative_to(ROOT)}: missing frontmatter")
            continue
        name = re.search(r"^name:\s*(.+)$", fm.group(1), re.M)
        desc = re.search(r"^description:\s*(.+)$", fm.group(1), re.M)
        if not name or name.group(1).strip() != s.parent.name:
            errs.append(f"{s.relative_to(ROOT)}: name must match the folder name")
        if not desc or len(desc.group(1)) > 1024:
            errs.append(f"{s.relative_to(ROOT)}: description missing or over 1024 characters")
        for ref in re.findall(r"`(\.\./[^`]+?\.md)`", text):
            if not (s.parent / ref).resolve().exists():
                errs.append(f"{s.relative_to(ROOT)}: broken reference {ref}")
    return errs


def validate_marketplace(path: Path) -> list[str]:
    errs: list[str] = []
    m = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent.parent.parent  # <repo>/.agents/plugins/marketplace.json -> <repo>
    if not m.get("name"):
        errs.append("marketplace: name is required")
    for p in m.get("plugins", []):
        src = p.get("source") or {}
        if src.get("source") != "local" or not str(src.get("path", "")).startswith("./"):
            errs.append(f"marketplace: {p.get('name')}: source must be local with a ./ path")
            continue
        root = (base / src["path"][2:]).resolve()
        if root.name != p.get("name"):
            errs.append(f"marketplace: {p.get('name')}: entry name must match the folder name")
        pol = p.get("policy") or {}
        if pol.get("installation") not in ("AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"):
            errs.append(f"marketplace: {p.get('name')}: policy.installation")
        if pol.get("authentication") not in ("ON_INSTALL", "ON_USE"):
            errs.append(f"marketplace: {p.get('name')}: policy.authentication")
        if not p.get("category"):
            errs.append(f"marketplace: {p.get('name')}: category is required")
        errs += validate_plugin(root)
    return errs


def main() -> int:
    errs = validate_marketplace(ROOT / ".agents" / "plugins" / "marketplace.json")
    if errs:
        print("\n".join(errs))
        return 1
    print("Codex plugin and marketplace: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
