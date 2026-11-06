#!/usr/bin/env python3
"""neovim-docs: Hermes's no-agent cron job (daily) that builds $HERMES_HOME/docs/neovim, the
Neovim documentation the `ops` tools nvim_help / nvim_help_read search (the neovim-help skill).

dev-cloud is a cockpit VM, so its own copies are the cockpit's: the Neovim install-vm.sh pins
(~/.local/bin/nvim), the plugins lazy-lock.json pins (~/.local/share/nvc-nvim/lazy) and the
cockpit deployed into ~/.local/share/nvc/src. The tree it writes:

  nvim/*.txt                 Neovim's runtime help, the version the cockpit runs
  plugins/NAME/...           each locked plugin's doc/ (help and markdown), docs/*.md, README.md
  cockpit/README.md, API.md  the deployed cockpit's own docs
  cockpit/guide.json, .md    the cockpit guide (`nvc-vm guide --json`, its live keymaps), as text
  keymaps.md                 every global keymap of the cockpit's Neovim (LazyVim, plugins, cockpit)
  tags.tsv                   tag, file, line: every *help-tag* and every markdown heading
  MANIFEST.json              when, from which versions and commits, and what does not match a pin

It builds next to the old tree and swaps only a complete one, so a failed run leaves the last
good docs in place. Prints nothing when it worked (the cron job stays silent), the reason and
exit 1 when not (the cron job delivers that as an alert).
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOME = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
OUT = os.path.expanduser(os.environ.get("HERMES_NVIM_DOCS", os.path.join(HOME, "docs", "neovim")))
NVIM = os.path.expanduser(os.environ.get("NVIM_BIN", "~/.local/bin/nvim"))
NVC_VM = os.path.expanduser(os.environ.get("NVC_VM", "~/.local/bin/nvc-vm"))
LAZY = os.path.expanduser(os.environ.get("NVC_LAZY_DIR", "~/.local/share/nvc-nvim/lazy"))
COCKPIT = os.path.expanduser(os.environ.get("NVC_SRC", "~/.local/share/nvc/src"))
APPNAME = "nvc-nvim"
NVIM_TIMEOUT_S = 120

# A tree below these is a broken source, not a smaller release: keep the old one.
MIN_RUNTIME_FILES = 100
MIN_TAGS = 10000
MIN_KEYMAPS = 50

HELP_TAG = re.compile(r"(?:^|(?<=\s))\*([^\s*|]+)\*(?=\s|$)")
MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
DOC_EXT = (".txt", ".md")

# Every global keymap once VeryLazy has run, as guide.lua's cli() waits for it: lazy-loaded
# plugins' keys exist from then on as their lazy.nvim stubs, with their desc.
KEYMAP_LUA = r"""
local function dump()
  local out = {}
  for _, mode in ipairs({ "n", "x", "s", "o", "i", "c", "t" }) do
    for _, m in ipairs(vim.api.nvim_get_keymap(mode)) do
      table.insert(out, { mode = mode, lhs = m.lhs, desc = m.desc or "", rhs = m.rhs or "" })
    end
  end
  io.stdout:write(vim.json.encode({ v = 1, leader = vim.g.mapleader or "\\", maps = out }) .. "\n")
  io.stdout:flush()
  os.exit(0)
