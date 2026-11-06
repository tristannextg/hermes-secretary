---
name: neovim-help
description: Answer every Neovim question ("how do I close all other windows", "what does <C-q> do in the snacks picker", "what is <leader>wd", "how do I search and replace across files", "which LazyVim key opens lazygit", "how does :g work") from the docs of the Neovim Tristan actually runs, never from memory - Neovim's own :help at the cockpit's version, LazyVim and every plugin it uses, the cockpit's live keymaps, the cockpit's README, API and guide.
version: 1.0.0
metadata:
  hermes:
    tags: [cockpit, neovim, help]
    related_skills: [cockpit-help]
---

# Neovim help

Tristan uses Neovim through his cockpit: LazyVim, snacks.nvim and the cockpit's own plugin. Your
`ops` tools `nvim_help` and `nvim_help_read` search a copy of exactly that setup's docs, rebuilt
every night (`neovim-docs` job): Neovim's runtime help at the version the cockpit pins, every
plugin in its lazy-lock.json (doc/, docs/, README), `keymaps.md` (every global key of his
Neovim, LazyVim's and the cockpit's included, with what it does) and the cockpit's README, API
and guide. Your shell and file tools cannot see these files; only the two tools can.

## Procedure

1. Say what he would type, then search for it:
   - a command, key or option you can name: its help tag first. Tags are written as in Vim's
     help: `:only`, `:s_flags`, `CTRL-W_o`, `i_CTRL-R` (insert mode), `v_o` (visual), `c_CTRL-R`
     (command line), `'hidden'` (option, with quotes), `nvim_buf_set_lines()`, `vim.keymap.set()`,
     `snacks-picker`. One exact hit gives its whole entry. Plugin tags are often generated and
     odd (`lazy.nvim-🔌-plugin-spec`): search a part (`plugin-spec`) and pick from the list.
   - otherwise two to four distinctive words, keys in the plugin's own spelling (`<c-q>`, not
     "control q"): `nvim_help {query: "picker <c-q>"}`. A word that names the plugin or module
     ("snacks picker") also matches by file name. Narrow with `in`: `nvim`, `cockpit`,
     `keymaps.md` or a plugin dir (`snacks.nvim`, `LazyVim`, `which-key.nvim`).
2. "What does key X do" / "which key does Y" in his editor: `keymaps.md` is the truth for global
   keys (`<leader>` is Space): `nvim_help {query: "<leader>wd", in: "keymaps.md"}` or words
   ("delete window"). A key that is not there may be local to a window (a picker, the explorer,
   lazygit): look in that plugin's docs, then Neovim's help.
3. A question about the cockpit itself (its agent list, inbox, chats, Hermes pane, `Alt-…` keys):
   follow `cockpit-help` first. `nvim_help {in: "cockpit"}` searches the same README, API and
   guide as deployed last night; use it when `cockpit_doc` has nothing or says it is old.
4. Read more when the hit is cut short: `nvim_help_read {tag}` for a whole entry, or `{file,
   line, lines}` around a grep hit.
5. Answer with the exact key or command (`<C-w>o` or `:only`), one sentence of what it does, and
   where it comes from: the help tag and file (`:help CTRL-W_o`, nvim/windows.txt) so he can
   read it himself. If his setup changes the stock answer (LazyVim maps the key to something
   else, the cockpit takes it), say both, his setup first. Quote the doc for anything subtle.
6. Nothing found: say so ("the docs don't cover …"), and say what you searched. Never invent a
   key, an option or a command.

## Pitfalls

- `nvim_help` prints which Neovim and cockpit version the docs are from. If it says STALE or
  lists something "not what the cockpit pins", mention it when the answer depends on it.
- Help tags are case-sensitive (`CTRL-W_o` and `CTRL-W_O` differ); the tool tries the exact
  case, then any case, then lists tags containing the query: pick from that list.
- Plugin keys in `keymaps.md` are LazyVim's stubs: the key and its description are right, but
  some only load the plugin on first use; that is normal.
- In a chat window of the cockpit, keys go to Claude Code, not to Neovim, until he leaves its
  input (`Alt-q`): mention it when he asks why a Neovim key does nothing in a chat.
