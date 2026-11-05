### Install the hooks plugin on one machine in one step (2026-11-02)

- Every plugin download now carries **install-local.ps1** (Windows) or **install-local.sh** (macOS and Linux). Run it from the unzipped folder: it builds a local marketplace, installs the plugin for your user with the Claude Code CLI, and lists your plugins. Use it to test on one machine; the desktop app's Code tab cannot run `/plugin`.
- The hooks guide's **Publish** section now has three paths: one machine, fleet (managed bundle plus the plugin), and organization library upload, with what we saw on the Windows desktop app.
- What changes for existing installs: nothing to do. Download the plugin again to get the installer.