end
vim.api.nvim_create_autocmd("VimEnter", { once = true, callback = function()
  vim.schedule(function()
    if not vim.g.did_very_lazy then
      vim.g.did_very_lazy = true
      vim.api.nvim_exec_autocmds("User", { pattern = "VeryLazy", modeline = false })
    end
    vim.defer_fn(dump, 500)
  end)
end })
vim.defer_fn(function() io.stdout:write("{}\n"); os.exit(1) end, 60000)
"""


class Failed(Exception):
    pass


def run(cmd, env=None, timeout=NVIM_TIMEOUT_S) -> str:
    try:
        r = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise Failed(f"{os.path.basename(cmd[0])} did not finish in {timeout} s") from None
    except OSError as e:
        raise Failed(f"{cmd[0]}: {e}") from None
    if r.returncode != 0:
        raise Failed(f"{' '.join(cmd[:3])} exit {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def last_json(text: str):
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def nvim_version() -> str:
    first = run([NVIM, "--version"]).splitlines()[0]  # NVIM v0.12.5
    return first.split()[-1].lstrip("v")


def pinned_nvim() -> str:
    try:
        with open(os.path.join(COCKPIT, "install-vm.sh")) as f:
            m = re.search(r"^NVIM_VERSION=(\S+)", f.read(), re.MULTILINE)
    except OSError:
        return ""
    return m.group(1) if m else ""


def runtime_docs(dest: str) -> int:
    rt = run([NVIM, "--clean", "--headless", "+lua io.write(vim.env.VIMRUNTIME)", "+q"]).strip()
    src = os.path.join(rt, "doc")
    if not os.path.isdir(src):
        raise Failed(f"Neovim's runtime has no doc/ ({src})")
    os.makedirs(dest)
    n = 0
    for name in sorted(os.listdir(src)):
        if name.endswith(".txt"):
            shutil.copy2(os.path.join(src, name), dest)
            n += 1
    return n


def git_head(path: str) -> str:
    try:
        return run(["git", "-C", path, "rev-parse", "HEAD"], timeout=20).strip()
    except Failed:
        return ""


def plugin_docs(dest: str) -> dict:
    with open(os.path.join(COCKPIT, "nvim", "lazy-lock.json")) as f:
        lock = json.load(f)
    out = {}
    for name in sorted(lock):
        src = os.path.join(LAZY, name)
        if not os.path.isdir(src):
            out[name] = {"lock": lock[name].get("commit", ""), "commit": "", "files": 0, "missing": True}
            continue
        files = 0
        for sub in ("doc", "docs"):
            root = os.path.join(src, sub)
            for d, dirs, names in os.walk(root):
                dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in ("node_modules", "public"))
                for fn in sorted(names):
                    if fn.endswith(DOC_EXT):
                        rel = os.path.relpath(os.path.join(d, fn), src)
                        os.makedirs(os.path.join(dest, name, os.path.dirname(rel)), exist_ok=True)
                        shutil.copy2(os.path.join(d, fn), os.path.join(dest, name, rel))
                        files += 1
        if os.path.isfile(os.path.join(src, "README.md")):
            os.makedirs(os.path.join(dest, name), exist_ok=True)
            shutil.copy2(os.path.join(src, "README.md"), os.path.join(dest, name, "README.md"))
            files += 1
        out[name] = {"lock": lock[name].get("commit", ""), "commit": git_head(src), "files": files}
    return out


def guide_markdown(g: dict) -> str:
    """The guide as lines grep finds: each key on one line with the place it works in."""
    out = [f"# The cockpit guide (cockpit {g.get('sha', '')[:12]}, built {g.get('at_text', '')})", ""]
    out += ["## Keys that work everywhere", ""]
    for k in g.get("keys") or []:
        out.append(f"- `{k.get('key', '')}`: {k.get('text', '')}")
    for p in g.get("places") or []:
        out += ["", f"## Keys in the {p.get('name')} place", ""]
        for grp in p.get("groups") or []:
            for e in grp.get("entries") or []:
                out.append(f"- `{e.get('key', '')}` ({p.get('name')}, {grp.get('label', '')}): {e.get('desc', '')}")
    out += ["", "## Marks in the agent list", ""]
    for m in g.get("marks") or []:
        out.append(f"- {m.get('mark', '')}: {m.get('text', '')}")
    out += ["", "## Tips", ""]
    for t in g.get("tips") or []:
        out.append(f"- {t if isinstance(t, str) else t.get('text', '')}")
    for s in g.get("sections") or []:
        out += ["", f"## {s.get('title', '')}", ""]
        for para in s.get("paragraphs") or []:
            out += [para, ""]
    return "\n".join(out) + "\n"


def cockpit_docs(dest: str) -> str:
    os.makedirs(dest)
    for name in ("README.md", "API.md"):
        shutil.copy2(os.path.join(COCKPIT, name), dest)
    g = last_json(run([NVC_VM, "guide", "--json"]))
    if not isinstance(g, dict) or g.get("v") != 1 or not g.get("places"):
        raise Failed("`nvc-vm guide --json` gave no guide")
    with open(os.path.join(dest, "guide.json"), "w") as f:
        json.dump(g, f, ensure_ascii=False)
    with open(os.path.join(dest, "guide.md"), "w") as f:
        f.write(guide_markdown(g))
    try:
        with open(os.path.join(COCKPIT, ".nvc-sha")) as f:
            return f.read().strip()
    except OSError:
        return g.get("sha", "")


def keymaps(path: str) -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(KEYMAP_LUA)
    try:
        env = dict(os.environ, NVIM_APPNAME=APPNAME)
        d = last_json(run([NVIM, "--headless", "-i", "NONE", f"+luafile {f.name}"], env=env))
    finally:
        os.unlink(f.name)
    if not isinstance(d, dict) or d.get("v") != 1:
        raise Failed("the cockpit's Neovim did not list its keymaps")
    leader = d.get("leader") or "\\"
    names = {"n": "normal", "x": "visual", "s": "select", "o": "operator-pending", "i": "insert",
             "c": "command-line", "t": "terminal"}
    lines = ["# Keymaps of the cockpit's Neovim (LazyVim, its plugins, the cockpit)",
             "", "Global keymaps only (a picker's or a buffer's own keys are in that plugin's docs).",
             f"`<leader>` is `{'<Space>' if leader == ' ' else leader}`. One line per key: mode, key, what it does.", ""]
    n = 0
    for m in sorted(d.get("maps") or [], key=lambda m: ("nxsoict".index(m["mode"]), m["lhs"].lower())):
        lhs, desc = m["lhs"], m["desc"] or m["rhs"]
        if not desc or lhs.startswith(("<Plug>", "<SNR>")):
            continue
        # nvim_get_keymap's lhs is key notation already, except that a space is a literal space
        if lhs.startswith(leader):
            lhs = "<leader>" + lhs[len(leader):]
        lhs = lhs.replace(" ", "<Space>")
        lines.append(f"{names[m['mode']]:<16} {lhs:<20} {' '.join(desc.split())[:200]}")
        n += 1
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return n


def index(root: str) -> int:
    rows = []
    for d, dirs, names in os.walk(root):
        dirs.sort()
        for fn in sorted(names):
            if not fn.endswith(DOC_EXT):
                continue
            path = os.path.join(d, fn)
            rel = os.path.relpath(path, root)
            fence = False
            with open(path, errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if fn.endswith(".txt"):
                        for tag in HELP_TAG.findall(line):
                            rows.append(f"{tag}\t{rel}\t{n}")
                    else:
                        if line.lstrip().startswith("```"):
                            fence = not fence
                        m = None if fence else MD_HEADING.match(line)
                        if m:
                            # `Snacks.picker.actions.qflist()` is looked up without its backticks
                            rows.append(f"{m.group(2).replace('`', '').strip()}\t{rel}\t{n}")
    with open(os.path.join(root, "tags.tsv"), "w") as f:
        f.write("\n".join(rows) + "\n")
    return len(rows)


def build(tmp: str) -> dict:
    version, pin = nvim_version(), pinned_nvim()
    runtime = runtime_docs(os.path.join(tmp, "nvim"))
    plugins = plugin_docs(os.path.join(tmp, "plugins"))
    sha = cockpit_docs(os.path.join(tmp, "cockpit"))
    maps = keymaps(os.path.join(tmp, "keymaps.md"))
    tags = index(tmp)
    if runtime < MIN_RUNTIME_FILES:
        raise Failed(f"only {runtime} runtime help files")
    if tags < MIN_TAGS:
        raise Failed(f"only {tags} tags")
    if maps < MIN_KEYMAPS:
        raise Failed(f"only {maps} keymaps")
    drift = [f"nvim {version}, the cockpit pins {pin}"] if pin and pin != version else []
    drift += [f"{n} at {p['commit'][:7] or 'missing'}, lazy-lock.json says {p['lock'][:7]}"
              for n, p in plugins.items() if p["commit"] != p["lock"]]
    manifest = {
        "built": datetime.datetime.now().astimezone().isoformat(timespec="minutes"),
        "nvim": version, "nvim_pinned": pin, "cockpit": sha[:12], "runtime_files": runtime,
        "keymaps": maps, "tags": tags, "plugins": plugins, "drift": drift,
    }
    with open(os.path.join(tmp, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def main() -> int:
    parent = os.path.dirname(OUT)
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".neovim-new-", dir=parent)
    try:
        build(tmp)
    except (Failed, OSError, ValueError, KeyError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"Neovim docs NOT refreshed, the last good copy stays in {OUT}: {e}")
        return 1
    old = None
    if os.path.exists(OUT):
        old = tempfile.mkdtemp(prefix=".neovim-old-", dir=parent)
        os.rename(OUT, os.path.join(old, "neovim"))
    os.rename(tmp, OUT)
    if old:
        shutil.rmtree(old, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
